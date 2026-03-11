import logging
from typing import Optional

import requests
import tmdbsimple as tmdb

logger = logging.getLogger(__name__)


class TMDBService:
    """
    Wrapper around the TMDB API.

    Provides high-level methods for the bot's use-cases:
    - Genre look-ups
    - Movie discovery and filtering
    - Movie details (cast, trailer, poster, production country)
    - Search by title and recommendations

    Results that are expensive to fetch (genres, paginated movie lists) are
    cached in-memory for the lifetime of the service instance so that the
    bot does not hammer the API with repeated identical requests.
    """

    def __init__(self, api_key: str, max_cast_members: int = 5) -> None:
        tmdb.API_KEY = api_key
        self._api_key = api_key
        self._max_cast = max_cast_members

        # In-memory caches
        self._genres_cache: Optional[dict] = None          # name → id
        self._movies_cache: dict[tuple, list] = {}         # (genre_id, page) → results

    # ------------------------------------------------------------------
    # Genres
    # ------------------------------------------------------------------

    def get_genres(self) -> dict:
        """Returns a dict mapping genre name → genre ID (cached after first call)."""
        if self._genres_cache is None:
            try:
                response = tmdb.Genres().movie_list()
                self._genres_cache = {g["name"]: g["id"] for g in response["genres"]}
                logger.info("Genres loaded: %s", list(self._genres_cache.keys()))
            except Exception as e:
                logger.error("Failed to fetch genres: %s", e)
                self._genres_cache = {}
        return self._genres_cache

    def is_valid_genre_id(self, genre_id: str) -> bool:
        """Returns True when genre_id is a digit string that matches a known genre."""
        return genre_id.isdigit() and int(genre_id) in self.get_genres().values()

    def get_genre_names(self, genre_ids: list) -> str:
        """Converts a list of genre IDs to a comma-separated string of names."""
        id_to_name = {v: k for k, v in self.get_genres().items()}
        return ", ".join(id_to_name.get(gid, "Unknown") for gid in genre_ids)

    # ------------------------------------------------------------------
    # Movie discovery
    # ------------------------------------------------------------------

    def _fetch_movies_page(self, genre_id: int, page: int) -> list:
        """Fetches one page of movies for the given genre (cached per genre/page pair)."""
        key = (genre_id, page)
        if key not in self._movies_cache:
            try:
                response = tmdb.Discover().movie(with_genres=str(genre_id), page=page)
                self._movies_cache[key] = response.get("results", [])
            except Exception as e:
                logger.error("Error fetching movies (genre=%s, page=%s): %s", genre_id, page, e)
                self._movies_cache[key] = []
        return self._movies_cache[key]

    def search_movies_by_genre(
        self,
        genre_id: int,
        watched_ids: list,
        max_pages: int = 3,
        min_rating: float = 0.0,
        min_year: int = 0,
    ) -> list:
        """
        Returns movies for the given genre, excluding the ones the user has
        already watched. Aggregates results across multiple pages.
        """
        all_movies = []
        for page in range(1, max_pages + 1):
            all_movies.extend(self._fetch_movies_page(genre_id, page))

        def release_year(movie: dict) -> int:
            date = str(movie.get("release_date", ""))
            if len(date) >= 4 and date[:4].isdigit():
                return int(date[:4])
            return 0

        return [
            m
            for m in all_movies
            if m["id"] not in watched_ids
            and float(m.get("vote_average", 0.0) or 0.0) >= float(min_rating)
            and release_year(m) >= int(min_year)
        ]

    # ------------------------------------------------------------------
    # Movie look-ups
    # ------------------------------------------------------------------

    def find_movie_by_name(self, name: str) -> Optional[int]:
        """Searches TMDB by title and returns the ID of the top result, or None."""
        try:
            results = tmdb.Search().movie(query=name).get("results", [])
            return results[0]["id"] if results else None
        except Exception as e:
            logger.error("Failed to find movie '%s': %s", name, e)
            return None

    def get_recommendations(self, movie_id: int) -> list:
        """Returns TMDB's recommendation list for the given movie."""
        try:
            return tmdb.Movies(movie_id).recommendations().get("results", [])
        except Exception as e:
            logger.error("Failed to get recommendations for movie %s: %s", movie_id, e)
            return []

    def get_movie_info(self, movie_id: int) -> dict:
        """Returns raw TMDB info payload for the given movie ID."""
        try:
            return tmdb.Movies(movie_id).info()
        except Exception as e:
            logger.error("Failed to get movie info for movie %s: %s", movie_id, e)
            return {}

    # ------------------------------------------------------------------
    # Movie details
    # ------------------------------------------------------------------

    def get_cast(self, movie_id: int) -> str:
        """Returns a comma-separated string of the top cast members."""
        try:
            credits = tmdb.Movies(movie_id).credits()
            names = [a["name"] for a in credits.get("cast", [])[:self._max_cast]]
            return ", ".join(names)
        except Exception as e:
            logger.error("Failed to fetch cast for movie %s: %s", movie_id, e)
            return "Cast details not available"

    def get_production_country(self, movie_id: int) -> str:
        """Returns the production country/countries for the given movie."""
        try:
            info = tmdb.Movies(movie_id).info()
            countries = info.get("production_countries", [])
            return ", ".join(c["name"] for c in countries) if countries else "Unknown"
        except Exception as e:
            logger.error("Failed to fetch production countries for movie %s: %s", movie_id, e)
            return "Unknown"

    def get_trailer_url(self, movie_id: int) -> Optional[str]:
        """
        Fetches the YouTube trailer URL for the movie.
        Returns None if no trailer is found or the request fails.
        """
        try:
            url = (
                f"https://api.themoviedb.org/3/movie/{movie_id}/videos"
                f"?api_key={self._api_key}"
            )
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                for result in response.json().get("results", []):
                    if result.get("type") == "Trailer" and result.get("site") == "YouTube":
                        logger.info("Trailer found for movie %s.", movie_id)
                        return f"https://www.youtube.com/watch?v={result['key']}"
        except Exception as e:
            logger.error("Failed to fetch trailer for movie %s: %s", movie_id, e)
        return None

    def get_poster_url(self, movie: dict) -> Optional[str]:
        """Returns the full poster image URL, or None if no poster is available."""
        path = movie.get("poster_path")
        return f"https://image.tmdb.org/t/p/w500{path}" if path else None
