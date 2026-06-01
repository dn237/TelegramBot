import json
import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError

from services.db import SessionLocal, engine
from models import schema

logger = logging.getLogger(__name__)


class UserPreferencesManager:
    """DB-backed user preference manager.

    Keeps the same method names as the previous JSON implementation, but stores
    all preferences in the `users` table so the bot can run without a local JSON
    preferences file.
    """

    def __init__(self, file_path: str | None = None) -> None:
        # `file_path` is accepted for backward compatibility but ignored.
        schema.Base.metadata.create_all(bind=engine)
        self._session_factory = SessionLocal

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _session(self):
        return self._session_factory()

    def _key(self, user_id: int) -> int:
        return int(user_id)

    def _get_user(self, session, user_id: int) -> schema.User:
        user = session.query(schema.User).filter_by(telegram_id=self._key(user_id)).first()
        if not user:
            user = schema.User(telegram_id=self._key(user_id))
            session.add(user)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                user = session.query(schema.User).filter_by(telegram_id=self._key(user_id)).first()
        return user

    @staticmethod
    def _loads_list(value: str) -> list:
        try:
            return list(json.loads(value or "[]"))
        except Exception:
            return []

    @staticmethod
    def _loads_dict(value: str) -> dict:
        try:
            return dict(json.loads(value or "{}"))
        except Exception:
            return {}

    @staticmethod
    def _dumps(value) -> str:
        return json.dumps(value, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initialize_user(self, user_id: int) -> None:
        with self._session() as session:
            self._get_user(session, user_id)

    def get_genre(self, user_id: int) -> Optional[str]:
        with self._session() as session:
            user = self._get_user(session, user_id)
            return user.genre

    def set_genre(self, user_id: int, genre: str) -> None:
        with self._session() as session:
            user = self._get_user(session, user_id)
            user.genre = genre
            session.commit()

    def get_watched(self, user_id: int) -> list:
        with self._session() as session:
            user = self._get_user(session, user_id)
            return self._loads_list(user.watched)

    def mark_watched(self, user_id: int, movie_id: int) -> None:
        with self._session() as session:
            user = self._get_user(session, user_id)
            watched = self._loads_list(user.watched)
            if movie_id not in watched:
                watched.append(movie_id)
                user.watched = self._dumps(watched)
                session.commit()

    def reset_watched(self, user_id: int) -> None:
        with self._session() as session:
            user = self._get_user(session, user_id)
            user.watched = self._dumps([])
            session.commit()

    def clear(self, user_id: int) -> None:
        with self._session() as session:
            user = self._get_user(session, user_id)
            user.genre = None
            user.min_rating = 6.5
            user.min_year = 2000
            user.watched = self._dumps([])
            user.liked_movies = self._dumps([])
            user.disliked_movies = self._dumps([])
            user.liked_genres = self._dumps({})
            user.disliked_genres = self._dumps({})
            session.commit()

    def _inc_genre_counts(self, target: dict, genre_ids: list[int]) -> None:
        for gid in genre_ids:
            key = str(gid)
            target[key] = int(target.get(key, 0)) + 1

    def _dec_genre_counts(self, target: dict, genre_ids: list[int]) -> None:
        for gid in genre_ids:
            key = str(gid)
            current = int(target.get(key, 0))
            if current <= 1:
                target.pop(key, None)
            else:
                target[key] = current - 1

    def mark_liked(self, user_id: int, movie_id: int, genre_ids: list[int]) -> None:
        with self._session() as session:
            user = self._get_user(session, user_id)
            liked = self._loads_list(user.liked_movies)
            disliked = self._loads_list(user.disliked_movies)
            liked_genres = self._loads_dict(user.liked_genres)
            disliked_genres = self._loads_dict(user.disliked_genres)

            if movie_id in liked:
                return

            liked.append(movie_id)
            self._inc_genre_counts(liked_genres, genre_ids)

            if movie_id in disliked:
                disliked.remove(movie_id)
                self._dec_genre_counts(disliked_genres, genre_ids)

            user.liked_movies = self._dumps(liked)
            user.disliked_movies = self._dumps(disliked)
            user.liked_genres = self._dumps(liked_genres)
            user.disliked_genres = self._dumps(disliked_genres)
            session.commit()

    def mark_disliked(self, user_id: int, movie_id: int, genre_ids: list[int]) -> None:
        with self._session() as session:
            user = self._get_user(session, user_id)
            liked = self._loads_list(user.liked_movies)
            disliked = self._loads_list(user.disliked_movies)
            liked_genres = self._loads_dict(user.liked_genres)
            disliked_genres = self._loads_dict(user.disliked_genres)

            if movie_id in disliked:
                return

            disliked.append(movie_id)
            self._inc_genre_counts(disliked_genres, genre_ids)

            if movie_id in liked:
                liked.remove(movie_id)
                self._dec_genre_counts(liked_genres, genre_ids)

            user.liked_movies = self._dumps(liked)
            user.disliked_movies = self._dumps(disliked)
            user.liked_genres = self._dumps(liked_genres)
            user.disliked_genres = self._dumps(disliked_genres)
            session.commit()

    def get_genre_feedback_weights(self, user_id: int) -> tuple[dict, dict]:
        with self._session() as session:
            user = self._get_user(session, user_id)
            return self._loads_dict(user.liked_genres), self._loads_dict(user.disliked_genres)

    def get_feedback_summary(self, user_id: int) -> dict:
        with self._session() as session:
            user = self._get_user(session, user_id)
            return {
                "liked_movies": len(self._loads_list(user.liked_movies)),
                "disliked_movies": len(self._loads_list(user.disliked_movies)),
            }

    def get_min_rating(self, user_id: int) -> float:
        with self._session() as session:
            user = self._get_user(session, user_id)
            return float(user.min_rating or 6.5)

    def set_min_rating(self, user_id: int, min_rating: float) -> None:
        with self._session() as session:
            user = self._get_user(session, user_id)
            user.min_rating = float(min_rating)
            session.commit()

    def get_min_year(self, user_id: int) -> int:
        with self._session() as session:
            user = self._get_user(session, user_id)
            return int(user.min_year or 2000)

    def set_min_year(self, user_id: int, min_year: int) -> None:
        with self._session() as session:
            user = self._get_user(session, user_id)
            user.min_year = int(min_year)
            session.commit()
