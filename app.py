"""rasrss - RSS 訂閱 → 定期將最新 MP3 連結傳給 AI API → 日文逐字稿 → 介面與 GitHub Pages"""

import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import feedparser
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from git import Repo

load_dotenv()

app = Flask(__name__)
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rasrss.db")
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
# GitHub Pages 輸出路徑：專案內 docs/，可設 GitHub Pages 來源為 main branch /docs
PAGES_DIR = os.path.join(REPO_ROOT, "docs", "transcripts")

# 排程選項（分鐘）
SCHEDULE_OPTIONS = [
    ("hourly", 60, "每小時"),
    ("6hours", 360, "每 6 小時"),
    ("daily", 1440, "每日"),
    ("weekly", 10080, "每週"),
]

# 逐字稿使用 AI Studio Gemini（下載 MP3 後上傳給 Gemini 轉錄）
# AI Studio Gemini：優先 3.0 Flash 相關，再 2.5、2.0
GEMINI_MODEL_PRIORITY = [
    "gemini-3.0-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

# OpenRouter：免費模型中自動選最好的（依序嘗試）
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_FREE_MODELS = [
    "google/gemini-2.0-flash-001:free",
    "deepseek/deepseek-r1:free",
    "deepseek/deepseek-chat:free",
    "qwen/qwen3-14b:free",
    "qwen/qwen3-32b:free",
    "meta-llama/llama-4-scout:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "microsoft/phi-3-mini-128k-instruct:free",
]


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rss_url TEXT NOT NULL UNIQUE,
            title TEXT,
            schedule_minutes INTEGER NOT NULL DEFAULT 1440,
            last_run_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL
        )
    """)
    # 升級：若舊表沒有 last_error 則新增
    try:
        cursor = conn.execute("PRAGMA table_info(feeds)")
        cols = [r[1] for r in cursor.fetchall()]
        if "last_error" not in cols:
            conn.execute("ALTER TABLE feeds ADD COLUMN last_error TEXT")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id INTEGER NOT NULL,
            episode_title TEXT,
            episode_url TEXT,
            mp3_url TEXT NOT NULL,
            transcript_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (feed_id) REFERENCES feeds(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episode_done (
            feed_id INTEGER NOT NULL,
            mp3_url TEXT NOT NULL,
            PRIMARY KEY (feed_id, mp3_url),
            FOREIGN KEY (feed_id) REFERENCES feeds(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)
    """)
    conn.commit()
    conn.close()
    Path(PAGES_DIR).mkdir(parents=True, exist_ok=True)


def get_latest_mp3_from_rss(rss_url):
    """從 RSS 取得最新一則的 MP3 連結。"""
    resp = requests.get(rss_url, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        return None, None, None
    entry = feed.entries[0]
    title = entry.get("title", "")
    link = entry.get("link", "")
    mp3_url = None
    if hasattr(entry, "enclosures"):
        for enc in entry.enclosures:
            href = getattr(enc, "href", "") or enc.get("href", "")
            if "audio" in enc.get("type", "") or "mpeg" in enc.get("type", "") or href.lower().endswith(".mp3"):
                mp3_url = href
                break
    if not mp3_url and entry.get("links"):
        for link_obj in entry.links:
            t = (link_obj.get("type") or "").lower()
            h = link_obj.get("href", "")
            if "audio" in t or "mpeg" in t or h.lower().endswith(".mp3"):
                mp3_url = h
                break
    return title, link, mp3_url


def already_processed(feed_id, mp3_url):
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM episode_done WHERE feed_id = ? AND mp3_url = ?",
        (feed_id, mp3_url),
    ).fetchone()
    conn.close()
    return row is not None


def mark_processed(feed_id, mp3_url):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO episode_done (feed_id, mp3_url) VALUES (?, ?)",
        (feed_id, mp3_url),
    )
    conn.commit()
    conn.close()


def _get_setting(key):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def _set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value or ""))
    conn.commit()
    conn.close()


