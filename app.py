import os
import time
import json
import logging
import traceback
from pathlib import Path
from datetime import datetime, timedelta
import feedparser
import requests
from flask import Flask, request

# Konfiguracja z ENV
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FEED_URL = "https://coinn.pl/feed/"
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
SEEN_FILE = Path("seen.json")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)

auto_publish_enabled = True  # można wyłączyć komendą


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


def send_telegram_message(text, chat_id=None):
    if chat_id is None:
        chat_id = TELEGRAM_CHAT_ID

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        logging.error(f"Telegram API error: {e}")


def get_entries_last_7_days():
    feed = feedparser.parse(FEED_URL)
    week_ago = datetime.utcnow() - timedelta(days=7)
    results = []

    for entry in feed.entries:
        published = entry.get("published_parsed")
        if not published:
            continue

        dt = datetime(*published[:6])
        if dt >= week_ago:
            results.append(entry)

    return results


@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def telegram_webhook():
    global auto_publish_enabled

    data = request.json
    if not data:
        return "no json", 200

    message = data.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")

    if text == "/news":
        send_telegram_message(
            "<b>Dostępne opcje:</b>\n"
            "/last7 — pokaż artykuły z ostatnich 7 dni\n"
            "/auto_on — włącz auto-publikację\n"
            "/auto_off — wyłącz auto-publikację",
            chat_id
        )

    elif text == "/last7":
        entries = get_entries_last_7_days()
        if not entries:
            send_telegram_message("Brak artykułów z ostatnich 7 dni", chat_id)
        else:
            for e in entries:
                send_telegram_message(format_entry(e), chat_id)

    elif text == "/auto_on":
        auto_publish_enabled = True
        send_telegram_message("Auto-publikacja włączona ✔️", chat_id)

    elif text == "/auto_off":
        auto_publish_enabled = False
        send_telegram_message("Auto-publikacja wyłączona ❌", chat_id)

    return "ok", 200


def main_loop():
    seen = load_seen()
    logging.info(f"Wczytano {len(seen)} znanych wpisów.")

    while True:
        try:
            if auto_publish_enabled:
                feed = feedparser.parse(FEED_URL)
                entries = feed.entries

                for entry in reversed(entries):
                    eid = entry.get("id") or entry.get("link")

                    if eid not in seen:
                        msg = format_entry(entry)
                        send_telegram_message(msg)
                        seen.add(eid)
                        save_seen(seen)

        except Exception:
            logging.error(traceback.format_exc())

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    # start webhook + worker
    import threading
    t = threading.Thread(target=main_loop)
    t.daemon = True
    t.start()

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 3000)))
