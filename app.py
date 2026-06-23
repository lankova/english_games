from flask import Flask, render_template, request
from flask_socketio import SocketIO
import os
from shared.database import init_db, save_room_to_db, load_rooms_from_db
from shared.utils import generate_room_code

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'my_secret_key'

socketio = SocketIO(app, cors_allowed_origins="*")

rooms_game1 = {}
rooms_game2 = {}


@app.route('/')
def index():
    """Home page with game selection"""
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
    # Use environment variable to control debug mode: True locally, False in production
    debug_mode = os.environ.get('FLASK_DEBUG', 'True') == 'True'
    socketio.run(app, debug=debug_mode, host='0.0.0.0', port=5000)

