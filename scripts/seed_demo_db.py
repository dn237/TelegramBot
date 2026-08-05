"""Seed a demo SQLite database for portfolio screenshots and local testing.

Usage:
    python scripts/seed_demo_db.py --out telegrambot.sample.db

If `--out` is omitted, `telegrambot.sample.db` is used.

The script will create tables and insert a few users, movies, and collection entries.
"""
from __future__ import annotations
import os
import argparse
from datetime import datetime


def build_db_url(path: str) -> str:
    # Ensure an absolute-ish path
    return f"sqlite:///{os.path.abspath(path)}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="telegrambot.sample.db", help="Output SQLite file path")
    args = parser.parse_args()

    # Set DATABASE_URL before importing app DB helpers so they use this DB
    os.environ["DATABASE_URL"] = build_db_url(args.out)

    # Local imports after env override
    from services.db import engine, SessionLocal
    from models import schema

    # Create tables
    schema.Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        # Create sample users
        user1 = schema.User(telegram_id=12345, username="demo_user", genre="Action", min_rating=7.0, min_year=2000)
        user2 = schema.User(telegram_id=67890, username="test_user", genre="Comedy", min_rating=6.0, min_year=1990)
        session.add_all([user1, user2])
        session.flush()

        # Create sample movies
        movie1 = schema.MovieCache(tmdb_id=100, title_en="Demo Action", title_ru=None, poster_path=None, collection_name="Demo Franchise", part_number=1, overview="An action-packed demo film.", genres="Action, Adventure")
        movie2 = schema.MovieCache(tmdb_id=101, title_en="Demo Comedy", title_ru=None, poster_path=None, collection_name=None, part_number=None, overview="A light-hearted demo comedy.", genres="Comedy")
        session.add_all([movie1, movie2])
        session.flush()

        # Link collections
        col1 = schema.UserCollection(user_id=user1.id, movie_id=movie1.id, status="watched")
        col2 = schema.UserCollection(user_id=user1.id, movie_id=movie2.id, status="planned")
        col3 = schema.UserCollection(user_id=user2.id, movie_id=movie2.id, status="watched")
        session.add_all([col1, col2, col3])

        session.commit()
        print(f"Demo DB written to {os.path.abspath(args.out)}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