def call_gemini(api_key, prompt):
    """AI Studio Gemini：優先 3.0 Flash 相關，再 2.5、2.0。"""
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("請安裝：pip install google-generativeai")
    genai.configure(api_key=api_key)
    last_err = None
    for model_name in GEMINI_MODEL_PRIORITY:
        try:
            model = genai.GenerativeModel(model_name)
            r = model.generate_content(prompt)
            return (r.text or "").strip(), model_name
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Gemini 無可用模型：{last_err}")


def call_openrouter(api_key, prompt):
    """OpenRouter：自動選免費中最好的模型（依序嘗試）。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5001",
        "X-Title": "rasrss",
    }
    last_err = None
    for model in OPENROUTER_FREE_MODELS:
        try:
            r = requests.post(
                OPENROUTER_API_URL,
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
                timeout=60,
            )
            if r.status_code == 200:
                data = r.json()
                if "choices" in data and data["choices"]:
                    text = data["choices"][0].get("message", {}).get("content", "")
                    return (text or "").strip(), model
            last_err = r.text or str(r.status_code)
        except Exception as e:
            last_err = str(e)
            continue
    raise RuntimeError(f"OpenRouter 無可用模型：{last_err}")


def _get_gemini_key():
    """Gemini Key：優先 .env GEMINI_API_KEY，其次介面儲存的設定。"""
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        key = (_get_setting("gemini_api_key") or "").strip()
    return key or None


def _download_mp3(mp3_url):
    """下載 MP3 到暫存檔，回傳路徑。呼叫方須負責刪除。"""
    r = requests.get(mp3_url, timeout=120, stream=True)
    r.raise_for_status()
    tmpdir = os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp"))
    path = os.path.join(tmpdir, f"rasrss_{os.getpid()}_{time.time():.0f}.mp3")
    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    return path


def transcribe_japanese_with_gemini(mp3_url):
    """用 AI Studio Gemini 產生日文逐字稿：下載 MP3 → 上傳 Gemini → 完整一字不漏、不摘要。"""
    key = _get_gemini_key()
    if not key:
        raise ValueError("請在「AI API 設定」中選擇 AI Studio（Gemini）並輸入、儲存 Gemini API Key")
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("請安裝：pip install google-generativeai")
    genai.configure(api_key=key)
    tmp_path = None
    try:
        tmp_path = _download_mp3(mp3_url)
        # 上傳音訊給 Gemini
        audio_file = genai.upload_file(tmp_path, mime_type="audio/mpeg")
        # 輪詢直到處理完成
        for _ in range(60):
            if audio_file.state.name == "ACTIVE":
                break
            if audio_file.state.name == "FAILED":
                raise RuntimeError(audio_file.state.name or "上傳失敗")
            time.sleep(2)
        prompt = "此為日文音訊。請產出完整逐字稿，一字不漏、不摘要，只輸出日文文字，不要其他說明。"
        last_err = None
        for model_name in GEMINI_MODEL_PRIORITY:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content([audio_file, prompt])
                if response.text:
                    return (response.text or "").strip()
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"Gemini 無可用模型：{last_err}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def safe_filename(s):
    s = re.sub(r"[^\w\s\-\.]", "", s)
    s = re.sub(r"\s+", "_", s)
    return (s or "episode")[:120]


def push_transcript_to_github(title, transcript_text, episode_slug):
    """將逐字稿寫入 docs/transcripts 並 push 到 origin（若為同一 repo）。"""
    Path(PAGES_DIR).mkdir(parents=True, exist_ok=True)
    filename = f"{episode_slug}.md"
    filepath = os.path.join(PAGES_DIR, filename)
    rel_path = os.path.relpath(filepath, REPO_ROOT)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(transcript_text)
    try:
        repo = Repo(REPO_ROOT)
        if repo.bare or not repo.remotes:
            return False, "本地非 git 或無遠端"
        repo.index.add([rel_path])
        repo.index.commit(f"transcript: {filename}")
        origin = repo.remotes.origin
        origin.push()
        return True, None
    except Exception as e:
        return False, str(e)


def run_feed_job(feed_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, rss_url, title, schedule_minutes FROM feeds WHERE id = ?",
        (feed_id,),
    ).fetchone()
    conn.close()
    if not row:
        return
    rss_url = row["rss_url"]
    title, link, mp3_url = get_latest_mp3_from_rss(rss_url)
    if not mp3_url:
        return
    if already_processed(feed_id, mp3_url):
        return
    try:
        transcript_text = transcribe_japanese_with_gemini(mp3_url)
    except Exception as e:
        err_msg = str(e)
        print(f"[rasrss] feed {feed_id} 轉錄失敗: {err_msg}")
        conn = get_db()
        conn.execute("UPDATE feeds SET last_error = ? WHERE id = ?", (err_msg, feed_id))
        conn.commit()
        conn.close()
        return
    # 成功則清除錯誤
    conn = get_db()
    conn.execute("UPDATE feeds SET last_error = NULL WHERE id = ?", (feed_id,))
    conn.commit()
    conn.close()
    now = datetime.utcnow().isoformat() + "Z"
    conn = get_db()
    conn.execute(
        """INSERT INTO transcripts (feed_id, episode_title, episode_url, mp3_url, transcript_text, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (feed_id, title or "", link or "", mp3_url, transcript_text, now),
    )
    conn.commit()
    conn.close()
    mark_processed(feed_id, mp3_url)
    # 更新 last_run_at
    conn = get_db()
    conn.execute("UPDATE feeds SET last_run_at = ? WHERE id = ?", (now, feed_id))
    conn.commit()
    conn.close()
    # 寫入 GitHub Pages
    slug = safe_filename(title or "episode") + "_" + now.replace(":", "-")[:19]
    ok, err = push_transcript_to_github(title or "Episode", transcript_text, slug)
    if not ok:
        print(f"[rasrss] GitHub push 失敗: {err}")


