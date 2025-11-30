import os
import time
import json
import logging
import traceback
import re
import threading
from pathlib import Path
from datetime import datetime, timedelta
import feedparser
import requests
from flask import Flask, request

# --- KONFIGURACJA ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FEED_URL = "https://coinn.pl/feed/"
# Jak często bot ma sprawdzać nowe wpisy (domyślnie co 60 sekund)
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
# Plik, w którym bot zapamiętuje opublikowane artykuły
SEEN_FILE = Path("seen.json") 
# Sekret do webhooka, używany do komend bota, np. /webhook/secret123
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret123") 

# Weryfikacja krytycznych zmiennych
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
    print("Brak TELEGRAM_BOT_TOKEN lub TELEGRAM_CHAT_ID w zmiennych środowiskowych. Zamykanie.")
    raise SystemExit(1)

# Ustawienia logowania
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)
# Użycie blokady do bezpiecznego dostępu do pliku seen.json oraz zmiennej globalnej
seen_lock = threading.Lock() 
auto_publish_enabled = True 


# --- FUNKCJE POMOCNICZE DLA PLIKU 'SEEN' ---

def load_seen() -> set:
    """Wczytuje zbiór identyfikatorów opublikowanych wpisów z pliku."""
    if SEEN_FILE.exists():
        with seen_lock:
            try:
                return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
            except Exception:
                logging.error("Błąd podczas wczytywania seen.json. Resetowanie listy.")
                return set()
    return set()


def save_seen(seen_set: set):
    """Zapisuje zbiór identyfikatorów opublikowanych wpisów do pliku."""
    with seen_lock:
        SEEN_FILE.write_text(
            json.dumps(list(seen_set), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )


# --- FUNKCJE FORMATOWANIA I WYSYŁANIA ---

def escape_html(s: str) -> str:
    """Escapuje znaki HTML w tekście."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


def format_entry(entry):
    """Formatuje wpis RSS na wiadomość Telegram w trybie HTML."""
    title = entry.get("title", "Bez tytułu")
    link = entry.get("link", "")
    summary = entry.get("summary", "")

    # Usuń tagi HTML z podsumowania
    plain = re.sub("<[^<]+?>", "", summary).strip()

    # Skróć podsumowanie, jeśli jest za długie
    if len(plain) > 300:
        plain = plain[:297].rsplit(" ", 1)[0] + "..."

    msg = f"<b>{escape_html(title)}</b>\n{link}"
    if plain:
        msg += f"\n\n{escape_html(plain)}"
        
    return msg


def send_telegram_message(text, chat_id=None):
    """Wysyła wiadomość do Telegrama."""
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
        logging.info(f"Wiadomość wysłana do chatu {chat_id}.")
    except Exception as e:
        logging.error(f"Błąd API Telegrama: {e}")
        try:
            logging.error(f"Odpowiedź API: {r.text}")
        except:
            pass


def get_entries_last_7_days():
    """Pobiera i filtruje wpisy z ostatnich 7 dni."""
    try:
        feed = feedparser.parse(FEED_URL)
        week_ago = datetime.utcnow() - timedelta(days=7)
        results = []

        for entry in feed.entries:
            published = entry.get("published_parsed")
            if not published:
                continue

            # Konwersja czasu publikacji na obiekt datetime
            dt = datetime(*published[:6])
            if dt >= week_ago:
                results.append(entry)
        
        return results
    except Exception as e:
        logging.error(f"Błąd podczas parsowania RSS: {e}")
        return []


# --- WEBHOOK (Obsługa komend od bota) ---

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def telegram_webhook():
    """Obsługuje komendy przesłane przez Telegram do bota."""
    global auto_publish_enabled

    data = request.json
    if not data:
        return "no json", 200

    message = data.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return "no chat id", 200

    # Zabezpieczenie: możesz dodać tu sprawdzenie, czy chat_id jest Twoim ID!

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
            send_telegram_message("Brak artykułów z ostatnich 7 dni.", chat_id)
        else:
            for e in entries:
                # Ograniczenie liczby wiadomości do 5, by nie spamować
                if len(entries) > 5: break 
                send_telegram_message(format_entry(e), chat_id)
            if len(entries) > 5:
                send_telegram_message(f"Pokazano 5 z {len(entries)} artykułów.", chat_id)

    elif text == "/auto_on":
        auto_publish_enabled = True
        send_telegram_message("Auto-publikacja włączona ✔️", chat_id)

    elif text == "/auto_off":
        auto_publish_enabled = False
        send_telegram_message("Auto-publikacja wyłączona ❌", chat_id)

    return "ok", 200


# --- GŁÓWNA PĘTLA ROBOCZA (WORKER) ---

def main_loop():
    """Pętla cyklicznie sprawdzająca nowe wpisy RSS."""
    seen = load_seen()
    logging.info(f"Wczytano {len(seen)} znanych wpisów.")

    while True:
        try:
            if auto_publish_enabled:
                feed = feedparser.parse(FEED_URL)
                entries = feed.entries
                new_entries_found = False

                # Przetwarzamy wpisy od najstarszego do najnowszego (stąd reversed)
                for entry in reversed(entries):
                    # Używamy ID wpisu lub linku jako unikalnego identyfikatora
                    eid = entry.get("id") or entry.get("link")

                    if eid and eid not in seen:
                        msg = format_entry(entry)
                        send_telegram_message(msg)
                        seen.add(eid)
                        new_entries_found = True
                        time.sleep(1) # Odstęp, by uniknąć limitu wiadomości na sekundę

                # Zapisujemy plik tylko raz, jeśli znaleziono nowe wpisy
                if new_entries_found:
                    save_seen(seen)
            
            # W środowisku produkcyjnym dobrym pomysłem jest logowanie aktualnego stanu
            logging.info(f"Stan: Auto-publikacja {'WŁĄCZONA' if auto_publish_enabled else 'WYŁĄCZONA'}. Czekam {POLL_INTERVAL_SECONDS}s.")

        except Exception:
            # Logowanie pełnego błędu
            logging.error(traceback.format_exc())

        time.sleep(POLL_INTERVAL_SECONDS)


# --- URUCHOMIENIE APLIKACJI ---

if __name__ == "__main__":
    # Uruchomienie pętli sprawdzającej w osobnym wątku
    t = threading.Thread(target=main_loop)
    t.daemon = True # Wątek zostanie zakończony, gdy główny wątek (Flask) się zakończy
    t.start()

    # Uruchomienie serwera Flask (obsługującego webhooki / komendy)
    # W środowisku produkcyjnym, zamiast app.run, użyłbyś Gunicorn/Waitress
    port = int(os.getenv("PORT", 3000))
    logging.info(f"Serwer Flask uruchomiony na porcie {port}.")
    app.run(host="0.0.0.0", port=port)
