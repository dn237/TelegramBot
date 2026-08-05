import time
from typing import Any, cast

from services.db import SessionLocal
from models import schema
from services.tmdb_service import TMDBService
from config import Config

def backfill_old_movies():
    print("Starting database backfill for missing Franchises and Genres...")
    
    # Connect to your database and TMDB
    session = SessionLocal()
    tmdb = TMDBService(Config.TMDB_API_KEY)

    try:
        # Find all movies that have NO collection name OR NO genres saved
        old_movies = session.query(schema.MovieCache).filter(
            (schema.MovieCache.collection_name.is_(None)) | 
            (schema.MovieCache.genres.is_(None))
        ).all()

        if not old_movies:
            print("✅ All your movies are perfectly up to date! Nothing to fix.")
            return

        print(f"🔍 Found {len(old_movies)} movies missing data. Fetching updates from TMDB...")

        updated_count = 0
        for movie in old_movies:
            # 1. Fetch fresh, complete data from TMDB
            # `movie.tmdb_id` is typed by the ORM as `Column[int]` which
            # confuses Pylance when passing to a function expecting `int`.
            # Use `cast(int, ...)` to inform the type checker while leaving
            # the runtime value unchanged.
            tmdb_info = tmdb.get_movie_info(cast(int, movie.tmdb_id))
            if not tmdb_info:
                print(f"⚠️ [Skipping] Could not fetch TMDB data for ID: {movie.tmdb_id}")
                continue

            # 2. Extract Franchise (Collection)
            belongs_to = tmdb_info.get("belongs_to_collection")
            if belongs_to and isinstance(belongs_to, dict):
                # Pylance may treat ORM mapped attributes as `Column[...]` types and
                # complain when assigning `Optional[str]` to them. Cast the
                # instance to `Any` for the assignment to satisfy the type checker.
                cast(Any, movie).collection_name = belongs_to.get("name")

            # 3. Extract Genres (Just in case older movies are missing this too!)
            genre_list = tmdb_info.get("genres", [])
            genre_names = [g.get("name") for g in genre_list if g.get("name")]
            if genre_names:
                cast(Any, movie).genres = ", ".join(genre_names)

            updated_count += 1
            print(f"🔄 Updated: {movie.title_en} -> 📦 {movie.collection_name or 'None'} | 📂 {movie.genres or 'None'}")
            
            # Small delay so TMDB doesn't block us for spamming requests too fast
            time.sleep(0.1) 

        # 4. Save all the updates to your SQLite database
        session.commit()
        print(f"🎉 Success! Fixed and updated {updated_count} movies in your database.")

    except Exception as e:
        session.rollback()
        print(f"❌ Error during backfill: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    backfill_old_movies()