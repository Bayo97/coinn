import os
import time
import json
import logging
import traceback
from pathlib import Path
from datetime import datetime
import feedparser
import requests

# Konfiguracja z ENV
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # np. -1001234567890
FEED_URL = "https://coinn.pl/feed/"
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
SEEN_FILE = Path("seen.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_seen():
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen(seen_set):
    SEEN_FILE.write_text(
        json.dumps(list(seen_set), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


def format_entry(entry):
    title = entry.get("title", "Bez tytułu")
    link = entry.get("link", "")
    summary = entry.get("summary", "")

    import re
    plain = re.sub("<[^<]+?>", "", summary).strip()

    if len(plain) > 300:
        plain = plain[:297].rsplit(" ", 1)[0] + "..."

    msg = f"<b>{escape_html(title)}</b>\n{link}"
    if plain:
        msg += f"\n\n{escape_html(plain)}"
    return msg


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        logging.error(f"Telegram API error: {e}")


def main_loop():
    seen = load_seen()
    logging.info(f"Wczytano {len(seen)} znanych wpisów.")

    while True:
        try:
            feed = feedparser.parse(FEED_URL)
            entries = feed.entries

            for entry in reversed(entries):
                eid = entry.get("id") or entry.get("link")

                if eid not in seen:
                    logging.info(f"Nowy artykuł: {entry.get('title')}")
                    msg = format_entry(entry)
                    send_telegram_message(msg)
                    seen.add(eid)
                    save_seen(seen)

        except Exception:
            logging.error(traceback.format_exc())

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.info("Bot Coinn Telegram Bot startuje...")
    main_loop()
