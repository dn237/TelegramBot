import logging

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
    prefs = UserPreferencesManager(config.PREFERENCES_FILE)
    tmdb_service = TMDBService(config.TMDB_API_KEY, config.MAX_CAST_MEMBERS)
    bot = MovieBot(config.TELEGRAM_BOT_TOKEN, tmdb_service, prefs, config.MAX_PAGES)
    bot.run()


if __name__ == "__main__":
    main()
