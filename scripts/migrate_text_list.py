"""Import a plain text movie list into the SQLite database.

Each line in the input file should contain a movie title and optionally a
status marker. Supported markers: leading `✅` (watched) or `🎬` (to watch).
If no marker is present, the script will try to detect `watched` / `to watch`
words; otherwise the item is treated as `planned`.

Usage:
    python scripts/migrate_text_list.py --file mylist.txt --telegram-id 123456
    python scripts/migrate_text_list.py --file watched.txt --telegram-id 123456 --watched
    python scripts/migrate_text_list.py --file to_watch.txt --telegram-id 123456 --to-watch

Requires `TMDB_API_KEY` env var or `--tmdb-key` argument.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    _HAS_DOTENV = True
except Exception:
    _HAS_DOTENV = False

# When running this script directly (python scripts/migrate_text_list.py),
# Python's import path is set to the `scripts/` directory which prevents
# sibling packages (like `services` and `models`) from being imported.
# Add the repository root to `sys.path` so `from services.db import ...`
# and `from models import schema` work reliably.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.exc import IntegrityError

from services.db import engine, SessionLocal
from models import schema
from services.tmdb_service import TMDBService

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


STATUS_WATCHED = "watched"
STATUS_PLANNED = "planned"


def parse_line(line: str) -> tuple[str, str]:
    """Return (title, status) extracted from a line."""
    original = line.strip()
    if not original:
        return "", ""

    # Leading emoji markers
    if original.startswith("✅"):
        return original.lstrip("✅ ").strip(), STATUS_WATCHED
    if original.startswith("🎬"):
        return original.lstrip("🎬 ").strip(), STATUS_PLANNED

    # Trailing status markers like " - watched" or " (watched)"
    m = re.match(r"^(.*?)[\s\-\(\[]+watched[\)\]]?$", original, flags=re.I)
    if m:
        return m.group(1).strip(), STATUS_WATCHED
    m2 = re.match(r"^(.*?)[\s\-\(\[]+to\s*watch[\)\]]?$", original, flags=re.I)
    if m2:
        return m2.group(1).strip(), STATUS_PLANNED

    # Default: treat as planned
    return original, STATUS_PLANNED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate text movie list into DB")
    parser.add_argument("--file", required=True, help="Path to the text file")
    parser.add_argument("--telegram-id", required=True, type=int, help="Telegram user id to assign the list to")
    parser.add_argument("--username", help="Optional username to save")
    parser.add_argument("--tmdb-key", help="TMDB API key (or set TMDB_API_KEY env var)")
    status_group = parser.add_mutually_exclusive_group()
    status_group.add_argument("--watched", action="store_true", help="Force every imported title to be marked as watched")
    status_group.add_argument("--to-watch", action="store_true", help="Force every imported title to be marked as planned")
    parser.add_argument("--skip-tmdb", action="store_true", help="Import titles without resolving to TMDB (creates local cache entries)")
    parser.add_argument("--require-tmdb", action="store_true", help="Fail instead of falling back if TMDB validation does not pass")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of lines to import (0 = all)")
    args = parser.parse_args(argv)

    tmdb_key = args.tmdb_key or os.getenv("TMDB_API_KEY")
    # Auto-load .env in project root if available and no key provided
    if not tmdb_key and _HAS_DOTENV:
        load_dotenv(dotenv_path=ROOT / ".env")
        tmdb_key = args.tmdb_key or os.getenv("TMDB_API_KEY")

    if not os.path.exists(args.file):
        logger.error("File not found: %s", args.file)
        return 2

    # Ensure DB tables exist
    schema.Base.metadata.create_all(bind=engine)

    tmdb: Optional[TMDBService] = None
    if not args.skip_tmdb:
        if not tmdb_key:
            if args.require_tmdb:
                logger.error("TMDB API key is required via --tmdb-key or TMDB_API_KEY env var")
                return 2
            logger.warning("No TMDB key found; falling back to title-only import. Use --require-tmdb to enforce TMDB.")
            args.skip_tmdb = True
        else:
            # Quick TMDB key validation (fail fast on 401)
            try:
                import requests as _requests

                r = _requests.get(f"https://api.themoviedb.org/3/movie/550?api_key={tmdb_key}", timeout=10)
                if r.status_code != 200:
                    msg = f"TMDB API key validation failed (status {r.status_code})."
                    if args.require_tmdb:
                        logger.error("%s Check your key.", msg)
                        return 2
                    logger.warning("%s Falling back to title-only import.", msg)
                    args.skip_tmdb = True
                else:
                    tmdb = TMDBService(tmdb_key)
            except Exception as e:
                if args.require_tmdb:
                    logger.error("Failed to validate TMDB key: %s", e)
                    return 2
                logger.warning("Failed to validate TMDB key (%s). Falling back to title-only import.", e)
                args.skip_tmdb = True

    if args.skip_tmdb:
        logger.info("Running in title-only import mode.")

    session = SessionLocal()
    try:
        # Ensure user exists
        user = session.query(schema.User).filter_by(telegram_id=args.telegram_id).first()
        if not user:
            user = schema.User(telegram_id=args.telegram_id, username=args.username)
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info("Created user %s (id=%s)", args.telegram_id, user.id)

        created = 0
        skipped = 0

        def iter_lines(path: str):
            # Read bytes and try multiple decodings because files produced
            # by PowerShell here-strings are often UTF-16 LE with BOM.
            with open(path, "rb") as bf:
                data = bf.read()

            for enc in ("utf-8", "utf-8-sig", "utf-16", "cp1252"):
                try:
                    text = data.decode(enc)
                    logger.info("Detected file encoding: %s", enc)
                    break
                except Exception:
                    continue
            else:
                # Last resort: replace undecodable bytes
                text = data.decode("utf-8", errors="replace")
                logger.warning("Falling back to utf-8 with replacement for undecodable bytes")

            for line in text.splitlines():
                yield line

        for i, raw in enumerate(iter_lines(args.file)):
            if args.limit and i >= args.limit:
                break
            title, status = parse_line(raw)
            if not title:
                continue

            if args.watched:
                status = STATUS_WATCHED
            elif args.to_watch:
                status = STATUS_PLANNED

            movie: Optional[schema.MovieCache] = None
            if args.skip_tmdb:
                # Create lightweight cache entry without TMDB resolution
                movie = schema.MovieCache(
                    tmdb_id=None,
                    title_en=title,
                    title_ru=None,
                    poster_path=None,
                    collection_name=None,
                    part_number=None,
                    overview=None,
                )
                session.add(movie)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    movie = session.query(schema.MovieCache).filter_by(title_en=title).first()
            else:
                tmdb_id = tmdb.find_movie_by_name(title)
                if tmdb_id is None:
                    logger.warning("Could not resolve title: %s", title)
                    skipped += 1
                    continue

                # Check or insert movie cache
                movie = session.query(schema.MovieCache).filter_by(tmdb_id=tmdb_id).first()
                if not movie:
                    info = tmdb.get_movie_info(tmdb_id)
                    movie = schema.MovieCache(
                        tmdb_id=tmdb_id,
                        title_en=info.get("title") or title,
                        title_ru=info.get("title") if info.get("original_language") == "ru" else None,
                        poster_path=info.get("poster_path"),
                        collection_name=(info.get("belongs_to_collection") or {}).get("name") if info.get("belongs_to_collection") else None,
                        part_number=None,
                        overview=info.get("overview"),
                    )
                    session.add(movie)
                    try:
                        session.commit()
                    except IntegrityError:
                        session.rollback()
                        movie = session.query(schema.MovieCache).filter_by(tmdb_id=tmdb_id).first()

                # Create or update user_collection
                existing = (
                    session.query(schema.UserCollection)
                    .filter_by(user_id=user.id, movie_id=movie.id)
                    .first()
                )
                if existing:
                    # upgrade status if needed
                    if status == STATUS_WATCHED and not existing.is_watched():
                        existing.status = STATUS_WATCHED
                        session.commit()
                    skipped += 1
                    continue

                uc = schema.UserCollection(user_id=user.id, movie_id=movie.id, status=status)
                session.add(uc)
                try:
                    session.commit()
                    created += 1
                    logger.info("Imported: %s -> %s", title, status)
                except IntegrityError:
                    session.rollback()
                    skipped += 1

        logger.info("Done. Created=%s, Skipped=%s", created, skipped)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
