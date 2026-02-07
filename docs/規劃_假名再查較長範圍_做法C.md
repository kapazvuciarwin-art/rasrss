# 假名「再查較長範圍」功能 — 做法 C 規劃報告

## 一、需求摘要

- **問題**：斷詞偏細時，點「震」會顯示 震(しん)，但文脈上是 震わせて(ふるわせて)。
- **做法 C**：在讀音顯示「震(しん)」**右邊**加一個 **「>」按鈕**，按了才執行「再查較長範圍」，避免與「點一下假名小視窗 → 詢問是否加入 rasword」混淆。
- **不改程式**：本文件僅為規劃，實作時再動程式。

---

## 二、目前讀音取得方式（已查 CODE）

### rasrss / rasporuno 一致

| 項目 | 說明 |
|------|------|
| **後端** | `to_furigana(text: str) -> str`，使用 **pykakasi**（`kakasi().getConverter()`）將整段文字轉成平假名。 |
| **API** | `GET /api/furigana?text=...`，回傳 `{ ok: true, text, reading }`。 |
| **前端** | 點擊文字 → `pickWordFromTextNode(text, offset)` 得到一個詞 `word` → `fetch('/api/furigana?text=' + encodeURIComponent(word))` → 彈窗顯示 `word (reading)`。 |

也就是說：**讀音完全由 pykakasi 對「傳入的那段文字」做轉換**，沒有用外部 API 或字典；傳入「震」就得到「しん」，傳入「震わせて」就得到「ふるわせて」。

---

## 三、點擊時能否拿到字元 index（已查 CODE）

### 結論：**可以**

- 點擊時使用 `caretRangeFromPoint(ev.clientX, ev.clientY)` 得到 `range`。
- `range.startContainer` 為文字所在節點（rasrss 逐字稿為單一 text node），`range.startOffset` 為該節點內的**字元 index**。
- 取得全文：`node.textContent`（該 text node 的整段文字）。
- 因此可從 `startOffset` 往右取子字串：`text.slice(startOffset, startOffset + len)`，len = 2, 3, 4, … 作為「較長範圍」查詢。

rasrss 的 `detailBody` 以 `detailBody.textContent = t.transcript_text` 賦值，整段逐字稿為單一 text node，故上述做法成立。rasporuno 若歌詞區也是單一 text node 或可取得點擊處的 text node 與 offset，同樣可實作。

---

## 四、做法 C 具體規格

### 4.1 UI

- **位置**：假名彈窗第一行，在「震(しん)」**右側**加一個 **「>」按鈕**（例如：`震 (しん) [>]`）。
- **行為**：僅「>」觸發「再查較長範圍」；點彈窗其他區域維持原邏輯（第一次點 → 詢問是否加入 rasword，不與「>」混淆）。
- **樣式**：小按鈕、可 hover，必要時加 title="試試較長範圍"。

### 4.2 再查較長範圍邏輯

1. **觸發**：使用者按「>」。
2. **輸入**：需要「當前點擊位置」的**全文**與**字元 index**。  
   - 第一次點「震」時，前端已用 `caretRangeFromPoint` 得到 `(node, startOffset)` 與 `word`；彈窗顯示時須**一併存下** `contextText = node.textContent`、`contextOffset = range.startOffset`（或等同資訊），供「>」使用。
3. **候選子字串**：從 `contextOffset` 往右取長度 2, 3, 4, …, N（例如 N=10 或遇到句讀/空白即停），得到多個子字串。
4. **查詢**：對每個子字串呼叫現有 `GET /api/furigana?text=...`（即現有 `to_furigana`），取得讀音。
5. **篩選**：與「目前顯示的讀音」相同者不重複顯示；可選：僅顯示「長度 > 目前 word 且讀音不同」的結果。
6. **顯示**：在彈窗內**下方**追加區塊，例如「較長範圍：震わせて(ふるわせて)」；若多筆可列多行，每行可點選（未來若要支援「選此詞加入 rasword」可再擴充）。

### 4.3 與「加入 rasword」的關係

- 「點一下假名小視窗」→ 進入 y/n 詢問是否加入 rasword，**不變**。
- 「>」只負責「再查較長範圍」並顯示結果，不直接改 rasword；若日後要在「較長範圍」的某一行也支援加入 rasword，可再規劃。

---

## 五、實作時需動的檔案與要點

### 5.1 前端（rasrss / rasporuno 的 templates/index.html）

| 項目 | 說明 |
|------|------|
| **儲存點擊脈絡** | 在 `showFuriganaAt(x, y, word)` 被呼叫時，除了 `currentWord`，一併存下 `currentContextText`、`currentContextOffset`（來自當時的 range.startContainer.textContent 與 range.startOffset）。需在「點擊逐字稿」的 handler 裡把 range / node / offset 傳給 showFuriganaAt 或存到共用變數。 |
| **彈窗 HTML** | 第一次顯示讀音時，改為：`震 (しん) <button type="button" class="furigana-extend-btn" title="試試較長範圍">&gt;</button>`，並避免「>」的 click 冒泡觸發「詢問加入 rasword」。 |
| **「>」的 click** | 讀取 `currentContextText`、`currentContextOffset`，從 offset 往右取 2~N 字，依序呼叫 `/api/furigana?text=...`，篩選與當前讀音不同之結果，在彈窗下方插入「較長範圍：xxx(讀音)」等行。 |
| **樣式** | `.furigana-extend-btn` 小按鈕、右側排列、hover 效果。 |

### 5.2 後端

- **無須改 API**：仍使用 `GET /api/furigana?text=...` 與現有 `to_furigana(text)`。較長範圍只是「多次呼叫同一 API、傳不同子字串」。

### 5.3 跨專案

- rasrss 與 rasporuno 的假名彈窗邏輯類似，需在**兩邊**都做：  
  - 儲存 contextText / contextOffset；  
  - 彈窗加「>」按鈕；  
  - 「>」的 handler 做較長範圍查詢與顯示。

---

## 六、流程整理（使用者觀點）

1. 點逐字稿「震」→ 彈窗顯示「震 (しん) [>]」。
2. 若滿意「しん」、要加入 rasword → 點彈窗（非「>」）→ 出現 y/n。
3. 若覺得「しん」不對、想試較長範圍 → 點「>」→ 彈窗下方出現「較長範圍：震わせて(ふるわせて)」等。
4. 之後仍可點彈窗其他區域進入 y/n（例如要加「震わせて」再擴充）。

---

## 七、小結

- **讀音來源**：兩專案皆為 **pykakasi**，透過現有 `GET /api/furigana?text=...`。
- **字元 index**：**可取得**，來自 `range.startContainer` + `range.startOffset`，並可從 `node.textContent` 取全文做 slice。
- **做法 C**：在「震(しん)」右邊加「>」按鈕，按了以後用「同一 API、多段較長子字串」再查，結果顯示在彈窗下方，與「點一下加入 rasword」分離，避免混淆。
- 實作時僅需改前端（兩專案 templates），後端 API 不變；本文件為規劃，先不改程式。
