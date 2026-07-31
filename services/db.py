"""SQLAlchemy engine and session setup.

The app reads `DATABASE_URL` from the environment (or defaults to a
local SQLite file). When using SQLite in multi-threaded contexts we
set `check_same_thread=False` so the debugger / threaded polling does
not error during local demos.

This module exposes `engine`, `SessionLocal` and `Base` for ORM models
to import and use. Use `get_db()` as a context / generator that yields
sessions and ensures they are closed.
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
