# rasrss

依 RSS 訂閱定期取得最新 MP3，以 **AI Studio（Gemini）** 產生日文逐字稿（完整、一字不漏、不摘要），並顯示於網頁介面與同步至 GitHub Pages。  
支援逐字稿內 **點擊日文詞顯示假名**、**每篇原始音檔 MP3 播放器（倒退／前進 10 秒）**，以及選用 **rasword 單字庫** 一鍵新增單字。

---

## 功能

- **RSS 訂閱**：輸入含 MP3 的 RSS 連結，選擇產生逐字稿週期（每小時、每 6 小時、每日、每週）。
- **自動轉錄**：系統定期從 RSS 取得最新一則 MP3，下載後上傳至 Gemini，產生日文逐字稿並寫入本機資料庫。
- **網頁介面**（<http://127.0.0.1:5001>）：
  - AI API 設定：選擇 **AI Studio（Gemini）** 或 **OpenRouter**，在頁面儲存 API Key（存於本機 SQLite，產生日文逐字稿需 **Gemini**）。
  - 新增／管理 RSS 訂閱，可對任一訂閱「立即執行」手動觸發一次轉錄。
  - 逐字稿列表：篩選訂閱來源、點「查看完整逐字稿」看全文。
  - **逐字稿詳情**：
    - **MP3 播放器**：播放該篇原始音檔，支援「倒退 10 秒」「播放／暫停」「前進 10 秒」與時間顯示。
    - **點擊日文詞**：顯示振假名（平假名）小視窗；再點小視窗可選擇是否將該詞新增至 **rasword** 單字庫（需本機啟動 rasword 服務）。
- **GitHub 連動**：新逐字稿會寫入 `docs/transcripts/*.md` 並更新 `docs/transcripts/index.html`，自動 commit 後 push 到 `origin`（可搭配 GitHub Pages 以 `main` 分支的 `/docs` 公開）。

---

## 環境需求

- Python 3.9+
- **Gemini API Key**（AI Studio）：在網頁「AI API 設定」中輸入並儲存，用於產生日文逐字稿。取得：<https://aistudio.google.com/apikey>
- （選用）**rasword**：若要在逐字稿中一鍵新增單字，需在本機或可連線處執行 [rasword](https://github.com/kapazvuciarwin-art/rasword)，預設為 `http://127.0.0.1:5000`，可設環境變數 `RASWORD_BASE_URL` 覆蓋。

---

## 安裝與執行

```bash
cd rasrss
pip install -r requirements.txt
# 或：python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
```

啟動：

```bash
python app.py
# 或：./run.sh
```

瀏覽器開啟 **http://127.0.0.1:5001**（本機）或 **http://\<此機 IP\>:5001**（同網段其他裝置）。

---

## 設定說明

1. **AI API（必備）**  
   在網頁「AI API 設定」選擇 **AI Studio（Gemini）**，輸入 Gemini API Key 後按「儲存 API 設定」。產生日文逐字稿僅使用 Gemini；OpenRouter 可用於「測試連線」。

2. **GitHub 連動（選用）**  
   - 專案需為 git repo 且已設定 `origin` 遠端。  
   - 每次產生新逐字稿會寫入 `docs/transcripts/*.md` 並更新目錄頁，自動 commit 後 push 到 `origin`。  
   - 若要以 GitHub Pages 公開：Repo **Settings → Pages**，Source 選「Deploy from a branch」→ Branch 選 `main`、Folder 選 `/docs`。  
   - 詳細步驟見：**[docs/GITHUB_PAGES_設定教學.md](docs/GITHUB_PAGES_設定教學.md)**。

3. **rasword 單字庫（選用）**  
   - 預設連線 `http://127.0.0.1:5000`，可設環境變數 `RASWORD_BASE_URL` 指向其他網址。  
   - 在逐字稿詳情中點擊日文詞 → 出現假名小視窗 → 再點小視窗可選 y/n 新增該詞至 rasword（來源標記為「逐字稿輸入」）。

---

## 使用方式

1. 開啟 <http://127.0.0.1:5001>，在「AI API 設定」儲存 **Gemini API Key**。
2. 在「新增 RSS 訂閱」輸入 RSS 連結、選擇週期，按「新增訂閱」。
3. 在「我的 RSS 訂閱」可對任一訂閱按「立即執行」手動觸發一次轉錄。
4. 在「逐字稿列表」點「查看完整逐字稿」進入詳情：
   - 使用 **倒退 10 秒 / 播放 / 前進 10 秒** 聆聽原始 MP3。
   - 點擊逐字稿中的日文詞可看假名；再點小視窗可選擇是否新增至 rasword。
5. 逐字稿會同步寫入 `docs/transcripts/` 並 push 到 GitHub；若已啟用 GitHub Pages，可從 Pages 網址查看。

---

## 專案結構

| 項目 | 說明 |
|------|------|
| `app.py` | Flask 後端：RSS 解析、排程、下載 MP3 並上傳 Gemini 轉錄、設定與 API、rasword 整合、寫入 `docs/transcripts` 並 git push |
| `templates/index.html` | 單頁介面：AI 設定、訂閱管理、逐字稿列表與詳情（含 MP3 播放器、假名點擊、rasword 新增） |
| `docs/` | GitHub Pages 來源目錄；`docs/transcripts/` 存放逐字稿 Markdown 與目錄頁 `index.html` |
| `run.sh` | 啟動腳本（可選用 venv） |
| `rasrss.db` | SQLite：訂閱、逐字稿、API 設定（key 存於 DB，不寫入 .env） |

---

## 與 GitHub 連動

- 若專案為 git 且設有 `origin`，每次產生新逐字稿會自動：
  1. 寫入 `docs/transcripts/<檔名>.md`
  2. 更新 `docs/transcripts/index.html` 目錄頁
  3. `git add`、`git commit`、`git push` 到 `origin`
- 手動將程式變更推送到 GitHub：  
  `git add .` → `git commit -m "說明"` → `git push origin <分支名>`（例如 `main` 或 `feat/rasword-word-add-integration`）。

啟用 GitHub Pages（Source: main / docs）後，可從 `https://<username>.github.io/rasrss/` 看到首頁，並從 `docs/transcripts/` 進入各逐字稿。
