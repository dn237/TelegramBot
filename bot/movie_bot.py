"""Telegram command handlers and high-level bot routing.

`MovieBot` encapsulates the `telebot.TeleBot` instance and registers
all command and callback handlers used by the UI. Handlers delegate
to `services` and `models` to keep this layer focused on I/O.
"""

import logging
import random
import html

import telebot
from telebot import types

from models.user_preferences import UserPreferencesManager
from services.tmdb_service import TMDBService

# Import your UI handlers (encapsulate presentation logic)
from handlers.library import LibraryHandler
from handlers.movie_cards import MovieCardHandler

logger = logging.getLogger(__name__)

class MovieBot:
    def __init__(
        self,
        token: str,
        tmdb_service: TMDBService,
        prefs: UserPreferencesManager,
        max_pages: int = 3,
    ) -> None:
        """Create bot instance and register handlers.

        Keep the constructor lightweight: inject the services and the
        preferences manager to make the class easy to unit-test.
        """
        self._bot = telebot.TeleBot(token)
        self._tmdb = tmdb_service
        self._prefs = prefs
        self._max_pages = max_pages

        # UI handler objects encapsulate message formatting and view logic.
        self.library = LibraryHandler(self._bot, self._prefs)
        self.cards = MovieCardHandler(self._bot, self._prefs, self._tmdb)

        self._configure_bot_menu()
        self._register_handlers()

    def run(self) -> None:
        """Start long-polling. In production you may replace this with
        a webhook-based deployment; polling is convenient for local demos."""
        logger.info("Bot is running.")
        self._bot.infinity_polling(timeout=10, long_polling_timeout=5)

    def _register_handlers(self) -> None:
        b = self._bot
        # FIXED: /menu is now properly an alias for /start
        b.message_handler(commands=["start", "menu"])(self._cmd_start)
        b.message_handler(commands=["help"])(self._cmd_help)
        
        b.message_handler(commands=["recommend_movies"])(self._cmd_recommend_movies)
        b.message_handler(commands=["set_genre_preference"])(self._cmd_set_genre_preference)
        b.message_handler(commands=["set_quality_preference"])(self._cmd_set_quality_preference)
        b.message_handler(commands=["my_profile"])(self._cmd_my_profile)
        b.message_handler(commands=["my_movies"])(self._cmd_my_movies)
        b.message_handler(commands=["my_watched"])(self._cmd_my_watched)
        b.message_handler(commands=["my_to_watch"])(self._cmd_my_to_watch)
        b.message_handler(commands=["clear_preferences"])(self._cmd_clear_preferences)
        b.message_handler(content_types=["photo", "audio", "video"])(self._handle_media)
        b.message_handler(commands=["set_blocked_languages"])(self._cmd_set_blocked_languages)

        b.message_handler(func=lambda m: True)(self._handle_text)
        b.callback_query_handler(func=lambda c: True)(self._handle_callback)

    def _configure_bot_menu(self) -> None:
        """Register command menu so Telegram Desktop/mobile can show it consistently."""
        try:
            self._bot.set_my_commands(
                [
                    types.BotCommand("start", "Open the main menu"),
                    types.BotCommand("menu", "Alias for /start"),
                    types.BotCommand("help", "Show available commands"),
                    types.BotCommand("recommend_movies", "Recommend by movie title"),
                    types.BotCommand("set_genre_preference", "Set favorite genre"),
                    types.BotCommand("set_quality_preference", "Set rating/year filters"),
                    types.BotCommand("set_blocked_languages", "Hide selected languages"),
                    types.BotCommand("my_profile", "Show your profile"),
                    types.BotCommand("my_movies", "Show all saved movies"),
                    types.BotCommand("my_watched", "Show watched movies"),
                    types.BotCommand("my_to_watch", "Show to-watch movies"),
                    types.BotCommand("clear_preferences", "Reset all preferences"),
                ]
            )

            # Force the chat menu button to open command list when supported.
            self._bot.set_chat_menu_button(menu_button=types.MenuButtonCommands(type="commands"))
        except Exception as e:
            logger.warning("Could not configure Telegram command menu: %s", e)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _cmd_start(self, message) -> None:
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
            self._bot.send_message(message.chat.id, "Sorry, I'm unable to start at the moment. Please try again later.")

    def _cmd_recommend_movies(self, message) -> None:
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
            self._bot.send_message(message.chat.id, "Movie not found.")

    def _cmd_set_genre_preference(self, message) -> None:
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
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Yes, reset everything", callback_data="clear_confirm"),
            types.InlineKeyboardButton("Cancel", callback_data="clear_cancel"),
        )
        self._bot.send_message(message.chat.id, "This will clear your genre, rating/year filters, watched history, and feedback. Continue?", reply_markup=markup)

    def _cmd_help(self, message) -> None:
        self._bot.send_message(message.chat.id, self._build_help_text(), parse_mode="HTML")

    def _cmd_my_movies(self, message) -> None:
        self._send_movie_collection(message.chat.id, status=None, heading="All your movies")

    def _cmd_my_watched(self, message) -> None:
        self._send_movie_collection(message.chat.id, status="watched", heading="Your watched movies")

    def _cmd_my_to_watch(self, message) -> None:
        self._send_movie_collection(message.chat.id, status="planned", heading="Your to-watch movies")

    def _cmd_set_quality_preference(self, message) -> None:
        current_rating = self._prefs.get_min_rating(message.chat.id)
        current_year = self._prefs.get_min_year(message.chat.id)
        sent = self._bot.send_message(message.chat.id, f"Set minimum TMDB rating (0.0 to 10.0).\nCurrent: {current_rating:.1f}\nExample: 7.0")
        self._bot.register_next_step_handler(sent, self._save_min_rating_step, current_year)

    def _save_min_rating_step(self, message, current_year: int) -> None:
        user_id = message.chat.id
        raw = str(message.text).strip().replace(",", ".")
        try:
            min_rating = float(raw)
        except ValueError:
            self._bot.send_message(user_id, "Invalid rating.")
            return

        if min_rating < 0 or min_rating > 10:
            self._bot.send_message(user_id, "Rating must be between 0.0 and 10.0.")
            return

        self._prefs.set_min_rating(user_id, min_rating)
        sent = self._bot.send_message(user_id, f"Now set minimum release year (e.g. 2005).\nCurrent: {current_year}")
        self._bot.register_next_step_handler(sent, self._save_min_year_step)

    def _save_min_year_step(self, message) -> None:
        user_id = message.chat.id
        raw = str(message.text).strip()
        if not raw.isdigit():
            self._bot.send_message(user_id, "Invalid year.")
            return

        min_year = int(raw)
        if min_year < 1900 or min_year > 2100:
            self._bot.send_message(user_id, "Year must be between 1900 and 2100.")
            return

        self._prefs.set_min_year(user_id, min_year)
        rating = self._prefs.get_min_rating(user_id)
        self._bot.send_message(user_id, f"Quality preferences updated.\n- Minimum rating: {rating:.1f}\n- Minimum year: {min_year}")

    def _cmd_my_profile(self, message) -> None:
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

    def _cmd_set_blocked_languages(self, message) -> None:
        user_id = message.chat.id
        current = self._prefs.get_blocked_languages(user_id)
        current_str = ", ".join(current) if current else "None"
        
        text = (
            f"<b>Current blocked languages:</b> {current_str}\n\n"
            "Reply with the 2-letter language codes you want to hide, separated by commas.\n"
            "<i>(Example: hi, ru, kn, te)</i>\n\n"
            "To clear your blocked list and see everything, reply with <b>none</b>."
        )
        sent = self._bot.send_message(user_id, text, parse_mode="HTML")
        self._bot.register_next_step_handler(sent, self._save_blocked_languages_step)

    def _save_blocked_languages_step(self, message) -> None:
        user_id = message.chat.id
        raw = message.text.lower().strip()
        
        if raw == 'none':
            self._prefs.set_blocked_languages(user_id, [])
            self._bot.send_message(user_id, "Cleared all blocked languages. You will now see movies from all countries.")
            self._cmd_start(message)
            return

        langs = [lang.strip() for lang in raw.split(",") if len(lang.strip()) == 2]
        
        if not langs:
            self._bot.send_message(user_id, "Invalid input. Please provide valid 2-letter codes (like 'hi' or 'ru'). Try again via the menu.")
            return

        self._prefs.set_blocked_languages(user_id, langs)
        self._bot.send_message(user_id, f"Blocked languages updated: <b>{', '.join(langs)}</b>", parse_mode="HTML")
        self._cmd_start(message)

    def _cmd_custom_list_prompt(self, call, movie_id: int) -> None:
        text = (
            "<b>Create or Add to Collection 📁</b>\n\n"
            "Reply with the name of your custom collection (e.g., <i>Favorites</i>, <i>Halloween</i>, <i>Family</i>):"
        )
        sent = self._bot.send_message(call.message.chat.id, text, parse_mode="HTML")
        self._bot.register_next_step_handler(sent, self._save_custom_list_step, movie_id)

    def _save_custom_list_step(self, message, movie_id: int) -> None:
        user_id = message.chat.id
        collection_name = message.text.strip().capitalize()
        
        if len(collection_name) > 25:
            collection_name = collection_name[:25]
            
        movie = self._tmdb.get_movie_info(movie_id)
        if not movie:
            self._bot.send_message(user_id, "Sorry, movie details not available.")
            return
            
        ok = self._prefs.upsert_movie_collection(user_id, movie, collection_name)
        
        if ok:
            self._bot.send_message(user_id, f"Added to <b>{html.escape(collection_name)}</b>! 📁\n<i>You can now view this in your Library.</i>", parse_mode="HTML")
            self._cmd_start(message)
        else:
            self._bot.send_message(user_id, "Error saving to custom collection.")

    # ------------------------------------------------------------------
    # Text and callback handlers
    # ------------------------------------------------------------------

    def _handle_text(self, message) -> None:
        text = message.text.lower()
        user_id = message.chat.id

        if "random movie" in text:
            self._send_random_movie(message, user_id)
        elif "browse by genre" in text or "select a movie" in text:
            self._show_genre_menu(message)
        elif "favorite genre" in text:
            self._cmd_set_genre_preference(message)
        elif "search similar" in text or "recommend" in text:
            self._cmd_recommend_movies(message)
        elif "quality filters" in text:
            self._cmd_set_quality_preference(message)
        elif "my profile" in text:
            self._cmd_my_profile(message)
        elif "help" in text:
            self._cmd_help(message)
        elif "my library" in text:
            self.library.show_library_menu(message)
        elif "reset all" in text or "reset preferences" in text:
            self._cmd_clear_preferences(message)
        elif "blocked languages" in text: 
            self._cmd_set_blocked_languages(message)

    def _handle_media(self, message) -> None:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Delete", callback_data="DELETE"))
        markup.add(types.InlineKeyboardButton("No", callback_data="NO"))
        self._bot.reply_to(message, "Would you like me to delete this?", reply_markup=markup)

    def _handle_callback(self, call) -> None:
        try:
            user_id = call.message.chat.id
            data = call.data

            if data == "ignore":
                self._bot.answer_callback_query(call.id)
                return

            if data.startswith("genre_"):
                genre_id = data.split("_", 1)[1]
                self._callback_show_movie_in_genre(call, genre_id, user_id)
            elif data.startswith("another_"):
                parts = data.split("_")
                genre_id = parts[1]
                exclude_id = int(parts[2]) if len(parts) > 2 else None
                self._callback_show_movie_in_genre(call, genre_id, user_id, exclude_id)
            elif data.startswith("recommend_"):
                movie_id = int(data.split("_", 1)[1])
                self._callback_show_recommendations(call, movie_id)
            elif data.startswith("like_"):
                movie_id = int(data.split("_", 1)[1])
                self._callback_like_movie(call, movie_id, user_id)
            elif data.startswith("dislike_"):
                movie_id = int(data.split("_", 1)[1])
                self._callback_dislike_movie(call, movie_id, user_id)
            elif data == "main_menu":
                self._cmd_start(call.message)
            elif data == "library_menu":
                self.library.show_library_menu(call.message)
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
                heading = self.library.collection_heading(status)
                self.library.edit_movie_collection(call, call.message.chat.id, status, heading, page)
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
                heading = self.library.collection_heading(status)
                self._bot.answer_callback_query(call.id, "Removal cancelled.")
                self.library.edit_movie_collection(call, user_id, status, heading, page)
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
            elif data.startswith("tmdb_card|"):
                _, movie_text = data.split("|", 1)
                self._callback_open_tmdb_card(call, int(movie_text))
            elif data.startswith("custom_list_add|"):
                _, movie_text = data.split("|", 1)
                self._cmd_custom_list_prompt(call, int(movie_text))
            elif data.startswith("filter_menu|"):
                _, status_key = data.split("|", 1)
                self.library.show_filter_menu(call, user_id, status_key)
            elif data == "library_collections":
                self.library.show_tmdb_collections_menu(call, page=1)
            elif data.startswith("lib_cols_page|"):
                _, page_str = data.split("|")
                self.library.show_tmdb_collections_menu(call, page=int(page_str))
            elif data.startswith("del_list|"):
                _, list_name = data.split("|", 1)
                self._prompt_delete_custom_list(call, list_name)
            elif data.startswith("del_list_conf|"):
                _, list_name = data.split("|", 1)
                self._confirm_delete_custom_list(call, list_name)
        except Exception as e:
            logger.error("Error in callback handler: %s", e)
            self._bot.answer_callback_query(call.id, "Sorry, something went wrong.")

    # ------------------------------------------------------------------
    # Private helpers logic perfectly restored
    # ------------------------------------------------------------------

    def _send_random_movie(self, message, user_id: int) -> None:
        genres = self._tmdb.get_genres()
        genre_name = self._prefs.get_genre(user_id)
        genre_id = genres.get(genre_name) if genre_name else random.choice(list(genres.values()))

        watched = self._prefs.get_watched(user_id)
        min_rating = self._prefs.get_min_rating(user_id)
        min_year = self._prefs.get_min_year(user_id)
        movies = self._tmdb.search_movies_by_genre(genre_id, watched, self._max_pages, min_rating=min_rating, min_year=min_year)  # type: ignore

        if movies:
            picked = self._pick_personalized_movie(user_id, movies)
            self.cards.send_movie_details_with_options(message, picked, genre_id, mark_watched=False)
        else:
            self._bot.send_message(message.chat.id, "No movies matched your filters. Resetting watched list so we can try again.")
            self._prefs.reset_watched(user_id)

    def _show_genre_menu(self, message) -> None:
        markup = types.InlineKeyboardMarkup()
        for name, gid in self._tmdb.get_genres().items():
            markup.add(types.InlineKeyboardButton(name, callback_data=f"genre_{gid}"))
        self._bot.send_message(message.chat.id, "Please select a genre:", reply_markup=markup)

    def _handle_collection_movie_action(self, call, user_id: int, action: str, status: str | None, page: int, movie_id: int) -> None:
        item = self._prefs.get_collection_item(user_id, movie_id)
        if not item:
            self._bot.answer_callback_query(call.id, "Movie not found in your library.")
            return

        heading = self.library.collection_heading(status)

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
        self.library.edit_movie_collection(call, call.message.chat.id, status, heading, page)

    def _handle_card_save_action(self, call, user_id: int, movie_id: int, status: str) -> None:
        movie = self._tmdb.get_movie_info(movie_id)
        if not movie:
            self._bot.answer_callback_query(call.id, "Movie details not available from TMDB.")
            return
        ok = self._prefs.upsert_movie_collection(user_id, movie, status)
        if ok:
            message = "Added to your watched history! ✅" if status == "watched" else "Added to your to-watch list! 🎬"
        else:
            message = "Could not save this movie to your library."
        self._bot.answer_callback_query(call.id, message)

    def _show_remove_confirmation(self, call, item: dict, status: str | None, page: int) -> None:
        status_key = "all" if status is None else status
        text = f"<b>Remove this movie?</b>\n{html.escape(item.get('title', 'Untitled'))}\n\nThis will remove the movie from your library."
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("Yes, remove", callback_data=f"collection_remove_confirm|{status_key}|{page}|{item['movie_id']}"),
            types.InlineKeyboardButton("Cancel", callback_data=f"collection_remove_cancel|{status_key}|{page}|{item['movie_id']}"),
        )
        markup.row(types.InlineKeyboardButton("Back to library", callback_data="library_menu"), types.InlineKeyboardButton("Main menu", callback_data="main_menu"))
        self._bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=markup)
        self._bot.answer_callback_query(call.id, "Confirm removal.")

    def _confirm_collection_removal(self, call, user_id: int, status: str | None, page: int, movie_id: int) -> None:
        ok = self._prefs.remove_movie_from_collection(user_id, movie_id)
        message = "Removed from your library." if ok else "Could not remove this movie."
        self._bot.answer_callback_query(call.id, message)
        heading = self.library.collection_heading(status)
        self.library.edit_movie_collection(call, user_id, status, heading, page)

    def _show_collection_movie_details(self, call, item: dict, status: str | None, page: int) -> None:
        tmdb_id = item.get("tmdb_id")
        if tmdb_id:
            movie = self._tmdb.get_movie_info(int(tmdb_id)) or {}
            if movie:
                movie.setdefault("title", item.get("title", "Untitled"))
                movie.setdefault("overview", item.get("overview") or "No description available.")
                genre_ids = [g.get("id") for g in movie.get("genres", []) if isinstance(g.get("id"), int)]
                genre_id = genre_ids[0] if genre_ids else 0
                self.cards.send_movie_details_with_options(
                    call.message, movie, genre_id, mark_watched=False,
                    extra_buttons=[
                        # ---> ADDED BRACKETS HERE <---
                        types.InlineKeyboardButton("[ 🔙 Back to List ]", callback_data=f"collection|{status or 'all'}|{page}"),
                        types.InlineKeyboardButton("[ 📚 Library ]", callback_data="library_menu"),
                    ],
                )
                self._bot.answer_callback_query(call.id, "Opened movie details.")
                return

        title = html.escape(item.get("title", "Untitled"))
        overview = html.escape(item.get("overview") or "No description available.")
        text = f"<b>🎬 Title:</b> {title}\n<b>📄 Status:</b> {html.escape(item.get('status', 'planned'))}\n<b>🍿 Overview:</b> {overview}"
        markup = types.InlineKeyboardMarkup()
        
        markup.row(types.InlineKeyboardButton("⸻ Actions ⸻", callback_data="ignore"))
        markup.row(types.InlineKeyboardButton("[ 🔙 Back to List ]", callback_data=f"collection|{status or 'all'}|{page}"), types.InlineKeyboardButton("[ 📚 Library ]", callback_data="library_menu"))
        
        self._bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        self._bot.answer_callback_query(call.id, "Opened movie details.")

    def _callback_show_movie_in_genre(self, call, genre_id: str, user_id: int, exclude_id: int | None = None) -> None:
        if not self._tmdb.is_valid_genre_id(genre_id):
            self._bot.send_message(call.message.chat.id, "Invalid genre selected.")
            return

        watched = self._prefs.get_watched(user_id)
        min_rating = self._prefs.get_min_rating(user_id)
        min_year = self._prefs.get_min_year(user_id)
        movies = self._tmdb.search_movies_by_genre(int(genre_id), watched, self._max_pages, min_rating=min_rating, min_year=min_year)

        if exclude_id and movies:
            movies = [m for m in movies if m.get('id') != exclude_id]

        if movies:
            picked = self._pick_personalized_movie(user_id, movies)
            self.cards.send_movie_details_with_options(call.message, picked, genre_id, mark_watched=False)
        else:
            self._bot.answer_callback_query(call.id, "No more unwatched movies in this genre.")
            self._cmd_start(call.message)


    def _callback_show_recommendations(self, call, movie_id: int) -> None:
        movies = self._tmdb.get_recommendations(movie_id)
        if movies:
            text = "<b>Recommended Movies:</b>\n<i>Tap a title to view details.</i>"
            markup = types.InlineKeyboardMarkup()
            
            for m in movies[:8]:
                label = f"▶ {m['title'][:30]}"
                markup.row(types.InlineKeyboardButton(label, callback_data=f"tmdb_card|{m['id']}"))
                
            self._bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
            self._bot.answer_callback_query(call.id)
        else:
            self._bot.answer_callback_query(call.id, "No recommendations available.")
    
    def _callback_open_tmdb_card(self, call, movie_id: int) -> None:
        movie = self._tmdb.get_movie_info(movie_id)
        if movie:
            genre_ids = [g.get("id") for g in movie.get("genres", []) if isinstance(g.get("id"), int)]
            genre_id = genre_ids[0] if genre_ids else 0
            
            self.cards.send_movie_details_with_options(
                call.message, movie, genre_id, mark_watched=False
            )
            self._bot.answer_callback_query(call.id)
        else:
            self._bot.answer_callback_query(call.id, "Could not load movie details.")

    def _callback_like_movie(self, call, movie_id: int, user_id: int) -> None:
        info = self._tmdb.get_movie_info(movie_id)
        genre_ids = [g.get("id") for g in info.get("genres", []) if isinstance(g.get("id"), int)]
        self._prefs.mark_liked(user_id, movie_id, genre_ids)
        self._bot.answer_callback_query(call.id, "Saved: you liked this movie.")

    def _callback_dislike_movie(self, call, movie_id: int, user_id: int) -> None:
        info = self._tmdb.get_movie_info(movie_id)
        genre_ids = [g.get("id") for g in info.get("genres", []) if isinstance(g.get("id"), int)]
        self._prefs.mark_disliked(user_id, movie_id, genre_ids)
        self._bot.answer_callback_query(call.id, "Saved: you disliked this movie.")

    def _pick_personalized_movie(self, user_id: int, movies: list[dict]) -> dict:
        import random
        liked, disliked = self._prefs.get_genre_feedback_weights(user_id)
        if not movies:
            return {}

        blocked_languages = self._prefs.get_blocked_languages(user_id)

        scored_movies = []
        for movie in movies:
            if movie.get("original_language") in blocked_languages:
                continue

            score = float(movie.get("vote_average", 0.0) or 0.0) * 0.1
            for gid in movie.get("genre_ids", []):
                score += float(liked.get(str(gid), 0)) * 2.0
                score -= float(disliked.get(str(gid), 0)) * 2.0
            
            scored_movies.append((score, movie))

        scored_movies.sort(key=lambda x: x[0], reverse=True)
        top_candidates = [m[1] for m in scored_movies[:10]]
        
        return random.choice(top_candidates) if top_candidates else {}

    def _send_movie_collection(self, user_id: int, status: str | None, heading: str) -> None:
        items = self._prefs.get_movie_collection(user_id, status=status)
        if not items:
            self._bot.send_message(user_id, f"No movies found for {html.escape(heading.lower())}.", parse_mode="HTML")
            return

        # Passed user_id here so the collection page can map its back buttons correctly
        text, markup = self.library.build_collection_page(items, heading, status, page=1, user_id=user_id)
        self._bot.send_message(user_id, text, parse_mode="HTML", reply_markup=markup)

    def _build_main_menu_markup(self) -> types.ReplyKeyboardMarkup:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        markup.row(types.KeyboardButton("🎲 Random Movie"), types.KeyboardButton("🎭 Browse by Genre"))
        markup.row(types.KeyboardButton("🔍 Search Similar"), types.KeyboardButton("📚 My Library"))
        markup.row(types.KeyboardButton("⚙️ Quality Filters"), types.KeyboardButton("🌐 Blocked Languages"), types.KeyboardButton("👤 My Profile"))
        markup.row(types.KeyboardButton("❤️ Favorite Genre"), types.KeyboardButton("❓ Help"), types.KeyboardButton("⚠️ Reset All"))
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

    def _format_top_genres(self, counters: dict, top_n: int = 3) -> str:
        if not counters:
            return "No data yet"
        id_to_name = {str(v): k for k, v in self._tmdb.get_genres().items()}
        ranked = sorted(counters.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
        return ", ".join(f"{id_to_name.get(genre_id, 'Unknown')} ({count})" for genre_id, count in ranked)

    def _callback_delete_media(self, call) -> None:
        try:
            self._bot.delete_message(call.message.chat.id, call.message.message_id - 1)
            self._bot.delete_message(call.message.chat.id, call.message.message_id)
            self._bot.answer_callback_query(call.id, "Media deleted.")
        except Exception:
            self._bot.answer_callback_query(call.id, "Error: Can't delete this message.")

    def _prompt_delete_custom_list(self, call, list_name: str) -> None:
        text = (
            f"<b>Delete Custom List?</b>\n\n"
            f"Are you sure you want to permanently delete your <b>{html.escape(list_name)}</b> list?\n"
            f"<i>(This will remove all movies currently saved inside it from your library)</i>"
        )
        markup = types.InlineKeyboardMarkup()
        
        # ---> VISUAL SEPARATOR FOR FUNCTIONS <---
        markup.row(types.InlineKeyboardButton("⸻ Actions ⸻", callback_data="ignore"))
        
        markup.row(
            types.InlineKeyboardButton(f"[ 🗑️ Yes, delete '{list_name}' ]", callback_data=f"del_list_conf|{list_name}"),
            types.InlineKeyboardButton("[ ❌ Cancel ]", callback_data=f"collection|{list_name}|1")
        )
        self._bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=markup)

    def _confirm_delete_custom_list(self, call, list_name: str) -> None:
        user_id = call.message.chat.id
        ok = self._prefs.delete_custom_collection(user_id, list_name)
        
        if ok:
            self._bot.answer_callback_query(call.id, f"List '{list_name}' deleted.")
        else:
            self._bot.answer_callback_query(call.id, "List not found or already deleted.")
            
        # Return to library menu and remove the old prompt message
        self.library.show_library_menu(call.message)
        self._bot.delete_message(call.message.chat.id, call.message.message_id)