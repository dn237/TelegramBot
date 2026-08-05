from telebot import types

TELEGRAM_PHOTO_CAPTION_LIMIT = 1024

class MovieCardHandler:
    def __init__(self, bot, prefs, tmdb):
        self._bot = bot
        self._prefs = prefs
        self._tmdb = tmdb

    def send_movie_details(self, message, movie: dict, genre_id) -> None:
        """Builds and sends the full movie info card."""
        self.send_movie_details_with_options(message, movie, genre_id, mark_watched=False)

    def send_movie_details_with_options(
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
            f"<b>📂 Genre:</b> {genres}\n"
            f"<b>🌍 Country:</b> {country}\n"
            f"<b>🎭 Cast:</b> {cast}\n"
            f"<b>📺 Trailer:</b> {trailer if trailer else 'No trailer available.'}\n"
        )
        short_caption = (
            f"<b>🎬 {movie['title']}</b>\n"
            f"<b>⭐ Rating:</b> {rating} | <b>📅 Year:</b> {year}\n"
            f"<b>📂 Genre:</b> {genres}"
        )

        if len(short_caption) > TELEGRAM_PHOTO_CAPTION_LIMIT:
            short_caption = short_caption[: TELEGRAM_PHOTO_CAPTION_LIMIT - 3] + "..."

        markup = types.InlineKeyboardMarkup()
        
        # ---> VISUAL SEPARATOR FOR FUNCTIONS <---
        markup.row(types.InlineKeyboardButton("⸻ Actions ⸻", callback_data="ignore"))
        
        # Actionable functions mapped nicely
        markup.add(types.InlineKeyboardButton("[ 🎲 Next in this Genre ]", callback_data=f"another_{genre_id}_{movie['id']}"))
        markup.add(types.InlineKeyboardButton("[ 🔍 Find Similar Movies ]", callback_data=f"recommend_{movie['id']}"))
        markup.add(
            # ---> ADDED BRACKETS HERE FOR 100% UI CONSISTENCY <---
            types.InlineKeyboardButton("[ 👍 Like ]", callback_data=f"like_{movie['id']}"),
            types.InlineKeyboardButton("[ 👎 Dislike ]", callback_data=f"dislike_{movie['id']}"),
        )
        
        markup.row(types.InlineKeyboardButton("⸻ Save to Library ⸻", callback_data="ignore"))
        markup.row(
            types.InlineKeyboardButton("[ ✅ Watched ]", callback_data=f"card_save|watched|{movie['id']}"),
            types.InlineKeyboardButton("[ 🎬 To-Watch ]", callback_data=f"card_save|planned|{movie['id']}"),
        )
        markup.row(
            types.InlineKeyboardButton("[ 📁 Add to Custom Collection ]", callback_data=f"custom_list_add|{movie['id']}")
        )
        
        if extra_buttons:
            markup.row(*extra_buttons)

        if poster_url:
            if len(info) <= TELEGRAM_PHOTO_CAPTION_LIMIT:
                self._bot.send_photo(message.chat.id, photo=poster_url, caption=info, parse_mode="HTML", reply_markup=markup)
            else:
                self._bot.send_photo(message.chat.id, photo=poster_url, caption=short_caption, parse_mode="HTML", reply_markup=markup)
                self._bot.send_message(message.chat.id, info, parse_mode="HTML")
        else:
            self._bot.send_message(message.chat.id, info, parse_mode="HTML", reply_markup=markup)