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

    def get_movie_collection(self, user_id: int, status: Optional[str] = None) -> list[dict]:
        with self._session() as session:
            user = self._get_user(session, user_id)
            query = (
                session.query(schema.UserCollection)
                .join(schema.MovieCache)
                .filter(schema.UserCollection.user_id == user.id)
                .order_by(schema.UserCollection.updated_at.desc(), schema.MovieCache.title_en.asc())
            )
            if status:
                query = query.filter(schema.UserCollection.status == status)

            items = []
            for entry in query.all():
                title = entry.movie.title_en or entry.movie.title_ru or "Untitled"
                items.append(
                    {
                        "id": entry.id,
                        "movie_id": entry.movie_id,
                        "tmdb_id": entry.movie.tmdb_id,
                        "title": title,
                        "status": entry.status,
                        "updated_at": entry.updated_at,
                        "overview": entry.movie.overview,
                        "poster_path": entry.movie.poster_path,
                    }
                )
            return items

    def get_collection_item(self, user_id: int, movie_id: int) -> Optional[dict]:
        with self._session() as session:
            user = self._get_user(session, user_id)
            entry = (
                session.query(schema.UserCollection)
                .join(schema.MovieCache)
                .filter(schema.UserCollection.user_id == user.id, schema.UserCollection.movie_id == movie_id)
                .first()
            )
            if not entry:
                return None

            title = entry.movie.title_en or entry.movie.title_ru or "Untitled"
            return {
                "id": entry.id,
                "movie_id": entry.movie_id,
                "tmdb_id": entry.movie.tmdb_id,
                "title": title,
                "status": entry.status,
                "updated_at": entry.updated_at,
                "overview": entry.movie.overview,
                "poster_path": entry.movie.poster_path,
            }

    def set_collection_status(self, user_id: int, movie_id: int, status: str) -> bool:
        with self._session() as session:
            user = self._get_user(session, user_id)
            entry = (
                session.query(schema.UserCollection)
                .filter(schema.UserCollection.user_id == user.id, schema.UserCollection.movie_id == movie_id)
                .first()
            )
            if not entry:
                movie = session.query(schema.MovieCache).filter(schema.MovieCache.id == movie_id).first()
                if not movie:
                    return False
                entry = schema.UserCollection(user_id=user.id, movie_id=movie_id, status=status)
                session.add(entry)

            else:
                entry.status = status

            watched = self._loads_list(user.watched)
            if status == "watched":
                if movie_id not in watched:
                    watched.append(movie_id)
            else:
                if movie_id in watched:
                    watched.remove(movie_id)
            user.watched = self._dumps(watched)
            session.commit()
            return True

    def upsert_movie_collection(self, user_id: int, movie: dict, status: str) -> bool:
        tmdb_id = movie.get("id")
        if tmdb_id is None:
            return False

        tmdb_id = int(tmdb_id)
        title = movie.get("title") or movie.get("name") or "Untitled"
        overview = movie.get("overview")
        poster_path = movie.get("poster_path")
        original_language = movie.get("original_language")

        with self._session() as session:
            user = self._get_user(session, user_id)

            movie_entry = session.query(schema.MovieCache).filter(schema.MovieCache.tmdb_id == tmdb_id).first()
            if not movie_entry:
                movie_entry = schema.MovieCache(
                    tmdb_id=tmdb_id,
                    title_en=title,
                    title_ru=title if original_language == "ru" else None,
                    poster_path=poster_path,
                    collection_name=(movie.get("belongs_to_collection") or {}).get("name") if movie.get("belongs_to_collection") else None,
                    part_number=None,
                    overview=overview,
                )
                session.add(movie_entry)
                session.flush()
            else:
                movie_entry.title_en = title or movie_entry.title_en
                if original_language == "ru" and not movie_entry.title_ru:
                    movie_entry.title_ru = title
                movie_entry.poster_path = poster_path or movie_entry.poster_path
                movie_entry.overview = overview or movie_entry.overview

            collection_entry = (
                session.query(schema.UserCollection)
                .filter(schema.UserCollection.user_id == user.id, schema.UserCollection.movie_id == movie_entry.id)
                .first()
            )
            if not collection_entry:
                collection_entry = schema.UserCollection(user_id=user.id, movie_id=movie_entry.id, status=status)
                session.add(collection_entry)
            else:
                collection_entry.status = status

            watched = self._loads_list(user.watched)
            if status == "watched":
                if movie_entry.id not in watched:
                    watched.append(movie_entry.id)
            else:
                if movie_entry.id in watched:
                    watched.remove(movie_entry.id)
            user.watched = self._dumps(watched)

            session.commit()
            return True

    def remove_movie_from_collection(self, user_id: int, movie_id: int) -> bool:
        with self._session() as session:
            user = self._get_user(session, user_id)
            entry = (
                session.query(schema.UserCollection)
                .filter(schema.UserCollection.user_id == user.id, schema.UserCollection.movie_id == movie_id)
                .first()
            )
            if not entry:
                return False

            watched = self._loads_list(user.watched)
            if movie_id in watched:
                watched.remove(movie_id)
                user.watched = self._dumps(watched)

            session.delete(entry)
            session.commit()
            return True

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
