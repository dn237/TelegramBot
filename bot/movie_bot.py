import logging
import random
import html
import math

import telebot
from telebot import types

from models.user_preferences import UserPreferencesManager
from services.tmdb_service import TMDBService

logger = logging.getLogger(__name__)

TELEGRAM_PHOTO_CAPTION_LIMIT = 1024
COLLECTION_PAGE_SIZE = 8


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
        b.message_handler(commands=["help", "menu"])(self._cmd_help)
        b.message_handler(commands=["recommend_movies"])(self._cmd_recommend_movies)
        b.message_handler(commands=["set_genre_preference"])(self._cmd_set_genre_preference)
        b.message_handler(commands=["set_quality_preference"])(self._cmd_set_quality_preference)
        b.message_handler(commands=["my_profile"])(self._cmd_my_profile)
        b.message_handler(commands=["my_movies"])(self._cmd_my_movies)
        b.message_handler(commands=["my_watched"])(self._cmd_my_watched)
        b.message_handler(commands=["my_to_watch"])(self._cmd_my_to_watch)
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
            markup = self._build_main_menu_markup()
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
        """Asks for confirmation before resetting all stored preferences."""
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Yes, reset everything", callback_data="clear_confirm"),
            types.InlineKeyboardButton("Cancel", callback_data="clear_cancel"),
        )
        self._bot.send_message(
            message.chat.id,
            "This will clear your genre, rating/year filters, watched history, and feedback. Continue?",
            reply_markup=markup,
        )

    def _cmd_help(self, message) -> None:
        """Shows the main command and shortcut overview."""
        self._bot.send_message(message.chat.id, self._build_help_text(), parse_mode="HTML")

    def _cmd_my_movies(self, message) -> None:
        self._send_movie_collection(message.chat.id, status=None, heading="All your movies")

    def _cmd_my_watched(self, message) -> None:
        self._send_movie_collection(message.chat.id, status="watched", heading="Your watched movies")

    def _cmd_my_to_watch(self, message) -> None:
        self._send_movie_collection(message.chat.id, status="planned", heading="Your to-watch movies")

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
        elif text == "set genre preference":
            self._cmd_set_genre_preference(message)
        elif text == "show my watched list":
            self._send_movie_collection(message.chat.id, status="watched", heading="Your watched movies")
        elif text == "show my to-watch list":
            self._send_movie_collection(message.chat.id, status="planned", heading="Your to-watch movies")
        elif text == "show all my movies":
            self._send_movie_collection(message.chat.id, status=None, heading="All your movies")
        elif text == "recommend by title":
            self._cmd_recommend_movies(message)
        elif text == "set quality preferences":
            self._cmd_set_quality_preference(message)
        elif text == "show my profile":
            self._cmd_my_profile(message)
        elif text == "help / commands":
            self._cmd_help(message)
        elif text == "browse my library":
            self._show_library_menu(message)
        elif text == "reset preferences":
            self._cmd_clear_preferences(message)

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

            elif data == "library_menu":
                self._show_library_menu(call.message)

            elif data == "library_watched":
                self._send_movie_collection(call.message.chat.id, status="watched", heading="Your watched movies")

            elif data == "library_to_watch":
                self._send_movie_collection(call.message.chat.id, status="planned", heading="Your to-watch movies")

            elif data == "library_all":
                self._send_movie_collection(call.message.chat.id, status=None, heading="All your movies")

            elif data == "library_help":
                self._bot.send_message(call.message.chat.id, self._build_help_text(), parse_mode="HTML")

            elif data.startswith("collection|"):
                _, status_key, page_text = data.split("|", 2)
                status = None if status_key == "all" else status_key
                page = max(1, int(page_text))
                heading = self._collection_heading(status)
                self._edit_movie_collection(call, call.message.chat.id, status, heading, page)

            elif data.startswith("movie_action|"):
                _, action, status_key, page_text, movie_text = data.split("|", 4)
                status = None if status_key == "all" else status_key
                page = max(1, int(page_text))
                movie_id = int(movie_text)
                self._handle_collection_movie_action(call, user_id, action, status, page, movie_id)

            elif data.startswith("collection_remove_confirm|"):
                _, status_key, page_text, movie_text = data.split("|", 3)
                status = None if status_key == "all" else status_key
                page = max(1, int(page_text))
                movie_id = int(movie_text)
                self._confirm_collection_removal(call, user_id, status, page, movie_id)

            elif data.startswith("collection_remove_cancel|"):
                _, status_key, page_text, movie_text = data.split("|", 3)
                status = None if status_key == "all" else status_key
                page = max(1, int(page_text))
                heading = self._collection_heading(status)
                self._bot.answer_callback_query(call.id, "Removal cancelled.")
                self._edit_movie_collection(call, user_id, status, heading, page)

            elif data.startswith("card_save|"):
                _, status, movie_text = data.split("|", 2)
                movie_id = int(movie_text)
                self._handle_card_save_action(call, user_id, movie_id, status)

            elif data == "clear_confirm":
                self._prefs.clear(user_id)
                self._bot.answer_callback_query(call.id, "Preferences reset.")
                self._bot.send_message(call.message.chat.id, "Your preferences have been reset.")
                self._cmd_start(call.message)

            elif data == "clear_cancel":
                self._bot.answer_callback_query(call.id, "Reset cancelled.")

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

    def _show_library_menu(self, message) -> None:
        """Sends a submenu for browsing the user's movie library."""
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("Watched", callback_data="library_watched"),
            types.InlineKeyboardButton("To-watch", callback_data="library_to_watch"),
        )
        markup.row(types.InlineKeyboardButton("All movies", callback_data="library_all"))
        markup.row(
            types.InlineKeyboardButton("Help / commands", callback_data="library_help"),
            types.InlineKeyboardButton("Main menu", callback_data="main_menu"),
        )
        self._bot.send_message(
            message.chat.id,
            "Browse your saved movie lists:",
            reply_markup=markup,
        )

    def _send_movie_details(self, message, movie: dict, genre_id) -> None:
        """
        Builds and sends the full movie info card (poster, details, action buttons).
        Also marks the movie as watched for this user.
        """
        self._send_movie_details_with_options(message, movie, genre_id, mark_watched=True)

    def _send_movie_details_with_options(
        self,
        message,
        movie: dict,
        genre_id,
        mark_watched: bool,
        extra_buttons: list[types.InlineKeyboardButton] | None = None,
    ) -> None:
        user_id = message.chat.id
        if mark_watched:
            self._prefs.upsert_movie_collection(user_id, movie, "watched")

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
        markup.row(
            types.InlineKeyboardButton("Mark watched", callback_data=f"card_save|watched|{movie['id']}"),
            types.InlineKeyboardButton("Mark to-watch", callback_data=f"card_save|planned|{movie['id']}"),
        )
        if extra_buttons:
            markup.row(*extra_buttons)

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

    def _handle_collection_movie_action(
        self,
        call,
        user_id: int,
        action: str,
        status: str | None,
        page: int,
        movie_id: int,
    ) -> None:
        item = self._prefs.get_collection_item(user_id, movie_id)
        if not item:
            self._bot.answer_callback_query(call.id, "Movie not found in your library.")
            return

        status_key = "all" if status is None else status
        heading = self._collection_heading(status)

        if action == "open":
            self._show_collection_movie_details(call, item, status, page)
            return

        if action == "watch":
            ok = self._prefs.set_collection_status(user_id, movie_id, "watched")
            message = "Marked as watched." if ok else "Could not update this movie."
        elif action == "plan":
            ok = self._prefs.set_collection_status(user_id, movie_id, "planned")
            message = "Moved to your to-watch list." if ok else "Could not update this movie."
        elif action == "remove":
            self._show_remove_confirmation(call, item, status, page)
            return
        else:
            self._bot.answer_callback_query(call.id, "Unknown action.")
            return

        self._bot.answer_callback_query(call.id, message)
        self._edit_movie_collection(call, call.message.chat.id, status, heading, page)

    def _handle_card_save_action(self, call, user_id: int, movie_id: int, status: str) -> None:
        movie = self._tmdb.get_movie_info(movie_id)
        if not movie:
            self._bot.answer_callback_query(call.id, "Movie details not available.")
            return

        ok = self._prefs.upsert_movie_collection(user_id, movie, status)
        if ok:
            message = "Added to your watched movies." if status == "watched" else "Added to your to-watch list."
        else:
            message = "Could not save this movie."
        self._bot.answer_callback_query(call.id, message)

    def _show_remove_confirmation(self, call, item: dict, status: str | None, page: int) -> None:
        status_key = "all" if status is None else status
        text = (
            f"<b>Remove this movie?</b>\n"
            f"{html.escape(item.get('title', 'Untitled'))}\n\n"
            "This will remove the movie from your library."
        )
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton(
                "Yes, remove",
                callback_data=f"collection_remove_confirm|{status_key}|{page}|{item['movie_id']}",
            ),
            types.InlineKeyboardButton(
                "Cancel",
                callback_data=f"collection_remove_cancel|{status_key}|{page}|{item['movie_id']}",
            ),
        )
        markup.row(
            types.InlineKeyboardButton("Back to library", callback_data="library_menu"),
            types.InlineKeyboardButton("Main menu", callback_data="main_menu"),
        )
        self._bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup,
        )
        self._bot.answer_callback_query(call.id, "Confirm removal.")

    def _confirm_collection_removal(self, call, user_id: int, status: str | None, page: int, movie_id: int) -> None:
        ok = self._prefs.remove_movie_from_collection(user_id, movie_id)
        message = "Removed from your library." if ok else "Could not remove this movie."
        self._bot.answer_callback_query(call.id, message)
        heading = self._collection_heading(status)
        self._edit_movie_collection(call, user_id, status, heading, page)

    def _show_collection_movie_details(self, call, item: dict, status: str | None, page: int) -> None:
        tmdb_id = item.get("tmdb_id")
        if tmdb_id:
            movie = self._tmdb.get_movie_info(int(tmdb_id)) or {}
            if movie:
                movie.setdefault("title", item.get("title", "Untitled"))
                movie.setdefault("overview", item.get("overview") or "No description available.")
                genre_ids = [g.get("id") for g in movie.get("genres", []) if isinstance(g.get("id"), int)]
                genre_id = genre_ids[0] if genre_ids else 0
                self._send_movie_details_with_options(
                    call.message,
                    movie,
                    genre_id,
                    mark_watched=False,
                    extra_buttons=[
                        types.InlineKeyboardButton("Back to list", callback_data=f"collection|{status or 'all'}|{page}"),
                        types.InlineKeyboardButton("Library", callback_data="library_menu"),
                    ],
                )
                self._bot.answer_callback_query(call.id, "Opened movie details.")
                return

        title = html.escape(item.get("title", "Untitled"))
        overview = html.escape(item.get("overview") or "No description available.")
        text = (
            f"<b>🎬 Title:</b> {title}\n"
            f"<b>📄 Status:</b> {html.escape(item.get('status', 'planned'))}\n"
            f"<b>🍿 Overview:</b> {overview}"
        )
        markup = types.InlineKeyboardMarkup()
        if status == "planned":
            markup.row(
                types.InlineKeyboardButton(
                    "Mark watched",
                    callback_data=f"movie_action|watch|{status or 'all'}|1|{item['movie_id']}",
                ),
                types.InlineKeyboardButton(
                    "Remove",
                    callback_data=f"movie_action|remove|{status or 'all'}|1|{item['movie_id']}",
                ),
            )
        elif status == "watched":
            markup.row(
                types.InlineKeyboardButton(
                    "Mark to-watch",
                    callback_data=f"movie_action|plan|{status or 'all'}|1|{item['movie_id']}",
                ),
                types.InlineKeyboardButton(
                    "Remove",
                    callback_data=f"movie_action|remove|{status or 'all'}|1|{item['movie_id']}",
                ),
            )
        else:
            markup.row(
                types.InlineKeyboardButton(
                    "Mark watched",
                    callback_data=f"movie_action|watch|all|1|{item['movie_id']}",
                ),
                types.InlineKeyboardButton(
                    "Remove",
                    callback_data=f"movie_action|remove|all|1|{item['movie_id']}",
                ),
            )
        markup.row(
            types.InlineKeyboardButton("Back to list", callback_data=f"collection|{status or 'all'}|{page}"),
            types.InlineKeyboardButton("Library", callback_data="library_menu"),
            types.InlineKeyboardButton("Main menu", callback_data="main_menu"),
        )
        self._bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        self._bot.answer_callback_query(call.id, "Opened movie details.")

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

    def _send_movie_collection(self, user_id: int, status: str | None, heading: str) -> None:
        items = self._prefs.get_movie_collection(user_id, status=status)
        if not items:
            self._bot.send_message(user_id, f"No movies found for {html.escape(heading.lower())}.", parse_mode="HTML")
            return

        text, markup = self._build_collection_page(items, heading, status, page=1)
        self._bot.send_message(user_id, text, parse_mode="HTML", reply_markup=markup)

    def _edit_movie_collection(self, call, user_id: int, status: str | None, heading: str, page: int) -> None:
        items = self._prefs.get_movie_collection(user_id, status=status)
        if not items:
            self._bot.answer_callback_query(call.id, "No movies found.")
            return

        text, markup = self._build_collection_page(items, heading, status, page=page)
        try:
            self._bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
                reply_markup=markup,
            )
            self._bot.answer_callback_query(call.id)
        except Exception:
            self._bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    def _build_collection_page(
        self,
        items: list[dict],
        heading: str,
        status: str | None,
        page: int = 1,
    ) -> tuple[str, types.InlineKeyboardMarkup | None]:
        total_pages = max(1, math.ceil(len(items) / COLLECTION_PAGE_SIZE))
        current_page = min(max(1, page), total_pages)
        start = (current_page - 1) * COLLECTION_PAGE_SIZE
        end = start + COLLECTION_PAGE_SIZE
        page_items = items[start:end]

        body = [
            f"<b>{html.escape(heading)}</b>",
            f"<i>Page {current_page}/{total_pages} • {len(items)} item(s)</i>",
            "<i>Tap a title to open its card.</i>",
        ]

        markup = types.InlineKeyboardMarkup()
        for item in page_items:
            status_key = "all" if status is None else status
            label = f"▶ {item['title'][:28]}"
            if status is None:
                label = f"▶ [{item['status']}] {item['title'][:20]}"
            markup.row(
                types.InlineKeyboardButton(
                    label,
                    callback_data=f"movie_action|open|{status_key}|{current_page}|{item['movie_id']}",
                )
            )
        nav_buttons = []
        status_key = "all" if status is None else status
        if current_page > 1:
            nav_buttons.append(
                types.InlineKeyboardButton("◀ Prev", callback_data=f"collection|{status_key}|{current_page - 1}")
            )
        if current_page < total_pages:
            nav_buttons.append(
                types.InlineKeyboardButton("Next ▶", callback_data=f"collection|{status_key}|{current_page + 1}")
            )
        if nav_buttons:
            markup.row(*nav_buttons)
        markup.row(
            types.InlineKeyboardButton("Library", callback_data="library_menu"),
            types.InlineKeyboardButton("Main menu", callback_data="main_menu"),
        )

        return "\n".join(body), markup

    def _collection_heading(self, status: str | None) -> str:
        if status == "watched":
            return "Your watched movies"
        if status == "planned":
            return "Your to-watch movies"
        return "All your movies"

    def _build_main_menu_markup(self) -> types.ReplyKeyboardMarkup:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        markup.row(
            types.KeyboardButton("Pick a random movie"),
            types.KeyboardButton("Select a movie by genre"),
        )
        markup.row(
            types.KeyboardButton("Set genre preference"),
            types.KeyboardButton("Recommend by title"),
            types.KeyboardButton("Browse my library"),
        )
        markup.row(
            types.KeyboardButton("Set quality preferences"),
            types.KeyboardButton("Show my profile"),
        )
        markup.row(
            types.KeyboardButton("Help / commands"),
            types.KeyboardButton("Reset preferences"),
        )
        return markup

    def _build_help_text(self) -> str:
        return (
            "<b>Available commands</b>\n"
            "/start — Open the main menu.\n"
            "/help — Show this command list.\n"
            "/menu — Alias for /start.\n"
            "/recommend_movies — Get recommendations from a movie title.\n"
            "/set_genre_preference — Choose your preferred genre.\n"
            "/set_quality_preference — Set minimum rating/year filters.\n"
            "/my_profile — View your learned taste profile.\n"
            "/my_movies — Show all saved movies.\n"
            "/my_watched — Show watched movies only.\n"
            "/my_to_watch — Show to-watch movies only.\n"
            "/clear_preferences — Reset all saved preferences and history.\n\n"
            "<b>Main menu shortcuts</b>\n"
            "Pick a random movie · Select a movie by genre · Set genre preference · Recommend by title · Browse my library\n"
            "<i>Library removals ask for confirmation before deleting.</i>"
        )

    def _chunk_text(self, lines: list[str], max_chars: int = 3500) -> list[str]:
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1
            if current and current_len + line_len > max_chars:
                chunks.append("\n".join(current))
                current = [line]
                current_len = line_len
            else:
                current.append(line)
                current_len += line_len

        if current:
            chunks.append("\n".join(current))

        return chunks

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
