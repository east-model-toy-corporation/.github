"""
sync_org.py
-----------
每日由 GitHub Actions 執行。

步驟：
1. 從 GitHub API 抓全部 org repos
2. Clone p028，讀取 03-系統文檔/ 建立 pXXX → 中文名稱對照表
3. 依 pXXX prefix 分組 repos
4. 產生 profile/README.md（組織首頁）
5. 更新 p028 03-系統文檔/：補缺少的 stub 筆記、同步狀態欄位
6. Push p028 變更

環境變數：
  GITHUB_TOKEN  - PAT，需要 repo + read:org 權限
  ORG_NAME      - east-model-toy-corporation
  P028_REPO     - p028-Automation-Intelligence-Bureau
"""

import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml
from github import Github

# ── 常數 ──────────────────────────────────────────────────────────────────

ORG_NAME = os.environ["ORG_NAME"]
P028_REPO = os.environ["P028_REPO"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

STATUS_MAP = {
    "status-active": "運行中",
    "status-maintenance": "維護中",
    "status-archived": "已封存",
}

STATUS_EMOJI = {
    "status-active": "✅",
    "status-maintenance": "🚧",
    "status-archived": "🗑️",
}

DEPT_DISPLAY = {
    "dept-商品部": "商品部",
    "dept-行銷部": "行銷部",
    "dept-客服部": "客服部",
    "dept-商開部": "商開部",
    "dept-倉儲部": "倉儲部",
    "dept-財務部": "財務部",
}

# ── GitHub API ─────────────────────────────────────────────────────────────

def fetch_all_org_repos(g: Github) -> list[dict]:
    org = g.get_organization(ORG_NAME)
    repos = []
    for repo in org.get_repos():
        prefix_match = re.match(r"^(p\d+)-", repo.name)
        prefix = prefix_match.group(1) if prefix_match else None
        topics = repo.get_topics()
        repos.append({
            "name": repo.name,
            "url": repo.html_url,
            "description": repo.description or "",
            "topics": topics,
            "pushed_at": repo.pushed_at.strftime("%Y-%m-%d") if repo.pushed_at else "",
            "prefix": prefix,
        })
    return repos

# ── p028 筆記操作 ──────────────────────────────────────────────────────────

def clone_p028(tmp_dir: str) -> Path:
    p028_path = Path(tmp_dir) / P028_REPO
    subprocess.run(
        ["git", "clone", f"https://x-access-token:{GITHUB_TOKEN}@github.com/{ORG_NAME}/{P028_REPO}.git", str(p028_path)],
        check=True, capture_output=True,
    )
    return p028_path


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """回傳 (frontmatter dict, body_without_frontmatter)"""
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 3)
    if end == -1:
        return {}, content
    fm_text = content[3:end].strip()
    body = content[end + 4:].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, body


def build_project_map(notes_dir: Path) -> dict[str, str]:
    """
    掃 03-系統文檔/*.md，回傳 {"p007": "倉儲流程改造王", ...}
    中文名稱 = 檔名去掉 pXXX- prefix 和 .md 後綴
    同一 prefix 有多個筆記時取字母序最小的（通常是大專案總覽）
    """
    project_map: dict[str, str] = {}
    for md_file in sorted(notes_dir.glob("*.md")):
        m = re.match(r"^(p\d+)-(.+)\.md$", md_file.name)
        if not m:
            continue
        prefix, name = m.group(1), m.group(2)
        if prefix not in project_map:
            project_map[prefix] = name
    return project_map


def find_note_for_repo(notes_dir: Path, repo_url: str) -> Path | None:
    """找 涉及檔案 中包含 repo_url 的筆記"""
    for md_file in notes_dir.glob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(content)
        files = fm.get("涉及檔案") or []
        if isinstance(files, str):
            files = [files]
        if any(repo_url in str(f) for f in files):
            return md_file
    return None


def update_note_frontmatter(note_path: Path, updates: dict):
    """只更新指定的 frontmatter 欄位，其餘內容不動"""
    content = note_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)
    fm.update(updates)
    new_fm = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    new_content = f"---\n{new_fm}\n---\n\n{body}"
    note_path.write_text(new_content, encoding="utf-8")


def create_stub_note(notes_dir: Path, repo: dict, today: str):
    """為沒有對應筆記的 REPO 建立 stub"""
    filename = f"{repo['name']}.md"
    note_path = notes_dir / filename

    status_topic = next((t for t in repo["topics"] if t in STATUS_MAP), None)
    status_value = STATUS_MAP.get(status_topic, "運行中")

    fm = {
        "專案編號": repo["prefix"] or "",
        "用途說明": repo["description"],
        "涉及檔案": [repo["url"]],
        "讀取資料源": [],
        "寫入資料源": [],
        "相依系統": [],
        "所有者": "",
        "狀態": status_value,
        "最後審計日期": today,
        "備註": "",
    }
    fm_text = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    body = f"""# {repo['name']}

## 說明

{repo['description']}

---
<!-- ↓ 以下為人工維護區域，腳本不會覆蓋 ↓ -->

## 上下游

## 備忘錄
"""
    note_path.write_text(f"---\n{fm_text}\n---\n\n{body}", encoding="utf-8")


