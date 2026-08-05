# Contributing & Running Locally

This file explains how to run the project locally, create a demo database for portfolio screenshots, and how to add tidy changes.

## Quickstart (Windows PowerShell)

1. Create and activate a virtual environment:

```powershell
python -m venv .venv
d:/Projects/TelegramBot/.venv/Scripts/Activate.ps1
```

2. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

3. Prepare environment variables (copy `.env.example` to `.env` and edit):

```powershell
copy .env.example .env
# Edit .env and fill TELEGRAM_BOT_TOKEN and TMDB_API_KEY
```

4. (Optional) Create a demo database for screenshots:

```powershell
python scripts/seed_demo_db.py --out telegrambot.sample.db
```

5. Start the bot (long-polling):

```powershell
python main.py
# Or use the explicit venv path:
# d:/Projects/TelegramBot/.venv/Scripts/python.exe main.py
```

Stop the bot with Ctrl+C.

## Troubleshooting

- `ModuleNotFoundError: No module named 'sqlalchemy'` — make sure you activated the `.venv` and installed `requirements.txt` in that environment.
- `401 Unauthorized` — your `TELEGRAM_BOT_TOKEN` is invalid. Create a new token using BotFather and update `.env`.
- `409 Conflict: terminated by other getUpdates request` — another process is fetching updates (or a webhook is set). Delete webhook using:

```powershell
python -c "from config import Config; import requests; c=Config(); print(requests.get(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/deleteWebhook').text)"
```

and ensure only one `main.py` process is running.

## Style & Formatting

- Keep functions small and single-responsibility.
- Add concise docstrings for public modules/classes/functions.
- Use `black` or `ruff` if you want consistent formatting (not required).

## Making the repo portfolio-ready

- Never commit `.env` or secrets. Use `.env.example` to show required variables.
- Use `scripts/seed_demo_db.py` to create a sanitized sample DB (`telegrambot.sample.db`) for screenshots.
- Keep `main.py` simple: it should be a one-screen entrypoint that wires services and starts the bot.

Thanks for keeping the project tidy — contribution PRs are welcome!