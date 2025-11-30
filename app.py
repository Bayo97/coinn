from flask import Flask, request
import os
import feedparser
from datetime import datetime, timedelta
from worker import format_entry, send_telegram_message, get_entries_last_7_days

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")

app = Flask(__name__)

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    data = request.json

    if not data or "message" not in data:
        return "ok", 200

    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text == "/news":
        send_telegram_message(
            "<b>Dostępne opcje:</b>\n"
            "/last7 — pokaż artykuły z ostatnich 7 dni\n"
            "/auto_on — włącz auto publikowanie\n"
            "/auto_off — wyłącz auto publikowanie",
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
        os.environ["AUTO_PUBLISH"] = "1"
        send_telegram_message("Auto-publikacja włączona ✔️", chat_id)

    elif text == "/auto_off":
        os.environ["AUTO_PUBLISH"] = "0"
        send_telegram_message("Auto-publikacja wyłączona ❌", chat_id)

    return "ok", 200


@app.route("/")
def home():
    return "Telegram Bot Running", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
