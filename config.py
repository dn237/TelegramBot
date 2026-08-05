# config.py
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
    
    # ADD THIS LINE: Explicit fallback for the local database URL
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///telegrambot.db")

    # How many pages of TMDB results to fetch when searching by genre.
    MAX_PAGES: int = 3

    # Maximum number of cast members shown per movie.
    MAX_CAST_MEMBERS: int = 5