# 🎬 Movie Tracker & Recommender Telegram Bot

A highly advanced, personalized Telegram bot that delivers movie recommendations powered by [The Movie Database (TMDB)](https://www.themoviedb.org/) API and stores your entire library in a local SQLite database. 

With a its UI, dynamic library sorting, automatic franchise grouping, and an intelligent feedback system, this bot adapts to your exact tastes over time.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Telegram Bot API](https://img.shields.io/badge/Telegram%20Bot%20API-pyTelegramBotAPI-26A5E4?logo=telegram&logoColor=white)
![TMDB](https://img.shields.io/badge/TMDB-API-01D277?logo=themoviedatabase&logoColor=white)

---

## ✨ Features

*   **📦 Automatic Franchise Grouping**
    Movies saved to your library are automatically scanned and grouped into their official TMDB Collections (e.g., *The Harry Potter Collection*, *The Avengers Collection*).
*   **📁 Custom Playlists**
    Create and manage your own custom collections dynamically (e.g., "Halloween Movies," "Date Night") right from the movie card. You can safely delete them anytime.
*   **🧠 Intelligent Taste Profile**
    Rate suggestions with Like/Dislike. The bot actively learns your specific genre preferences and mathematically ranks future recommendations to suit your taste.
*   **🎛️ Paginated "Control Panel" UI**
    Navigate massive libraries easily with a sleek, paginated inline keyboard UI that keeps your chat history clean and organized.
*   **🌐 Advanced Quality & Language Filters**
    Set a minimum TMDB rating (0–10), minimum release year, and block specific audio languages so you only get high-quality recommendations you actually want to watch.
*   **🗄️ SQLite Persistence & Caching**
    User preferences, watched history, and library metadata are stored locally in `telegrambot.db`. The bot caches API requests to prevent rate-limiting.
*   **🍿 Rich Movie Cards**
    Every recommendation pulls the official poster, overview, release year, genre, country, cast, and a direct YouTube trailer link.

---

## 🏗️ Architecture

The codebase follows a clean, **service-oriented** design:

*   **`main.py` & `config.py`**: Centralized configuration and entry point.
*   **`bot/movie_bot.py`**: The core router. Handles all Telegram commands, free-text matching, and callback dispatching.
*   **`handlers/`**: Dedicated UI logic. `library.py` handles the complex paginated menus and dynamic sorting, while `movie_cards.py` formats the media output.
*   **`services/tmdb_service.py`**: Wraps the TMDB API with intelligent in-memory caching.
*   **`models/`**: SQLAlchemy ORM models (`schema.py`) and the DB-backed repository (`user_preferences.py`) for handling all CRUD operations.

---

## 🚀 Getting Started

### Prerequisites
*   Python 3.10+
*   A [Telegram Bot Token](https://core.telegram.org/bots#how-do-i-create-a-bot) (via BotFather)
*   A [TMDB API Key](https://developer.themoviedb.org/docs/getting-started) (free account)

### Installation

```bash
# Clone the repository
git clone [https://github.com/yourusername/TelegramBot.git](https://github.com/yourusername/TelegramBot.git)
cd TelegramBot

# Create and activate a virtual environment
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt