# GitHub Pages 設定教學（rasrss）

讓你的 rasrss 逐字稿在網路上公開，網址會是：  
**https://kapazvuciarwin-art.github.io/rasrss/**

---

## 一、在 GitHub 網站上開啟設定

1. 用瀏覽器打開：  
   **https://github.com/kapazvuciarwin-art/rasrss**
2. 點上方 **Settings**（設定）。
3. 左側選單往下捲，點 **Pages**（在「Code and automation」區塊裡）。

---

## 二、設定來源為 main 分支的 /docs

1. 在 **Build and deployment** 區塊：
   - **Source** 選：**Deploy from a branch**（從分支部署）。
2. **Branch** 下拉選單：
   - 選 **main**。
   - 右邊 **Folder** 選 **/docs**。
3. 按 **Save**（儲存）。

---

## 三、等幾分鐘後檢查

- GitHub 會自動用 `main` 分支裡的 **docs** 資料夾建站。
- 約 1～3 分鐘後，在 Pages 設定頁最上方會出現綠色提示，例如：  
  **Your site is live at https://kapazvuciarwin-art.github.io/rasrss/**
- 用瀏覽器打開上述網址，應會看到 rasrss 的 index 頁面；點「查看 transcripts 目錄」可看逐字稿列表。

---

## 四、之後如何更新內容

- 程式會把新逐字稿寫進 **docs/transcripts/**，並自動 commit + push 到 GitHub。
- 你一 push 到 `main`，GitHub 會自動重新部署，幾分鐘後網站就會更新，**不用再手動設定**。

---

## 常見問題

| 問題 | 說明 |
|------|------|
| 網址 404 | 等 2～3 分鐘再試，或確認 Branch 選 main、Folder 選 /docs。 |
| 改設定後沒變 | 確認已按 Save；可到 **Actions** 分頁看是否有 Pages 部署紀錄。 |
| 想用自訂網域 | 在 Pages 頁的 **Custom domain** 填你的網域，並依說明設定 DNS。 |

完成以上步驟後，你的 GitHub Page 就設定好了。
