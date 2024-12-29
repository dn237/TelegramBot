# Import necessary libraries
import telebot  # Used for interacting with the Telegram Bot API.
from telebot import types  # Necessary for creating custom keyboards and interactive buttons.
import tmdbsimple as tmdb  # Used to access The Movie Database (TMDB) API easily.
import random  # Used for generating random selections.
import requests  # Used for making HTTP requests.
import logging  # Used for logging messages and errors.
import json  # Used for JSON data handling.
from functools import lru_cache  # Used to cache results of function calls.

###HEEEEEEEEEEEEEEEEELOOOOLLLLLOL

# Set up basic configuration for logging to help with debugging.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set API keys for TMDB and configure the Telegram bot with a token.
tmdb.API_KEY = 'f95282a62bc8ad0d06f78ce91156b997'
bot = telebot.TeleBot('6715626173:AAE8b7M8rOgG3ihPurA2IRe5ibU6khypVzs')

# Function to load user preferences from a JSON file or create a new one if it doesn't exist.
def load_preferences():
    try:
        with open('user_preferences.json', 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        logger.info("User preferences file not found, creating new one.")
        return {}

# Function to save user preferences to a JSON file.
def save_preferences(preferences):
    with open('user_preferences.json', 'w') as file:
        json.dump(preferences, file, indent=4)

# Load user preferences on startup.
user_preferences = load_preferences()

# Command handler to start interaction with the bot
@bot.message_handler(commands=['start'])
def start(message):
    try:
        user_id = message.chat.id
        initialize_user_preferences(user_id)  # Initialize preferences when the chat starts
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn1 = types.KeyboardButton('Pick a random movie')
        btn2 = types.KeyboardButton('Select a movie by genre')
        btn3 = types.KeyboardButton('Display a list of available commands')
        markup.row(btn1, btn2, btn3)
        bot.send_message(message.chat.id, f'Hi, {message.from_user.first_name}! How can I help you today?', reply_markup=markup)
    except Exception as e:
        logger.error("An error occurred: %s", str(e))
        bot.send_message(message.chat.id, "Sorry, I'm unable to start at the moment. Please try again later.")

# Command handler to start the search for similar movies
@bot.message_handler(commands=['recommend_movies'])
def recommend_movies(message):
    logger.info("Recommend movies command received from user %s.", message.chat.id)
    sent_msg = bot.send_message(message.chat.id, "Please enter the name of the movie:")
    bot.register_next_step_handler(sent_msg, process_movie_recommendation)

# Command handler to set user's genre preference
@bot.message_handler(commands=['set_genre_preference'])
def ask_for_user_preference(message):
    user_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    for genre_name in get_genres().keys():
        markup.add(types.KeyboardButton(genre_name))
    msg = bot.send_message(message.chat.id, "Choose your preferred genre:", reply_markup=markup)
    bot.register_next_step_handler(msg, set_genre_preference)

@bot.message_handler(commands=['clear_preferences'])
def clear_preferences(message):
    user_id = message.chat.id
    user_preferences[user_id] = {'watched': []}
    save_preferences(user_preferences)
    bot.send_message(message.chat.id, "Your preferences have been reset.")


@lru_cache(maxsize=1)
def get_genres():
    try:
        response = tmdb.Genres().movie_list()
        genres = {genre['name']: genre['id'] for genre in response['genres']}
        logger.info(f"Genres fetched: {genres}")
        return genres
    except Exception as e:
        logger.error("Failed to fetch genres: %s", str(e))
        return {}


#error simulating
#@lru_cache(maxsize=1)
#def get_genres():
#    raise Exception("Simulated API error: Unable to fetch genres.")

@lru_cache(maxsize=100)
def cached_movie_search(genre_id, page):
    try:
        response = tmdb.Discover().movie(with_genres=str(genre_id), page=page)
        return response['results']
    except Exception as e:
        logger.error("Error fetching movies by genre: %s", e)
        return []

def search_movies_by_genre(genre_id, user_id, max_pages=3):
    all_movies = []
    for page in range(1, max_pages+1):
        movies = cached_movie_search(genre_id, page)
        all_movies.extend(movies)
    watched_movies = user_preferences.get(user_id, {}).get('watched', [])
    return [movie for movie in all_movies if movie['id'] not in watched_movies]


def is_valid_genre_id(genre_id):
    genres = get_genres()
    return genre_id.isdigit() and int(genre_id) in genres.values()


def set_user_genre_preference(user_id, genre_id, call):
    if is_valid_genre_id(genre_id):
        user_preferences[user_id]['genre'] = int(genre_id)
        save_preferences(user_preferences)
        bot.send_message(call.message.chat.id, f"Genre preference set to {get_genres()[int(genre_id)]}.")
        start(call.message)
    else:
        bot.send_message(call.message.chat.id, "Invalid genre selected.")

def show_another_movie_from_genre(call, genre_id, user_id):
    if is_valid_genre_id(genre_id):
        movies = search_movies_by_genre(int(genre_id), user_id)
        if movies:
            random_movie = random.choice(movies)
            send_movie_details(call.message, random_movie, int(genre_id))
        else:
            bot.send_message(call.message.chat.id, "No more unwatched movies available in this genre.")
    else:
        bot.send_message(call.message.chat.id, "Invalid genre selected.")


def mark_movie_as_watched(call, movie_id, user_id):
    user_preferences[user_id].setdefault('watched', []).append(movie_id)
    save_preferences(user_preferences)
    bot.answer_callback_query(call.id, "Movie marked as watched.")

def delete_message(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id, "Message deleted.")

def cancel_operation(call):
    bot.answer_callback_query(call.id, "Operation cancelled.")


# Function to get the URL of a movie's poster
def get_movie_poster_path(movie):
    poster_path = movie.get('poster_path')
    if poster_path:
        return f"https://image.tmdb.org/t/p/w500{poster_path}"
    return None
    
# Function to get a movie's trailer URL from YouTube
def get_movie_trailer(movie_id):
    try:
        url = f'https://api.themoviedb.org/3/movie/{movie_id}/videos?api_key={tmdb.API_KEY}'
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            for result in results:
                if result.get('type') == 'Trailer' and result.get('site') == 'YouTube':
                    logger.info("Trailer found for movie %s.", movie_id)
                    key = result.get('key')
                    return f'https://www.youtube.com/watch?v={key}'
        return None
    except Exception as e:
        logger.error("Failed to fetch movie trailer for ID %s: %s", movie_id, e)
        return None

# Function to get the names of the main cast members
def get_cast(movie_id):
    try:
        response = tmdb.Movies(movie_id).credits()
        return ", ".join(actor['name'] for actor in response.get('cast', [])[:5])
    except Exception as e:
        logger.error("Failed to fetch cast: %s", str(e))
        return "Cast details not available"

#Fetches the production country for a given movie from TMDB.
def get_production_country(movie_id):
    try:
        info = tmdb.Movies(movie_id).info()
        countries = info.get('production_countries', [])
        return ', '.join(country['name'] for country in countries) if countries else 'Unknown'
    except Exception as e:
        logger.error("Failed to fetch production countries: %s", str(e))
        return "Unknown"
    
# Ensure user preferences are correctly initialized
def initialize_user_preferences(user_id):
    # Check if user_id exists in user_preferences, if not initialize it
    if user_id not in user_preferences:
        user_preferences[user_id] = {'watched': [], 'genre': None}
    # No need to save preferences here, it should be done after modifications

# Function to search for a movie by name and return its ID
def find_movie_by_name(movie_name):
    try:
        search = tmdb.Search()
        response = search.movie(query=movie_name)
        if response['results']:
            return response['results'][0]['id']
    except Exception as e:
        logger.error(f"Failed to find movie by name '{movie_name}': {str(e)}")
    return None

# Function to get recommended movies based on a movie ID
def get_recommended_movies(movie_id):
    try:
        movie = tmdb.Movies(movie_id)
        recommendations = movie.recommendations()
        return recommendations['results']
    except Exception as e:
        logger.error(f"Failed to get recommendations for movie ID {movie_id}: {str(e)}")
        return []


# Process the movie recommendation
def process_movie_recommendation(message):
    logger.info("Processing movie recommendation for: %s", message.text)
    movie_id = find_movie_by_name(message.text)
    if movie_id:
        recommended_movies = get_recommended_movies(movie_id)
        response_text = "Recommended Movies:\n"
        for movie in recommended_movies:
            response_text += f"{movie['title']}\n"
        bot.send_message(message.chat.id, response_text)
    else:
        logger.warning("Movie not found for: %s", message.text)
        bot.send_message(message.chat.id, "Movie not found.")


# Function to convert genre IDs to names using a dictionary
def get_genre_names_by_ids(genre_ids):
    genres_dict = get_genres()
    # Invert the dictionary to map IDs to genre names
    id_to_genre = {v: k for k, v in genres_dict.items()}
    # Get genre names by their IDs, fallback to "Unknown genre" if needed
    genre_names = [id_to_genre.get(genre_id, 'Unknown genre') for genre_id in genre_ids]
    return ', '.join(genre_names)

# Function to set user's genre preference
def set_genre_preference(message):
    user_id = message.chat.id
    user_preferences[user_id] = {'genre': message.text}  # Set the genre preference for the user
    save_preferences(user_preferences)  # Save changes immediately
    bot.send_message(message.chat.id, f"Genre preference set to {message.text}.")
    start(message)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    if message.text.lower() == 'pick a random movie':
        genre_preference = user_preferences.get(user_id, {}).get('genre')
        genres_dict = get_genres()
        genre_id = genres_dict.get(genre_preference) if genre_preference else random.choice(list(genres_dict.values()))
        movies = search_movies_by_genre(genre_id, user_id)
        if movies:
            random_movie = random.choice(movies)
            send_movie_details(message, random_movie, genre_id)  # Include genre_id here
        else:
            bot.send_message(message.chat.id, "Sorry, all movies in this genre have been watched. Resetting your watched list.")
            user_preferences[user_id]['watched'] = []  # Reset watched list if all have been shown
    elif message.text.lower() == 'select a movie by genre':
        select_movie_by_genre(message)
    elif message.text.lower() == 'display a list of available commands':
        commands = "/start - Restart the bot.\n/set_genre_preference - Set genre preference.\n/recommend_movies - Get a list of recommended movies based on a specific movie.\n/clear_preferences - Reset preferences" 
        bot.send_message(message.chat.id, commands)

# Function to display inline keyboard for selecting movie genres
def select_movie_by_genre(message):
    genres_dict = get_genres()
    markup = types.InlineKeyboardMarkup()
    for genre_name, genre_id in genres_dict.items():
        markup.add(types.InlineKeyboardButton(genre_name, callback_data=f'genre_{genre_id}'))
    bot.send_message(message.chat.id, "Please select a genre:", reply_markup=markup)

# Function to send movie details and options to the user
def send_movie_details(message, movie, genre_id):
    user_id = message.chat.id
    initialize_user_preferences(user_id)  # Ensure preferences are initialized
    if 'watched' not in user_preferences[user_id]:
        user_preferences[user_id]['watched'] = []  # Ensure 'watched' key exists
    user_preferences[user_id]['watched'].append(movie['id'])
    poster_url = get_movie_poster_path(movie)
    trailer = get_movie_trailer(movie['id'])
    production_countries = get_production_country(movie['id'])
    cast_names = get_cast(movie['id'])
    genre_names = get_genre_names_by_ids(movie.get('genre_ids', []))
    rating = movie.get('vote_average', 'N/A')
    release_year = movie.get('release_date', 'Unknown')[:4]
    movie_info = (f"<b>🎬 Title:</b> {movie['title']}\n"
                  f"<b>🍿 Overview:</b> {movie.get('overview', 'No description available.')}\n"
                  f"<b>⭐ Rating:</b> {rating}\n"
                  f"<b>📅 Year:</b> {release_year}\n"
                  f"<b>🎭 Genre:</b> {genre_names}\n"
                  f"<b>🌍 Country:</b> {production_countries}\n"
                  f"<b>👩🏼 Cast:</b> {cast_names}\n"
                  f"<b>📽️ Trailer:</b> {trailer if trailer else 'No trailer available.'}\n")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Watch another from this genre", callback_data=f"another_{genre_id}"))
    markup.add(types.InlineKeyboardButton("Get recommendations", callback_data=f"recommend_{movie['id']}"))  # Добавлено
    if poster_url:
        bot.send_photo(message.chat.id, photo=poster_url, caption=movie_info, parse_mode='HTML', reply_markup=markup)
    else:
        bot.send_message(message.chat.id, movie_info, parse_mode='HTML', reply_markup=markup)


# Handler for receiving media messages
@bot.message_handler(content_types=['photo', 'audio', 'video'])
def get_media(message):
    markup = types.InlineKeyboardMarkup()  # Creating a keyboard object
    markup.add(types.InlineKeyboardButton('Delete', callback_data='DELETE'))  # Adding a "Delete" button
    markup.add(types.InlineKeyboardButton("No", callback_data='NO'))  # Adding a "No" button
    bot.reply_to(message, "My creator, being the mad genius they are, thought it'd be hilarious to make me the detective of media-blindness. Elementary, my dear pixels! \nWould you like me to delete this?", reply_markup=markup)


# Handler for processing callback queries
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        user_id = call.message.chat.id
        # Processing genre selection
        if call.data.startswith('genre_'):
            genre_id = call.data.split('_')[1]
            movies = search_movies_by_genre(genre_id, user_id)
            if movies:
                random_movie = random.choice(movies)
                send_movie_details(call.message, random_movie, genre_id)
            else:
                bot.send_message(call.message.chat.id, "No more unwatched movies available in this genre.")
                start(call.message)  # send back to the start menu
        elif call.data.startswith('recommend_'):
            movie_id = call.data.split('_')[1]
            recommended_movies = get_recommended_movies(movie_id)
            if recommended_movies:
                response_text = "Recommended Movies:\n"
                for movie in recommended_movies:
                    response_text += f"{movie['title']}\n"
                bot.send_message(call.message.chat.id, response_text)
            else:
                bot.send_message(call.message.chat.id, "No recommendations available.")
        elif call.data.startswith('another_'):
            genre_id = call.data.split('_')[1]
            movies = search_movies_by_genre(genre_id, user_id)
            if movies:
                random_movie = random.choice(movies)
                send_movie_details(call.message, random_movie, genre_id)
            else:
                bot.answer_callback_query(call.id, "No more unwatched movies available in this genre.")
                start(call.message)  # send back to the start menu
        # Processing request to pick another genre
        elif call.data == "pick_another_genre":
            select_movie_by_genre(call.message)
        # Returning to the main menu
        elif call.data == "main_menu":
            start(call.message)
        # Processing request to delete media message
        elif call.data == 'DELETE':
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id - 1)
                bot.delete_message(call.message.chat.id, call.message.message_id)
                bot.answer_callback_query(call.id, "Media deleted.")
            except Exception as e:
                bot.answer_callback_query(call.id, "Error: Can't delete this message.")
        # Cancelling deletion of media message
        elif call.data == 'NO':
            bot.answer_callback_query(call.id, "Operation cancelled.")
    except Exception as e:
        logger.error("An error occurred: %s", str(e))
        bot.answer_callback_query(call.id, "Sorry, I'm unable to process your request at the moment.")

# Start polling for updates
bot.polling(none_stop=True)