def scheduler_tick():
    conn = get_db()
    feeds = conn.execute(
        "SELECT id, schedule_minutes, last_run_at FROM feeds"
    ).fetchall()
    conn.close()
    now = datetime.utcnow()
    for row in feeds:
        feed_id = row["id"]
        interval_min = row["schedule_minutes"]
        last = row["last_run_at"]
        run = False
        if not last:
            run = True
        else:
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                delta_min = (now - last_dt).total_seconds() / 60
                if delta_min >= interval_min:
                    run = True
            except Exception:
                run = True
        if run:
            threading.Thread(target=run_feed_job, args=(feed_id,), daemon=True).start()


# ------------------------- 路由 -------------------------


@app.route("/")
def index():
    return render_template("index.html", schedule_options=SCHEDULE_OPTIONS)


@app.route("/api/feeds", methods=["GET"])
def list_feeds():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, rss_url, title, schedule_minutes, last_run_at, last_error, created_at FROM feeds ORDER BY id DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT id, rss_url, title, schedule_minutes, last_run_at, created_at FROM feeds ORDER BY id DESC"
        ).fetchall()
    conn.close()
    out = [dict(r) for r in rows]
    for r in out:
        if "last_error" not in r:
            r["last_error"] = None
    return jsonify(out)


@app.route("/api/feeds", methods=["POST"])
def add_feed():
    data = request.get_json() or {}
    rss_url = (data.get("rss_url") or "").strip()
    schedule = data.get("schedule", "daily")
    if not rss_url:
        return jsonify({"success": False, "error": "請輸入 RSS 連結"}), 400
    schedule_minutes = 1440
    for key, minutes, _ in SCHEDULE_OPTIONS:
        if key == schedule:
            schedule_minutes = minutes
            break
    try:
        title, _, _ = get_latest_mp3_from_rss(rss_url)
    except Exception as e:
        return jsonify({"success": False, "error": f"無法讀取 RSS：{e}"}), 400
    now = datetime.utcnow().isoformat() + "Z"
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO feeds (rss_url, title, schedule_minutes, created_at) VALUES (?, ?, ?, ?)",
            (rss_url, title or "", schedule_minutes, now),
        )
        conn.commit()
        feed_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"success": False, "error": "此 RSS 已存在"}), 400
    conn.close()
    return jsonify({"success": True, "feed_id": feed_id})


