import os
import time
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
import feedparser
import requests
import re

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FEED_URL = "https://coinn.pl/feed/"
SEEN_FILE = Path("seen.json")
POLL_INTERVAL_SECONDS = 60

logging.basicConfig(level=logging.INFO)

def load_seen():
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except:
            return set()
    return set()

def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(list(seen)))

def escape_html(s):
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )

def format_entry(entry):
    title = entry.get("title")
    link = entry.get("link")
    summary = entry.get("summary", "")

    plain = re.sub("<[^<]+?>", "", summary).strip()
    if len(plain) > 300:
        plain = plain[:297] + "..."

    return f"<b>{escape_html(title)}</b>\n{link}\n\n{escape_html(plain)}"

def send_telegram_message(text, chat_id=TELEGRAM_CHAT_ID):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    })

def get_entries_last_7_days():
    feed = feedparser.parse(FEED_URL)
    week = datetime.utcnow() - timedelta(days=7)
    results = []

    for e in feed.entries:
        pub = e.get("published_parsed")
        if not pub:
            continue
        dt = datetime(*pub[:6])
        if dt >= week:
            results.append(e)
    return results

if __name__ == "__main__":
    seen = load_seen()
    logging.info(f"Started worker with {len(seen)} entries in memory")

    while True:
        if os.getenv("AUTO_PUBLISH", "1") == "1":
            feed = feedparser.parse(FEED_URL)
            for entry in reversed(feed.entries):
                eid = entry.get("id") or entry.get("link")
                if eid not in seen:
                    send_telegram_message(format_entry(entry))
                    seen.add(eid)
                    save_seen(seen)

        time.sleep(POLL_INTERVAL_SECONDS)
