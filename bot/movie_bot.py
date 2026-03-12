import logging
import random

import telebot
from telebot import types

from models.user_preferences import UserPreferencesManager
from services.tmdb_service import TMDBService

logger = logging.getLogger(__name__)

TELEGRAM_PHOTO_CAPTION_LIMIT = 1024


class MovieBot:
    """
    Main Telegram bot class.

    Owns a telebot.TeleBot instance and wires up all message/callback
    handlers. Business logic is delegated to TMDBService (API calls) and
    UserPreferencesManager (state persistence) which are injected via the
    constructor so the class is easy to test and extend.

    Usage:
        bot = MovieBot(token, tmdb_service, prefs_manager)
        bot.run()
    """

    def __init__(
        self,
        token: str,
        tmdb_service: TMDBService,
        prefs: UserPreferencesManager,
        max_pages: int = 3,
    ) -> None:
        self._bot = telebot.TeleBot(token)
        self._tmdb = tmdb_service
        self._prefs = prefs
        self._max_pages = max_pages
        self._register_handlers()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Starts the bot's long-polling loop (blocks until interrupted)."""
        logger.info("Bot is running.")
        self._bot.polling(none_stop=True)

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        """Registers all Telegram message and callback handlers."""
        b = self._bot

        b.message_handler(commands=["start"])(self._cmd_start)
        b.message_handler(commands=["recommend_movies"])(self._cmd_recommend_movies)
        b.message_handler(commands=["set_genre_preference"])(self._cmd_set_genre_preference)
        b.message_handler(commands=["set_quality_preference"])(self._cmd_set_quality_preference)
        b.message_handler(commands=["my_profile"])(self._cmd_my_profile)
        b.message_handler(commands=["clear_preferences"])(self._cmd_clear_preferences)

        # Media handler must be registered before the catch-all text handler.
        b.message_handler(content_types=["photo", "audio", "video"])(self._handle_media)
        b.message_handler(func=lambda m: True)(self._handle_text)

        b.callback_query_handler(func=lambda c: True)(self._handle_callback)

    # ------------------------------------------------------------------
    # Command handlers  (/start, /recommend_movies, …)
    # ------------------------------------------------------------------

    def _cmd_start(self, message) -> None:
        """Greets the user and displays the main menu keyboard."""
        try:
            self._prefs.initialize_user(message.chat.id)
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.row(
                types.KeyboardButton("Pick a random movie"),
                types.KeyboardButton("Select a movie by genre"),
                types.KeyboardButton("Set quality preferences"),
                types.KeyboardButton("Show my profile"),
                types.KeyboardButton("Display a list of available commands"),
            )
            self._bot.send_message(
                message.chat.id,
                f"Hi, {message.from_user.first_name}! How can I help you today?",
                reply_markup=markup,
            )
        except Exception as e:
            logger.error("Error in /start handler: %s", e)
            self._bot.send_message(
                message.chat.id, "Sorry, I'm unable to start at the moment. Please try again later."
            )

    def _cmd_recommend_movies(self, message) -> None:
        """Asks the user for a movie title and returns similar recommendations."""
        sent = self._bot.send_message(message.chat.id, "Please enter the name of the movie:")
        self._bot.register_next_step_handler(sent, self._process_movie_recommendation)

    def _process_movie_recommendation(self, message) -> None:
        movie_id = self._tmdb.find_movie_by_name(message.text)
        if movie_id:
            movies = self._tmdb.get_recommendations(movie_id)
            if movies:
                text = "Recommended Movies:\n" + "\n".join(m["title"] for m in movies)
            else:
                text = "No recommendations found for that movie."
            self._bot.send_message(message.chat.id, text)
        else:
            logger.warning("Movie not found for query: %s", message.text)
            self._bot.send_message(message.chat.id, "Movie not found.")

    def _cmd_set_genre_preference(self, message) -> None:
        """Shows a keyboard with all available genres for the user to pick from."""
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        for genre_name in self._tmdb.get_genres():
            markup.add(types.KeyboardButton(genre_name))
        msg = self._bot.send_message(message.chat.id, "Choose your preferred genre:", reply_markup=markup)
        self._bot.register_next_step_handler(msg, self._save_genre_preference)

    def _save_genre_preference(self, message) -> None:
        self._prefs.set_genre(message.chat.id, message.text)
        self._bot.send_message(message.chat.id, f"Genre preference set to {message.text}.")
        self._cmd_start(message)

    def _cmd_clear_preferences(self, message) -> None:
        """Resets all stored preferences (watched history and genre) for the user."""
        self._prefs.clear(message.chat.id)
        self._bot.send_message(message.chat.id, "Your preferences have been reset.")

    def _cmd_set_quality_preference(self, message) -> None:
        """Starts the flow for setting min rating and min release year filters."""
        current_rating = self._prefs.get_min_rating(message.chat.id)
        current_year = self._prefs.get_min_year(message.chat.id)
        sent = self._bot.send_message(
            message.chat.id,
            (
                "Set minimum TMDB rating (0.0 to 10.0).\n"
                f"Current: {current_rating:.1f}\n"
                "Example: 7.0"
            ),
        )
        self._bot.register_next_step_handler(sent, self._save_min_rating_step, current_year)

    def _save_min_rating_step(self, message, current_year: int) -> None:
        user_id = message.chat.id
        raw = str(message.text).strip().replace(",", ".")
        try:
            min_rating = float(raw)
        except ValueError:
            self._bot.send_message(user_id, "Invalid rating. Please enter a number like 6.5 or 7.0.")
            return

        if min_rating < 0 or min_rating > 10:
            self._bot.send_message(user_id, "Rating must be between 0.0 and 10.0.")
            return

        self._prefs.set_min_rating(user_id, min_rating)
        sent = self._bot.send_message(
            user_id,
            (
                "Now set minimum release year (e.g. 2005).\n"
                f"Current: {current_year}"
            ),
        )
        self._bot.register_next_step_handler(sent, self._save_min_year_step)

    def _save_min_year_step(self, message) -> None:
        user_id = message.chat.id
        raw = str(message.text).strip()
        if not raw.isdigit():
            self._bot.send_message(user_id, "Invalid year. Please enter a year like 2010.")
            return

        min_year = int(raw)
        if min_year < 1900 or min_year > 2100:
            self._bot.send_message(user_id, "Year must be between 1900 and 2100.")
            return

        self._prefs.set_min_year(user_id, min_year)
        rating = self._prefs.get_min_rating(user_id)
        self._bot.send_message(
            user_id,
            (
                "Quality preferences updated.\n"
                f"- Minimum rating: {rating:.1f}\n"
                f"- Minimum year: {min_year}"
            ),
        )

    def _cmd_my_profile(self, message) -> None:
        """Shows saved filters and learned taste profile for the current user."""
        user_id = message.chat.id
        genre = self._prefs.get_genre(user_id) or "Not set"
        min_rating = self._prefs.get_min_rating(user_id)
        min_year = self._prefs.get_min_year(user_id)
        liked, disliked = self._prefs.get_genre_feedback_weights(user_id)
        stats = self._prefs.get_feedback_summary(user_id)

        text = (
            "<b>Your Profile</b>\n"
            f"<b>Preferred genre:</b> {genre}\n"
            f"<b>Minimum rating:</b> {min_rating:.1f}\n"
            f"<b>Minimum year:</b> {min_year}\n"
            f"<b>Liked movies:</b> {stats['liked_movies']}\n"
            f"<b>Disliked movies:</b> {stats['disliked_movies']}\n"
            f"<b>Top liked genres:</b> {self._format_top_genres(liked)}\n"
            f"<b>Top disliked genres:</b> {self._format_top_genres(disliked)}"
        )
        self._bot.send_message(user_id, text, parse_mode="HTML")

    # ------------------------------------------------------------------
    # Text & media message handlers
    # ------------------------------------------------------------------

    def _handle_text(self, message) -> None:
        """Routes free-text messages that correspond to the main-menu buttons."""
        text = message.text.lower()
        user_id = message.chat.id

        if text == "pick a random movie":
            self._send_random_movie(message, user_id)
        elif text == "select a movie by genre":
            self._show_genre_menu(message)
        elif text == "set quality preferences":
            self._cmd_set_quality_preference(message)
        elif text == "show my profile":
            self._cmd_my_profile(message)
        elif text == "display a list of available commands":
            commands = (
                "/start — Restart the bot.\n"
                "/set_genre_preference — Set your preferred genre.\n"
                "/set_quality_preference — Set minimum rating/year filters.\n"
                "/my_profile — Show your saved preferences and taste profile.\n"
                "/recommend_movies — Get recommendations based on a movie title.\n"
                "/clear_preferences — Reset your watched history and genre preference."
            )
            self._bot.send_message(message.chat.id, commands)

    def _handle_media(self, message) -> None:
        """Responds to photo/audio/video messages with a delete prompt."""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Delete", callback_data="DELETE"))
        markup.add(types.InlineKeyboardButton("No", callback_data="NO"))
        self._bot.reply_to(
            message,
            "My creator, being the mad genius they are, thought it'd be hilarious to make me "
            "the detective of media-blindness. Elementary, my dear pixels!\n"
            "Would you like me to delete this?",
            reply_markup=markup,
        )

    # ------------------------------------------------------------------
    # Callback query handler
    # ------------------------------------------------------------------

    def _handle_callback(self, call) -> None:
        """Dispatches inline-keyboard callbacks to the appropriate helper method."""
        try:
            user_id = call.message.chat.id
            data = call.data

            if data.startswith("genre_"):
                genre_id = data.split("_", 1)[1]
                self._callback_show_movie_in_genre(call, genre_id, user_id)

            elif data.startswith("another_"):
                genre_id = data.split("_", 1)[1]
                self._callback_show_movie_in_genre(call, genre_id, user_id)

            elif data.startswith("recommend_"):
                movie_id = int(data.split("_", 1)[1])
                self._callback_show_recommendations(call, movie_id)

            elif data.startswith("like_"):
                movie_id = int(data.split("_", 1)[1])
                self._callback_like_movie(call, movie_id, user_id)

            elif data.startswith("dislike_"):
                movie_id = int(data.split("_", 1)[1])
                self._callback_dislike_movie(call, movie_id, user_id)

            elif data == "pick_another_genre":
                self._show_genre_menu(call.message)

            elif data == "main_menu":
                self._cmd_start(call.message)

            elif data == "DELETE":
                self._callback_delete_media(call)

            elif data == "NO":
                self._bot.answer_callback_query(call.id, "Operation cancelled.")

        except Exception as e:
            logger.error("Error in callback handler: %s", e)
            self._bot.answer_callback_query(call.id, "Sorry, something went wrong.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _send_random_movie(self, message, user_id: int) -> None:
        """Picks a random unwatched movie, using the user's preferred genre if set."""
        genres = self._tmdb.get_genres()
        genre_name = self._prefs.get_genre(user_id)
        genre_id = genres.get(genre_name) if genre_name else random.choice(list(genres.values()))

        watched = self._prefs.get_watched(user_id)
        min_rating = self._prefs.get_min_rating(user_id)
        min_year = self._prefs.get_min_year(user_id)
        movies = self._tmdb.search_movies_by_genre(
            genre_id,
            watched,
            self._max_pages,
            min_rating=min_rating,
            min_year=min_year,
        )

        if movies:
            picked = self._pick_personalized_movie(user_id, movies)
            self._send_movie_details(message, picked, genre_id)
        else:
            self._bot.send_message(
                message.chat.id,
                "No movies matched your filters in this genre. Resetting watched list so we can try again.",
            )
            self._prefs.reset_watched(user_id)

    def _show_genre_menu(self, message) -> None:
        """Sends an inline keyboard with all available genres."""
        markup = types.InlineKeyboardMarkup()
        for name, gid in self._tmdb.get_genres().items():
            markup.add(types.InlineKeyboardButton(name, callback_data=f"genre_{gid}"))
        self._bot.send_message(message.chat.id, "Please select a genre:", reply_markup=markup)

    def _send_movie_details(self, message, movie: dict, genre_id) -> None:
        """
        Builds and sends the full movie info card (poster, details, action buttons).
        Also marks the movie as watched for this user.
        """
        user_id = message.chat.id
        self._prefs.mark_watched(user_id, movie["id"])

        poster_url = self._tmdb.get_poster_url(movie)
        trailer = self._tmdb.get_trailer_url(movie["id"])
        country = self._tmdb.get_production_country(movie["id"])
        cast = self._tmdb.get_cast(movie["id"])
        genres = self._tmdb.get_genre_names(movie.get("genre_ids", []))
        rating = movie.get("vote_average", "N/A")
        year = str(movie.get("release_date", "Unknown"))[:4]

        info = (
            f"<b>🎬 Title:</b> {movie['title']}\n"
            f"<b>🍿 Overview:</b> {movie.get('overview', 'No description available.')}\n"
            f"<b>⭐ Rating:</b> {rating}\n"
            f"<b>📅 Year:</b> {year}\n"
            f"<b>🎭 Genre:</b> {genres}\n"
            f"<b>🌍 Country:</b> {country}\n"
            f"<b>👩🏼 Cast:</b> {cast}\n"
            f"<b>📽️ Trailer:</b> {trailer if trailer else 'No trailer available.'}\n"
        )

        short_caption = (
            f"<b>🎬 {movie['title']}</b>\n"
            f"<b>⭐ Rating:</b> {rating} | <b>📅 Year:</b> {year}\n"
            f"<b>🎭 Genre:</b> {genres}"
        )

        if len(short_caption) > TELEGRAM_PHOTO_CAPTION_LIMIT:
            short_caption = short_caption[: TELEGRAM_PHOTO_CAPTION_LIMIT - 3] + "..."

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "Watch another from this genre", callback_data=f"another_{genre_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "Get recommendations", callback_data=f"recommend_{movie['id']}"
            )
        )
        markup.add(
            types.InlineKeyboardButton("Like", callback_data=f"like_{movie['id']}"),
            types.InlineKeyboardButton("Dislike", callback_data=f"dislike_{movie['id']}"),
        )

        if poster_url:
            # Telegram photo captions are limited to 1024 chars.
            if len(info) <= TELEGRAM_PHOTO_CAPTION_LIMIT:
                self._bot.send_photo(
                    message.chat.id,
                    photo=poster_url,
                    caption=info,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                self._bot.send_photo(
                    message.chat.id,
                    photo=poster_url,
                    caption=short_caption,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                self._bot.send_message(message.chat.id, info, parse_mode="HTML")
        else:
            self._bot.send_message(message.chat.id, info, parse_mode="HTML", reply_markup=markup)

    def _callback_show_movie_in_genre(self, call, genre_id: str, user_id: int) -> None:
        """Picks and sends a random unwatched movie for the chosen genre."""
        if not self._tmdb.is_valid_genre_id(genre_id):
            self._bot.send_message(call.message.chat.id, "Invalid genre selected.")
            return

        watched = self._prefs.get_watched(user_id)
        min_rating = self._prefs.get_min_rating(user_id)
        min_year = self._prefs.get_min_year(user_id)
        movies = self._tmdb.search_movies_by_genre(
            int(genre_id),
            watched,
            self._max_pages,
            min_rating=min_rating,
            min_year=min_year,
        )

        if movies:
            picked = self._pick_personalized_movie(user_id, movies)
            self._send_movie_details(call.message, picked, genre_id)
        else:
            self._bot.answer_callback_query(call.id, "No more unwatched movies in this genre.")
            self._cmd_start(call.message)

    def _callback_show_recommendations(self, call, movie_id: int) -> None:
        """Sends a list of TMDB recommendations for the given movie."""
        movies = self._tmdb.get_recommendations(movie_id)
        if movies:
            text = "Recommended Movies:\n" + "\n".join(m["title"] for m in movies)
            self._bot.send_message(call.message.chat.id, text)
        else:
            self._bot.send_message(call.message.chat.id, "No recommendations available.")

    def _callback_like_movie(self, call, movie_id: int, user_id: int) -> None:
        """Stores positive feedback to improve future picks for this user."""
        info = self._tmdb.get_movie_info(movie_id)
        genre_ids = [g.get("id") for g in info.get("genres", []) if isinstance(g.get("id"), int)]
        self._prefs.mark_liked(user_id, movie_id, genre_ids)
        self._bot.answer_callback_query(call.id, "Saved: you liked this movie.")

    def _callback_dislike_movie(self, call, movie_id: int, user_id: int) -> None:
        """Stores negative feedback to avoid similar picks for this user."""
        info = self._tmdb.get_movie_info(movie_id)
        genre_ids = [g.get("id") for g in info.get("genres", []) if isinstance(g.get("id"), int)]
        self._prefs.mark_disliked(user_id, movie_id, genre_ids)
        self._bot.answer_callback_query(call.id, "Saved: you disliked this movie.")

    def _pick_personalized_movie(self, user_id: int, movies: list[dict]) -> dict:
        """Ranks candidate movies by user feedback and returns the best match."""
        liked, disliked = self._prefs.get_genre_feedback_weights(user_id)
        if not movies:
            return {}

        best_score = None
        best_movies = []

        for movie in movies:
            score = 0.0
            for gid in movie.get("genre_ids", []):
                g = str(gid)
                score += float(liked.get(g, 0)) * 2.0
                score -= float(disliked.get(g, 0)) * 2.0

            # Slightly favor better-rated movies among similarly scored options.
            score += float(movie.get("vote_average", 0.0) or 0.0) * 0.1

            if best_score is None or score > best_score:
                best_score = score
                best_movies = [movie]
            elif score == best_score:
                best_movies.append(movie)

        return random.choice(best_movies)

    def _format_top_genres(self, counters: dict, top_n: int = 3) -> str:
        """Converts genre-id counters into a readable top-N genre summary."""
        if not counters:
            return "No data yet"

        id_to_name = {str(v): k for k, v in self._tmdb.get_genres().items()}
        ranked = sorted(counters.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
        return ", ".join(
            f"{id_to_name.get(genre_id, 'Unknown')} ({count})"
            for genre_id, count in ranked
        )

    def _callback_delete_media(self, call) -> None:
        """Attempts to delete the media message and the bot's reply prompt."""
        try:
            self._bot.delete_message(call.message.chat.id, call.message.message_id - 1)
            self._bot.delete_message(call.message.chat.id, call.message.message_id)
            self._bot.answer_callback_query(call.id, "Media deleted.")
        except Exception:
            self._bot.answer_callback_query(call.id, "Error: Can't delete this message.")
