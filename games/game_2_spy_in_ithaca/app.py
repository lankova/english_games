from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import os

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'my_secret_key'

socketio = SocketIO(app, cors_allowed_origins="*")

# Store all active game rooms
# Structure: { room_code: { 'players': {'name': score}, 'game_started': False } }
rooms = {}


# -------------------- ROUTES (Page URLs) --------------------

@app.route('/spy-in-ithaca/rules')
def game2_rules():
    return render_template('spy_in_ithaca/rules.html')

@app.route('/spy-in-ithaca/game')
def spy_in_ithaca_game():
    return render_template('spy_in_ithaca/game.html')

@app.route('/spy-in-ithaca/<room_code>')
def spy_in_ithaca_room(room_code):
    return render_template('spy_in_ithaca/game.html')

if __name__ == '__main__':
    # Use environment variable to control debug mode: True locally, False in production
    debug_mode = os.environ.get('FLASK_DEBUG', 'True') == 'True'
    socketio.run(app, debug=debug_mode, host='0.0.0.0', port=5001)

