"""SQLAlchemy ORM models for the Movie Tracker bot.

Contains `User`, `MovieCache`, and `UserCollection` tables. Import and
call `Base.metadata.create_all(engine)` (from `services.db`) during
initial setup or migrations to create the database schema.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Float,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from services.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(128), nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)
    genre = Column(String(128), nullable=True)
    min_rating = Column(Float, nullable=False, default=6.5)
    min_year = Column(Integer, nullable=False, default=2000)
    watched = Column(Text, nullable=False, default="[]")
    liked_movies = Column(Text, nullable=False, default="[]")
    disliked_movies = Column(Text, nullable=False, default="[]")
    liked_genres = Column(Text, nullable=False, default="{}")
    disliked_genres = Column(Text, nullable=False, default="{}")

    collection = relationship("UserCollection", back_populates="user")


class MovieCache(Base):
    __tablename__ = "movies_cache"

    id = Column(Integer, primary_key=True, index=True)
    tmdb_id = Column(Integer, unique=True, nullable=True, index=True)
    title_en = Column(String(512), nullable=False, index=True)
    title_ru = Column(String(512), nullable=True)
    poster_path = Column(String(512), nullable=True)
    collection_name = Column(String(256), nullable=True)
    part_number = Column(Integer, nullable=True)
    overview = Column(Text, nullable=True)

    users = relationship("UserCollection", back_populates="movie")


class UserFeedback(Base):
    __tablename__ = "user_feedback"
    __table_args__ = (UniqueConstraint("user_id", "movie_id", name="u_user_feedback_movie"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    movie_id = Column(Integer, ForeignKey("movies_cache.id", ondelete="CASCADE"), nullable=False)
    feedback_type = Column(String(16), nullable=False)
    genre_ids = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")
    movie = relationship("MovieCache")


class UserGenrePreference(Base):
    __tablename__ = "user_genre_preferences"
    __table_args__ = (UniqueConstraint("user_id", "genre_id", "feedback_type", name="u_user_genre_feedback"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    genre_id = Column(Integer, nullable=False, index=True)
    feedback_type = Column(String(16), nullable=False)
    score = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class UserCollection(Base):
    """Represents a user's relation to a cached movie.

    `status` is either `planned` or `watched`.
    """

    __tablename__ = "user_collection"
    __table_args__ = (UniqueConstraint("user_id", "movie_id", name="u_user_movie"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    movie_id = Column(Integer, ForeignKey("movies_cache.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="planned")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="collection")
    movie = relationship("MovieCache", back_populates="users")

    def is_watched(self) -> bool:
        return self.status == "watched"

