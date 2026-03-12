import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """
    Centralised application configuration.
    All sensitive values are read from environment variables so that no
    secrets are ever committed to source control.
    """

    TMDB_API_KEY: str = os.getenv("TMDB_API_KEY", "")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Path to the JSON file used for persisting user preferences.
    PREFERENCES_FILE: str = "user_preferences.json"

    # How many pages of TMDB results to fetch when searching by genre.
    MAX_PAGES: int = 3

    # Maximum number of cast members shown per movie.
    MAX_CAST_MEMBERS: int = 5
