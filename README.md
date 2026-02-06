# rasrss

依 RSS 訂閱定期抓取最新 MP3，以 AI（OpenAI Whisper）產生日文逐字稿（完整、一字不漏、不摘要），並顯示於網頁介面與同步至 GitHub Pages。

## 功能

- 輸入 RSS 連結（需包含 MP3 的節目）
- 選擇產生逐字稿週期：每小時、每 6 小時、每日、每週
- 系統定期抓取該 RSS 最新一則 MP3，呼叫 Whisper API 產生日文逐字稿
- 逐字稿顯示於本機網頁介面，並寫入 `docs/transcripts/` 後 push 到 GitHub（可搭配 GitHub Pages 公開）

## 環境需求

- Python 3.10+
- OpenAI API Key（用於 Whisper 語音轉文字）

## 安裝

```bash
cd rasrss
pip install -r requirements.txt
cp .env.example .env
# 編輯 .env，填入 OPENAI_API_KEY
```

## 設定

1. **OpenAI API Key**  
   在 `.env` 中設定 `OPENAI_API_KEY`。取得方式：<https://platform.openai.com/api-keys>  
   Whisper 用於將 MP3 轉成日文逐字稿（一字不漏、不摘要）。

2. **GitHub 連動（選用）**  
   - 專案需為 git repo 且已設定 `origin` 遠端。  
   - 每次產生新逐字稿會寫入 `docs/transcripts/*.md` 並自動 commit + push。  
   - 若要在 GitHub 上公開：到 repo 的 Settings → Pages → Source 選「Deploy from a branch」→ Branch 選 `main`，Folder 選 `/docs`，即可用 GitHub Pages 顯示 `docs/` 內容（含逐字稿）。

## 使用方式

```bash
python app.py
```

瀏覽 <http://0.0.0.0:5001>：

1. 在「新增 RSS 訂閱」輸入 RSS 連結並選擇週期，按「新增訂閱」。
2. 在「我的 RSS 訂閱」可對任一訂閱按「立即執行」手動觸發一次抓取與轉錄。
3. 在「逐字稿列表」查看所有逐字稿，點「查看完整逐字稿」可看全文。
4. 逐字稿會同步寫入 `docs/transcripts/` 並 push 到 GitHub；若已啟用 GitHub Pages（來源：main / docs），可從 Pages 網址查看。

## 專案結構

- `app.py`：Flask 後端、排程、RSS 解析、MP3 下載、Whisper 轉錄、Git push
- `templates/index.html`：使用者介面（輸入 RSS、選週期、顯示逐字稿）
- `docs/`：GitHub Pages 來源目錄；`docs/transcripts/` 存放逐字稿 Markdown
- `rasrss.db`：SQLite 資料庫（訂閱與逐字稿紀錄，本機使用）

## 與 GitHub 連動

本專案已可與 GitHub 連動：

- 若專案目錄為 git 且設有 `origin`，每次產生新逐字稿會自動：
  1. 寫入 `docs/transcripts/<檔名>.md`
  2. `git add`、`git commit`、`git push` 到 `origin`

啟用 GitHub Pages 後，訪客可從 `https://<username>.github.io/<repo>/` 看到 `docs/index.html`，並從 `docs/transcripts/` 進入各逐字稿。
