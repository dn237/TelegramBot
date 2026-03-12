# 🎬 Movie Recommendation Telegram Bot

A Telegram bot that delivers personalized movie recommendations powered by [The Movie Database (TMDB)](https://www.themoviedb.org/) API. Users can discover films by genre, get title-based suggestions, and fine-tune results through a learning feedback system that adapts to their taste over time.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Telegram Bot API](https://img.shields.io/badge/Telegram%20Bot%20API-pyTelegramBotAPI-26A5E4?logo=telegram&logoColor=white)
![TMDB](https://img.shields.io/badge/TMDB-API-01D277?logo=themoviedatabase&logoColor=white)

---

## Features

- **Random Movie Picker** — Get a random movie suggestion filtered by your preferred genre, minimum rating, and release year.
- **Browse by Genre** — Choose from all TMDB genres via an inline keyboard and explore movies one at a time.
- **Title-Based Recommendations** — Enter any movie title and receive a list of similar films from TMDB.
- **Quality Filters** — Set a minimum TMDB rating (0–10) and minimum release year to control recommendation quality.
- **Like / Dislike Feedback** — Rate each suggestion; the bot learns your genre preferences and ranks future picks accordingly.
- **User Profile** — View your saved filters, feedback stats, and top liked/disliked genres at a glance.
- **Watched History** — Automatically tracks movies you've seen so you never get the same recommendation twice.
- **Rich Movie Cards** — Each recommendation includes poster, overview, rating, year, genre, country, cast, and a YouTube trailer link.

## Architecture

```
TelegramBot/
├── main.py                  # Entry point — wires config, services, and bot
├── config.py                # Centralised configuration (env vars + defaults)
├── bot/
│   └── movie_bot.py         # Telegram handlers, menus, callback routing
├── services/
│   └── tmdb_service.py      # TMDB API wrapper with in-memory caching
├── models/
│   └── user_preferences.py  # JSON-backed user state & feedback persistence
├── requirements.txt
├── Procfile                 # Heroku / PaaS deployment descriptor
└── user_preferences.json    # Auto-generated runtime data (git-ignored)
```

The codebase follows a **service-oriented** design with clear separation of concerns:

| Layer | Responsibility |
|-------|---------------|
| **Config** | Reads secrets from environment variables; no credentials in code. |
| **TMDBService** | Wraps the TMDB API — genre look-ups, movie discovery, cast/trailer fetching — with per-session caching. |
| **UserPreferencesManager** | Persists watched history, genre preference, quality filters, and like/dislike feedback to a JSON file. |
| **MovieBot** | Owns the Telegram bot instance; registers all command, text, and callback handlers; delegates business logic to the service and model layers. |

## Tech Stack

- **Language:** Python 3.10+
- **Telegram Framework:** [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI) (telebot)
- **Movie Data:** [TMDB API](https://developer.themoviedb.org/) via [tmdbsimple](https://github.com/celiao/tmdbsimple)
- **Environment Management:** python-dotenv
- **Deployment:** Heroku-ready (Procfile included)

## Getting Started

### Prerequisites

- Python 3.10 or higher
- A [Telegram Bot Token](https://core.telegram.org/bots#how-do-i-create-a-bot) (via BotFather)
- A [TMDB API Key](https://developer.themoviedb.org/docs/getting-started) (free account)

### Installation

```bash
# Clone the repository
git clone https://github.com/dn237/TelegramBot.git
cd TelegramBot

# Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TMDB_API_KEY=your_tmdb_api_key
```

### Run

```bash
python main.py
```

The bot starts long-polling and is ready to use in Telegram.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Launch the bot and display the main menu. |
| `/set_genre_preference` | Choose a preferred genre for random picks. |
| `/set_quality_preference` | Set minimum rating and release year filters. |
| `/my_profile` | View your saved preferences and taste profile. |
| `/recommend_movies` | Get recommendations based on a movie title. |
| `/clear_preferences` | Reset all watched history and preferences. |

## How the Recommendation Engine Works

1. **Genre Filtering** — Movies are fetched from TMDB's Discover endpoint for the selected genre across multiple pages.
2. **Quality Filtering** — Results are filtered by the user's minimum rating and release year thresholds.
3. **Watch Deduplication** — Previously seen movies are excluded automatically.
4. **Personalized Ranking** — Each candidate is scored using accumulated like/dislike genre weights. Movies whose genres align with the user's positive feedback are ranked higher, while disliked genres are penalized.
5. **Tie-Breaking** — Among equally scored movies, TMDB rating is used as a secondary signal, and final selection is randomized for variety.

## Deployment

The included `Procfile` makes the bot deployable to Heroku or any compatible PaaS:

```
worker: python main.py
```

Set `TELEGRAM_BOT_TOKEN` and `TMDB_API_KEY` as environment variables on your hosting platform.

## License

This project is open-source and available under the [MIT License](LICENSE).
