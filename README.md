# Coinn.pl Telegram Bot

Bot monitoruje `https://coinn.pl/feed/` i automatycznie publikuje nowe artykuły
na wskazanej grupie Telegram.

## Zmienne środowiskowe

Ustaw w Railway.com:

- `TELEGRAM_BOT_TOKEN` — token bota
- `TELEGRAM_CHAT_ID` — ID grupy (np. -1001234567890)
- `POLL_INTERVAL_SECONDS` — odstęp między sprawdzaniem feeda (domyślnie 60)

## Lokalny start

```bash
pip install -r requirements.txt
python app.py
