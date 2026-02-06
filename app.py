"""rasrss - RSS 訂閱 → 定期抓取最新 MP3 → AI 日文逐字稿 → 介面與 GitHub Pages"""

import os
import re
import sqlite3
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import feedparser
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import OpenAI
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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


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
            created_at TEXT NOT NULL
        )
    """)
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


def download_mp3(mp3_url):
    r = requests.get(mp3_url, timeout=120, stream=True)
    r.raise_for_status()
    ext = ".mp3"
    fd, path = tempfile.mkstemp(suffix=ext)
    with os.fdopen(fd, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    return path


def transcribe_japanese_whisper(file_path):
    """使用 OpenAI Whisper 產生日文逐字稿，要求完整一字不漏、不摘要。"""
    client = OpenAI(api_key=OPENAI_API_KEY)
    with open(file_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="ja",
            response_format="text",
        )
    return (transcript or "").strip()


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
    tmp_path = None
    try:
        tmp_path = download_mp3(mp3_url)
        transcript_text = transcribe_japanese_whisper(tmp_path)
    except Exception as e:
        print(f"[rasrss] feed {feed_id} 轉錄失敗: {e}")
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
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
    rows = conn.execute(
        "SELECT id, rss_url, title, schedule_minutes, last_run_at, created_at FROM feeds ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


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


def main():
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduler_tick, "interval", minutes=5)
    scheduler.start()
    try:
        app.run(host="0.0.0.0", port=5001, debug=True)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
