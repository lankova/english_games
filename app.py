from gevent import monkey
monkey.patch_all()

from flask import Flask, render_template, request, url_for as flask_url_for
from flask_socketio import SocketIO
import os
from shared.database import save_room_to_db
from shared.utils import generate_room_code

# Initialize Flask app
app = Flask(__name__)
# TODO: move to environment variable
app.config['SECRET_KEY'] = 'my_secret_key'

socketio = SocketIO(app, cors_allowed_origins=[
    "http://127.0.0.1:5000",
    "https://lankova.tech",
    "https://www.lankova.tech",
    "http://lankova.tech",
    "http://www.lankova.tech",
    "https://english-games.ru",
    "https://www.english-games.ru",
    "http://english-games.ru",
    "http://www.english-games.ru",
])

rooms_game1 = {}
rooms_game2 = {}


@app.context_processor
def override_url_for():
    """Append file mtime to static URLs so browsers fetch new CSS/JS after deploy."""

    def dated_url_for(endpoint, **values):
        if endpoint == "static":
            filename = values.get("filename")
            if filename and app.static_folder:
                file_path = os.path.join(app.static_folder, filename)
                if os.path.isfile(file_path):
                    values["v"] = int(os.path.getmtime(file_path))
        return flask_url_for(endpoint, **values)

    return dict(url_for=dated_url_for)


@app.after_request
def set_cache_headers(response):
    """
    HTML is never long-cached (so players pick up new ?v= static URLs).
    Versioned /static/ files can be cached; API payloads stay fresh.
    """
    content_type = response.content_type or ""
    if "text/html" in content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.route('/')
def index():
    # Home page with game selection
    return render_template('index.html')

# Register Game 1 - Describe & Guess
from games.game_1_describe_and_guess.routes import register_routes as register_routes_g1
register_routes_g1(app)

from games.game_1_describe_and_guess.socket_handlers import register_handlers as register_handlers_g1
register_handlers_g1(socketio, rooms_game1, save_room_to_db, generate_room_code)

# Register Game 2 - Spy in Ithaca
from games.game_2_spy_in_ithaca.routes import register_routes as register_routes_g2
register_routes_g2(app)

from games.game_2_spy_in_ithaca.socket_handlers import register_handlers as register_handlers_g2
register_handlers_g2(socketio, rooms_game2, save_room_to_db, generate_room_code)

# ------ RUN SERVER ------

if __name__ == '__main__':
    # environment variable is used for debug mode control: True locally, False in production
    debug_mode = os.environ.get('FLASK_DEBUG', 'True') == 'True'
    socketio.run(app, debug=False, host='0.0.0.0', port=5000)