def update_p028_notes(repos: list[dict], p028_path: Path):
    notes_dir = p028_path / "03-系統文檔"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for repo in repos:
        status_topic = next((t for t in repo["topics"] if t in STATUS_MAP), None)
        if not status_topic:
            continue  # 未設定狀態 Topic 的 REPO 不動 p028

        note_path = find_note_for_repo(notes_dir, repo["url"])
        if note_path:
            update_note_frontmatter(note_path, {
                "狀態": STATUS_MAP[status_topic],
                "最後審計日期": today,
            })
        else:
            create_stub_note(notes_dir, repo, today)

    # Push p028
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=p028_path, check=True)
    subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=p028_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=p028_path, check=True)
    result = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=p028_path)
    if result.returncode != 0:
        subprocess.run(["git", "commit", "-m", "chore: auto-sync from org navigation [skip ci]"], cwd=p028_path, check=True)
        remote = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{ORG_NAME}/{P028_REPO}.git"
        subprocess.run(["git", "push", remote, "main"], cwd=p028_path, check=True)

# ── README 產生 ────────────────────────────────────────────────────────────

def group_by_prefix(repos: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for repo in repos:
        key = repo["prefix"] or "__unclassified__"
        groups.setdefault(key, []).append(repo)
    # 每組內依 REPO 名稱排序
    for key in groups:
        groups[key].sort(key=lambda r: r["name"])
    return groups


def repo_row(repo: dict, p028_base_url: str, notes_dir: Path | None) -> str:
    name_link = f"[{repo['name']}]({repo['url']})"
    desc = repo["description"] or "—"

    depts = [DEPT_DISPLAY[t] for t in repo["topics"] if t in DEPT_DISPLAY]
    dept_str = " · ".join(depts) if depts else "—"

    status_topic = next((t for t in repo["topics"] if t in STATUS_EMOJI), None)
    status_str = STATUS_EMOJI.get(status_topic, "❓")

    # Wiki 連結
    wiki_str = "—"
    if notes_dir:
        note_path = find_note_for_repo(notes_dir, repo["url"])
        if note_path:
            encoded = note_path.name.replace(" ", "%20")
            wiki_url = f"{p028_base_url}/blob/main/03-系統文檔/{encoded}"
            wiki_str = f"[📄]({wiki_url})"

    return f"| {name_link} | {desc} | {dept_str} | {status_str} | {wiki_str} |"


def generate_org_readme(groups: dict[str, list[dict]], project_map: dict[str, str], notes_dir: Path | None):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    p028_url = f"https://github.com/{ORG_NAME}/{P028_REPO}"

    lines = [
        "# 🏭 East Model Toy Corporation",
        "",
        f"> 找到你要的工具，避免重複造輪子。  ",
        f"> 更新時間：{now} UTC（每日自動同步）  ",
        f"> 📚 [完整知識庫 →]({p028_url})",
        "",
        "---",
        "",
    ]

    # 有 prefix 的分組（排除未分類）
    sorted_prefixes = sorted(k for k in groups if k != "__unclassified__")

    for prefix in sorted_prefixes:
        repos = groups[prefix]
        cn_name = project_map.get(prefix, "")
        section_title = f"{prefix} · {cn_name}" if cn_name else prefix
        lines.append(f"## 📦 {section_title}")
        lines.append("")
        lines.append("| REPO | 說明 | 部門 | 狀態 | Wiki |")
        lines.append("|------|------|------|------|------|")
        for repo in repos:
            lines.append(repo_row(repo, p028_url, notes_dir))
        lines.append("")

    # 未分類
    unclassified = groups.get("__unclassified__", [])
    if unclassified:
        lines.append("## ❓ 未分類")
        lines.append("")
        lines.append("> 以下 REPO 尚未設定 `dept-xxx` Topic，請協助補上。")
        lines.append("")
        lines.append("| REPO | 最後推送 |")
        lines.append("|------|----------|")
        for repo in sorted(unclassified, key=lambda r: r["name"]):
            lines.append(f"| [{repo['name']}]({repo['url']}) | {repo['pushed_at']} |")
        lines.append("")

    readme_path = Path("profile/README.md")
    readme_path.parent.mkdir(exist_ok=True)
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ profile/README.md 已產生（{len(groups)} 個分組）")

# ── 主程式 ─────────────────────────────────────────────────────────────────

def main():
    g = Github(GITHUB_TOKEN)

    print("📡 抓取 org repos...")
    repos = fetch_all_org_repos(g)
    print(f"   找到 {len(repos)} 個 repos")

    with tempfile.TemporaryDirectory() as tmp_dir:
        print("📥 Clone p028...")
        p028_path = clone_p028(tmp_dir)
        notes_dir = p028_path / "03-系統文檔"

        print("🗂️  建立大專案名稱對照表...")
        project_map = build_project_map(notes_dir)
        print(f"   找到 {len(project_map)} 個大專案")

        print("📝 產生 org README...")
        groups = group_by_prefix(repos)
        generate_org_readme(groups, project_map, notes_dir)

        print("🔄 更新 p028 系統文檔...")
        update_p028_notes(repos, p028_path)
        print("✅ 完成")


if __name__ == "__main__":
    main()
