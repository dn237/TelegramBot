import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class UserPreferencesManager:
    """
    Manages persistent user preferences stored in a local JSON file.

    Each user is identified by their Telegram chat ID. Preferences include:
    - watched: list of movie IDs the user has already seen.
    - genre:   the user's preferred genre name (or None if unset).

    String keys are used throughout so that round-tripping through JSON
    (which converts all dict keys to strings) is handled transparently.
    """

    def __init__(self, file_path: str) -> None:
        self._file_path = file_path
        self._data: dict = self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        try:
            with open(self._file_path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.info("Preferences file not found — starting with empty preferences.")
            return {}

    def _save(self) -> None:
        with open(self._file_path, "w") as f:
            json.dump(self._data, f, indent=4)

    def _key(self, user_id: int) -> str:
        """Returns a consistent string key for the given user ID."""
        return str(user_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initialize_user(self, user_id: int) -> None:
        """Creates a default preferences entry for the user if one does not exist."""
        key = self._key(user_id)
        if key not in self._data:
            self._data[key] = {
                "watched": [],
                "genre": None,
                "min_rating": 6.5,
                "min_year": 2000,
                "liked_movies": [],
                "disliked_movies": [],
                "liked_genres": {},
                "disliked_genres": {},
            }
            self._save()
        else:
            # Backward-compatible: ensure newly added keys exist for older users.
            prefs = self._data[key]
            changed = False
            if "min_rating" not in prefs:
                prefs["min_rating"] = 6.5
                changed = True
            if "min_year" not in prefs:
                prefs["min_year"] = 2000
                changed = True
            if "liked_movies" not in prefs:
                prefs["liked_movies"] = []
                changed = True
            if "disliked_movies" not in prefs:
                prefs["disliked_movies"] = []
                changed = True
            if "liked_genres" not in prefs:
                prefs["liked_genres"] = {}
                changed = True
            if "disliked_genres" not in prefs:
                prefs["disliked_genres"] = {}
                changed = True
            if changed:
                self._save()

    def get_genre(self, user_id: int) -> Optional[str]:
        """Returns the user's preferred genre name, or None if not set."""
        return self._data.get(self._key(user_id), {}).get("genre")

    def set_genre(self, user_id: int, genre: str) -> None:
        """Persists a new genre preference for the user."""
        self.initialize_user(user_id)
        self._data[self._key(user_id)]["genre"] = genre
        self._save()

    def get_watched(self, user_id: int) -> list:
        """Returns the list of movie IDs the user has already watched."""
        return self._data.get(self._key(user_id), {}).get("watched", [])

    def mark_watched(self, user_id: int, movie_id: int) -> None:
        """Adds a movie to the user's watched list and persists the change."""
        self.initialize_user(user_id)
        self._data[self._key(user_id)].setdefault("watched", []).append(movie_id)
        self._save()

    def reset_watched(self, user_id: int) -> None:
        """Clears the watched list so all genre movies become available again."""
        self.initialize_user(user_id)
        self._data[self._key(user_id)]["watched"] = []
        self._save()

    def clear(self, user_id: int) -> None:
        """Resets all preferences for the user (watched history and genre)."""
        self._data[self._key(user_id)] = {
            "watched": [],
            "genre": None,
            "min_rating": 6.5,
            "min_year": 2000,
            "liked_movies": [],
            "disliked_movies": [],
            "liked_genres": {},
            "disliked_genres": {},
        }
        self._save()

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
        """Marks a movie as liked and updates genre affinity counters."""
        self.initialize_user(user_id)
        prefs = self._data[self._key(user_id)]

        liked = prefs.setdefault("liked_movies", [])
        disliked = prefs.setdefault("disliked_movies", [])
        liked_genres = prefs.setdefault("liked_genres", {})
        disliked_genres = prefs.setdefault("disliked_genres", {})

        if movie_id in liked:
            return

        liked.append(movie_id)
        self._inc_genre_counts(liked_genres, genre_ids)

        if movie_id in disliked:
            disliked.remove(movie_id)
            self._dec_genre_counts(disliked_genres, genre_ids)

        self._save()

    def mark_disliked(self, user_id: int, movie_id: int, genre_ids: list[int]) -> None:
        """Marks a movie as disliked and updates genre affinity counters."""
        self.initialize_user(user_id)
        prefs = self._data[self._key(user_id)]

        liked = prefs.setdefault("liked_movies", [])
        disliked = prefs.setdefault("disliked_movies", [])
        liked_genres = prefs.setdefault("liked_genres", {})
        disliked_genres = prefs.setdefault("disliked_genres", {})

        if movie_id in disliked:
            return

        disliked.append(movie_id)
        self._inc_genre_counts(disliked_genres, genre_ids)

        if movie_id in liked:
            liked.remove(movie_id)
            self._dec_genre_counts(liked_genres, genre_ids)

        self._save()

    def get_genre_feedback_weights(self, user_id: int) -> tuple[dict, dict]:
        """Returns liked and disliked genre counters for personalization."""
        self.initialize_user(user_id)
        prefs = self._data[self._key(user_id)]
        return (
            dict(prefs.get("liked_genres", {})),
            dict(prefs.get("disliked_genres", {})),
        )

    def get_feedback_summary(self, user_id: int) -> dict:
        """Returns compact feedback stats for profile/reporting use-cases."""
        self.initialize_user(user_id)
        prefs = self._data[self._key(user_id)]
        return {
            "liked_movies": len(prefs.get("liked_movies", [])),
            "disliked_movies": len(prefs.get("disliked_movies", [])),
        }

    def get_min_rating(self, user_id: int) -> float:
        """Returns the minimum acceptable TMDB rating for movie picks."""
        self.initialize_user(user_id)
        return float(self._data[self._key(user_id)].get("min_rating", 6.5))

    def set_min_rating(self, user_id: int, min_rating: float) -> None:
        """Persists a minimum movie rating preference for the user."""
        self.initialize_user(user_id)
        self._data[self._key(user_id)]["min_rating"] = float(min_rating)
        self._save()

    def get_min_year(self, user_id: int) -> int:
        """Returns the oldest acceptable release year for movie picks."""
        self.initialize_user(user_id)
        return int(self._data[self._key(user_id)].get("min_year", 2000))

    def set_min_year(self, user_id: int, min_year: int) -> None:
        """Persists a minimum release year preference for the user."""
        self.initialize_user(user_id)
        self._data[self._key(user_id)]["min_year"] = int(min_year)
        self._save()
