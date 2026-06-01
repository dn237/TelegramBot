"""Database configuration: SQLAlchemy engine, Base, and session factory.

Defaults to a local SQLite database at `./telegrambot.db`. The URL can be
overridden with the `DATABASE_URL` environment variable.
"""
from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./telegrambot.db")


def _connect_args(url: str) -> dict:
    # SQLite requires `check_same_thread=False` for multithreaded apps.
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


engine = create_engine(DATABASE_URL, **_connect_args(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db() -> Generator:
    """Yield a SQLAlchemy session and ensure it's closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