@app.route("/api/feeds/<int:feed_id>", methods=["DELETE"])
def delete_feed(feed_id):
    conn = get_db()
    conn.execute("DELETE FROM episode_done WHERE feed_id = ?", (feed_id,))
    conn.execute("DELETE FROM transcripts WHERE feed_id = ?", (feed_id,))
    conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/transcripts", methods=["GET"])
def list_transcripts():
    feed_id = request.args.get("feed_id", type=int)
    conn = get_db()
    if feed_id:
        rows = conn.execute(
            "SELECT id, feed_id, episode_title, episode_url, mp3_url, transcript_text, created_at FROM transcripts WHERE feed_id = ? ORDER BY created_at DESC",
            (feed_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, feed_id, episode_title, episode_url, mp3_url, transcript_text, created_at FROM transcripts ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/transcripts/<int:tid>", methods=["GET"])
def get_transcript(tid):
    conn = get_db()
    row = conn.execute(
        "SELECT id, feed_id, episode_title, episode_url, transcript_text, created_at FROM transcripts WHERE id = ?",
        (tid,),
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "找不到逐字稿"}), 404
    return jsonify(dict(row))


@app.route("/api/run-now/<int:feed_id>", methods=["POST"])
def run_now(feed_id):
    threading.Thread(target=run_feed_job, args=(feed_id,), daemon=True).start()
    return jsonify({"success": True, "message": "已排入執行"})


@app.route("/api/settings", methods=["GET"])
def get_settings():
    """取得 API 設定（僅回傳 provider 與是否已設定 key，不回傳明文 key）。"""
    provider = _get_setting("api_provider") or "gemini"
    has_gemini = bool(_get_setting("gemini_api_key"))
    has_openrouter = bool(_get_setting("openrouter_api_key"))
    return jsonify({
        "api_provider": provider,
        "has_gemini_key": has_gemini,
        "has_openrouter_key": has_openrouter,
    })


@app.route("/api/settings", methods=["POST"])
def save_settings():
    """儲存 API 設定（provider 與 key）；key 留空則不覆蓋既有值。"""
    data = request.get_json() or {}
    provider = (data.get("api_provider") or "gemini").strip().lower()
    if provider not in ("gemini", "openrouter"):
        provider = "gemini"
    _set_setting("api_provider", provider)
    gemini_key = (data.get("gemini_api_key") or "").strip()
    openrouter_key = (data.get("openrouter_api_key") or "").strip()
    if gemini_key:
        _set_setting("gemini_api_key", gemini_key)
    if openrouter_key:
        _set_setting("openrouter_api_key", openrouter_key)
    return jsonify({"success": True, "api_provider": provider})


@app.route("/api/ai-test", methods=["POST"])
def ai_test():
    """測試 AI API 連線（傳入的 key 優先，否則用已儲存的 key）。"""
    data = request.get_json() or {}
    provider = (data.get("api_provider") or "gemini").strip().lower()
    if provider not in ("gemini", "openrouter"):
        return jsonify({"success": False, "error": "請選擇 Gemini 或 OpenRouter"}), 400
    if provider == "gemini":
        key = (data.get("gemini_api_key") or "").strip() or _get_setting("gemini_api_key")
        if not key:
            return jsonify({"success": False, "error": "請輸入或先儲存 Gemini API Key"}), 400
        try:
            text, model = call_gemini(key, "回覆：OK")
            return jsonify({"success": True, "model": model, "message": "連線成功"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400
    else:
        key = (data.get("openrouter_api_key") or "").strip() or _get_setting("openrouter_api_key")
        if not key:
            return jsonify({"success": False, "error": "請輸入或先儲存 OpenRouter API Key"}), 400
        try:
            text, model = call_openrouter(key, "回覆：OK")
            return jsonify({"success": True, "model": model, "message": "連線成功"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400


def main():
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduler_tick, "interval", minutes=5)
    scheduler.start()
    print("\n請在瀏覽器開啟： http://127.0.0.1:5001")
    print("或從其他裝置：   http://<此機IP>:5001\n")
    try:
        app.run(host="0.0.0.0", port=5001, debug=True)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
