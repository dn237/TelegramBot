"""Entry point for the MovieRec Telegram bot.

This module wires together configuration, services, and the bot
implementation and starts the bot. It also performs quick runtime
validation (token / API key) so failures are clear for demo/portfolio use.
"""

import logging
import requests

from config import Config
from models.user_preferences import UserPreferencesManager
from services.tmdb_service import TMDBService
from bot.movie_bot import MovieBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def main() -> None:
    config = Config()
    if not config.TELEGRAM_BOT_TOKEN:
        logging.error(
            "TELEGRAM_BOT_TOKEN not set. Please set TELEGRAM_BOT_TOKEN in the environment or .env file"
        )
        return
    # Quick validation of the Telegram token to fail fast on invalid credentials
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe",
            timeout=5,
        )
        if resp.status_code != 200:
            logging.error(
                "TELEGRAM_BOT_TOKEN validation failed (%s): %s",
                resp.status_code,
                resp.text,
            )
            return
    except Exception as e:
        logging.error("Failed to validate TELEGRAM_BOT_TOKEN: %s", e)
        return
    if not config.TMDB_API_KEY:
        logging.warning("TMDB_API_KEY is not set. TMDB features may be limited.")
    prefs = UserPreferencesManager()
    tmdb_service = TMDBService(config.TMDB_API_KEY, config.MAX_CAST_MEMBERS)
    bot = MovieBot(config.TELEGRAM_BOT_TOKEN, tmdb_service, prefs, config.MAX_PAGES)
    bot.run()


if __name__ == "__main__":
    main()
