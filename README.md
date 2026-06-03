# east-model-toy-corporation/.github

組織層級的 GitHub 設定與自動化腳本。

## 檔案結構

```
profile/README.md           ← 組織首頁（由 GitHub Actions 自動產生，勿手動編輯）
scripts/sync_org.py         ← 每日同步腳本
.github/workflows/sync.yml  ← GitHub Actions 排程
```

## 設定

在 repo Settings → Secrets → Actions 加入：

| Secret | 說明 |
|--------|------|
| `ORG_SYNC_TOKEN` | GitHub PAT，需要 `repo` + `read:org` 權限 |

## 手動觸發

Actions → Sync Org Navigation → Run workflow
