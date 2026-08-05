import html
import math
from telebot import types
from services.db import SessionLocal
from models import schema

COLLECTION_PAGE_SIZE = 8

class LibraryHandler:
    def __init__(self, bot, prefs):
        self._bot = bot
        self._prefs = prefs

    def show_library_menu(self, message) -> None:
        """Sends a submenu for browsing the user's movie library."""
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Watched", callback_data="library_watched"),
            types.InlineKeyboardButton("🎬 To-Watch", callback_data="library_to_watch"),
        )
        
        markup.row(types.InlineKeyboardButton("📦 Browse by Collection", callback_data="library_collections"))
        markup.row(types.InlineKeyboardButton("🎞️ All Movies", callback_data="library_all"))
        
        # --- DYNAMIC CUSTOM COLLECTIONS ---
        session = SessionLocal()
        try:
            user_id = message.chat.id
            custom_lists = (
                session.query(schema.UserCollection.status)
                .join(schema.User, schema.User.id == schema.UserCollection.user_id)
                .filter(schema.User.telegram_id == user_id)
                .filter(schema.UserCollection.status.notin_(['watched', 'planned']))
                .distinct().all()
            )
            for c_list in custom_lists:
                list_name = c_list[0]
                markup.row(types.InlineKeyboardButton(f"📁 {list_name}", callback_data=f"collection|{list_name}|1"))
        finally:
            session.close()
        # ----------------------------------

        # ---> VISUAL SEPARATOR FOR FUNCTIONS <---
        markup.row(types.InlineKeyboardButton("⸻ System Options ⸻", callback_data="ignore"))

        markup.row(
            types.InlineKeyboardButton("[ ❓ Help ]", callback_data="library_help"),
            types.InlineKeyboardButton("[ 🏠 Main Menu ]", callback_data="main_menu"),
        )
        self._bot.send_message(message.chat.id, "📚 <b>Your Movie Library</b>\nBrowse your saved lists below:", reply_markup=markup, parse_mode="HTML")

    def edit_movie_collection(self, call, user_id: int, status: str | None, heading: str, page: int) -> None:
        """Fetches the user's library and STRICTLY sorts it by Collection and Genre."""
        session = SessionLocal()
        try:
            query = (
                session.query(schema.MovieCache, schema.UserCollection.status)
                .join(schema.UserCollection, schema.MovieCache.id == schema.UserCollection.movie_id)
                .join(schema.User, schema.User.id == schema.UserCollection.user_id)
                .filter(schema.User.telegram_id == user_id)
            )

            base_status = status
            if status and ":GENRE:" in status:
                base_status, genre_name = status.split(":GENRE:", 1)
                query = query.filter(schema.MovieCache.genres.like(f"%{genre_name}%"))
                
            if base_status and base_status.startswith("C:"):
                collection_name = base_status.split(":", 1)[1]
                query = query.filter(schema.MovieCache.collection_name.startswith(collection_name))
            elif base_status and base_status != "all":
                query = query.filter(schema.UserCollection.status == base_status)

            query = query.order_by(
                schema.MovieCache.collection_name.asc(),
                schema.MovieCache.genres.asc(),
                schema.MovieCache.title_en.asc()
            )

            data = query.all()
            items = []
            for m, s in data:
                movie_title = m.title_en or m.title_ru or "Untitled"
                items.append({
                    'movie_id': m.id,
                    'title': movie_title,
                    'status': s,
                    'collection': m.collection_name,
                    'genres': m.genres
                })
        finally:
            session.close()
            
        if not items:
            self._bot.answer_callback_query(call.id, "No movies found.")
            return

        # ---> FIXED: We now pass the user_id into the page builder so it can calculate the return page! <---
        text, markup = self.build_collection_page(items, heading, status, page=page, user_id=user_id)
        try:
            self._bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=markup)
            self._bot.answer_callback_query(call.id)
        except Exception:
            self._bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    def build_collection_page(self, items: list[dict], heading: str, status: str | None, page: int = 1, user_id: int = None): # type: ignore
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
            
            raw_label = item['title']
            if status is None or (status and status.startswith("GENRE:")):
                if item['status'] == "watched": status_icon = "✅"
                elif item['status'] == "planned": status_icon = "🎬"
                else: status_icon = "📁"
                raw_label = f"{status_icon} {raw_label}"
                
            label = f"▶ {raw_label}"[:60]
            markup.row(types.InlineKeyboardButton(label, callback_data=f"movie_action|open|{status_key}|{current_page}|{item['movie_id']}"))
            
        markup.row(types.InlineKeyboardButton("⸻ Actions ⸻", callback_data="ignore"))

        nav_buttons = []
        status_key = "all" if status is None else status
        if current_page > 1:
            nav_buttons.append(types.InlineKeyboardButton("[ ◀ Prev ]", callback_data=f"collection|{status_key}|{current_page - 1}"))
        if current_page < total_pages:
            nav_buttons.append(types.InlineKeyboardButton("[ Next ▶ ]", callback_data=f"collection|{status_key}|{current_page + 1}"))
        
        if nav_buttons:
            markup.row(*nav_buttons)
            
        # ---> ADDED: Magically calculate the exact page of the Collections menu this belongs to! <---
        back_page = 1
        if status and status.startswith("C:") and user_id:
            target_col = status.split(":", 1)[1]
            session = SessionLocal()
            try:
                collections = (
                    session.query(schema.MovieCache.collection_name)
                    .join(schema.UserCollection, schema.MovieCache.id == schema.UserCollection.movie_id)
                    .join(schema.User, schema.User.id == schema.UserCollection.user_id)
                    .filter(schema.User.telegram_id == user_id)
                    .filter(schema.MovieCache.collection_name.isnot(None))
                    .distinct()
                    .all()
                )
                all_cols = sorted([c[0] for c in collections if c[0]])
                for idx, c_name in enumerate(all_cols):
                    if c_name.startswith(target_col):
                        back_page = (idx // 10) + 1  # 10 is the PAGE_SIZE for the collections menu
                        break
            finally:
                session.close()
                
        if status is None or not status.startswith("C:"):
            markup.row(types.InlineKeyboardButton("[ 🔍 Filter this list by Genre ]", callback_data=f"filter_menu|{status_key}"))
        else:
            # ---> FIXED: Return to the exact page calculated above! <---
            markup.row(types.InlineKeyboardButton("[ 🔙 Back to Collections ]", callback_data=f"lib_cols_page|{back_page}"))
            
        is_custom = status and status not in ["watched", "planned", "all"] and not status.startswith("C:") and ":GENRE:" not in status and not status.startswith("GENRE:")
        if is_custom:
            markup.row(types.InlineKeyboardButton(f"[ 🗑️ Delete '{status}' List ]", callback_data=f"del_list|{status}"))

        markup.row(types.InlineKeyboardButton("[ 📚 Library ]", callback_data="library_menu"), types.InlineKeyboardButton("[ 🏠 Main Menu ]", callback_data="main_menu"))
        return "\n".join(body), markup
    
    def show_filter_menu(self, call, user_id: int, status: str) -> None:
        """Shows a genre filter menu strictly for the current list being viewed."""
        session = SessionLocal()
        try:
            query = (
                session.query(schema.MovieCache.genres)
                .join(schema.UserCollection, schema.MovieCache.id == schema.UserCollection.movie_id)
                .join(schema.User, schema.User.id == schema.UserCollection.user_id)
                .filter(schema.User.telegram_id == user_id)
            )
            
            base_status = status
            if status and ":GENRE:" in status:
                base_status = status.split(":GENRE:", 1)[0]
                
            if base_status and base_status.startswith("C:"):
                collection_name = base_status.split(":", 1)[1]
                query = query.filter(schema.MovieCache.collection_name.startswith(collection_name))
            elif base_status and base_status != "all":
                query = query.filter(schema.UserCollection.status == base_status)

            genres = query.distinct().all()
            unique_genres = set()
            for g in genres:
                if g[0]:
                    for genre in g[0].split(", "):
                        unique_genres.add(genre)
                        
            if not unique_genres:
                self._bot.answer_callback_query(call.id, "No categories to filter by yet.")
                return

            markup = types.InlineKeyboardMarkup()
            for genre in sorted(unique_genres):
                markup.row(types.InlineKeyboardButton(f"📂 {genre}", callback_data=f"collection|{status}:GENRE:{genre}|1"))
                
            markup.row(types.InlineKeyboardButton("⸻ Actions ⸻", callback_data="ignore"))
            markup.row(types.InlineKeyboardButton("[ 🔙 Back to List ]", callback_data=f"collection|{status}|1"))
            
            heading = self.collection_heading(status)
            self._bot.edit_message_text(f"<b>Filter {html.escape(heading)}</b>\nChoose a category:", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=markup)
        finally:
            session.close()

    def show_tmdb_collections_menu(self, call, page: int = 1) -> None:
        """Shows unique TMDB collections based on the user's library with Pagination."""
        session = SessionLocal()
        try:
            user_id = call.message.chat.id
            collections = (
                session.query(schema.MovieCache.collection_name)
                .join(schema.UserCollection, schema.MovieCache.id == schema.UserCollection.movie_id)
                .join(schema.User, schema.User.id == schema.UserCollection.user_id)
                .filter(schema.User.telegram_id == user_id)
                .filter(schema.MovieCache.collection_name.isnot(None))
                .distinct()
                .all()
            )
            
            all_collections = sorted([c[0] for c in collections if c[0]])
            
            if not all_collections:
                self._bot.answer_callback_query(call.id, "No collections found in your library yet!")
                return

            PAGE_SIZE = 10
            total_pages = max(1, math.ceil(len(all_collections) / PAGE_SIZE))
            current_page = min(max(1, page), total_pages)
            start = (current_page - 1) * PAGE_SIZE
            end = start + PAGE_SIZE
            page_collections = all_collections[start:end]

            markup = types.InlineKeyboardMarkup()
            for c in page_collections:
                safe_c = c[:20] 
                markup.row(types.InlineKeyboardButton(f"📦 {c}", callback_data=f"collection|C:{safe_c}|1"))
                
            markup.row(types.InlineKeyboardButton("⸻ Actions ⸻", callback_data="ignore"))

            nav_buttons = []
            if current_page > 1:
                nav_buttons.append(types.InlineKeyboardButton("[ ◀ Prev ]", callback_data=f"lib_cols_page|{current_page - 1}"))
            if current_page < total_pages:
                nav_buttons.append(types.InlineKeyboardButton("[ Next ▶ ]", callback_data=f"lib_cols_page|{current_page + 1}"))
            
            if nav_buttons:
                markup.row(*nav_buttons)
                
            markup.row(types.InlineKeyboardButton("[ 📚 Back to Library ]", callback_data="library_menu"))

            text = f"📦 <b>Your Collections</b>\n<i>Page {current_page}/{total_pages}</i>\nChoose a Collection to browse:"
            self._bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=markup)
            self._bot.answer_callback_query(call.id)
        finally:
            session.close()

    def collection_heading(self, status: str | None) -> str:
        if status and ":GENRE:" in status:
            base, genre = status.split(":GENRE:", 1)
            base_name = "All movies"
            if base == "watched": base_name = "Watched"
            elif base == "planned": base_name = "To-watch"
            elif base.startswith("C:"): 
                base_name = base.split(":", 1)[1]
                if len(base_name) == 20: base_name += "..."
            elif base != "all": base_name = base.capitalize()
            return f"{base_name} ➔ {genre}"
        
        if status and status.startswith("C:"):
            name = status.split(':', 1)[1]
            return f"{name}..." if len(name) == 20 else f"{name}"
            
        if status == "watched": return "Your watched movies"
        if status == "planned": return "Your to-watch movies"
        if status is None or status == "all": return "All your movies"
        if status and status.startswith("GENRE:"): return f"Genre: {status.split(':', 1)[1]}"
        return f"Collection: {status}"