# app.py - Main Flask application for English Games

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import string
import secrets # for secure token generation (for the host)
import time
import threading

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'my_secret_key'

socketio = SocketIO(app, cors_allowed_origins="*")

# Store all active game rooms
# Structure: { room_code: { 'players': {'name': score}, 'game_started': False } }
rooms = {}


def generate_room_code():
    """Generate random 4-character room code (letters + digits)"""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choices(characters, k=4))


# -------------------- ROUTES (Page URLs) --------------------

@app.route('/')
def index():
    """Home page with game selection"""
    return render_template('index.html')


@app.route('/game1/rules')
def game1_rules():
    """Rules page for Describe & Guess game"""
    return render_template('game_1_describe_and_guess/rules.html')

@app.route('/game1/game')
def game1_game():
    return render_template('game_1_describe_and_guess/game.html')

@app.route('/describe-and-guess/<room_code>')
def describe_and_guess(room_code):
    return render_template('game_1_describe_and_guess/game.html')

# -------------------- WEBSOCKET EVENTS --------------------

@socketio.on('create_room')
def handle_create_room(data):
    """
    Create a new game room.
    Expects: { 'name': player_name }
    """
    player_name = data.get('name')
    room_code = generate_room_code()
    sid = request.sid  # unique session ID for the host
    host_token = secrets.token_hex(16) #secure random token

    # Initialize room with host as first player
    rooms[room_code] = {
        'host_sid': sid,
        'host_name': player_name, # Who created the room
        'host_token': host_token,
        'players': {player_name: 0}, # Host is the first player
        'game_started': False,
        'round_active': False,
        'explainer': None,
        'round_start_time': None,
        'duration': 90, #round duration is 90 seconds
        'timer_thread': None  # background thread for countdown
    }

    # Add player to SocketIO room
    join_room(room_code)

    # Notify the creator that they are the host
    emit('room_created', {
        'room_code': room_code,
        'is_host': True,
        'host_token': host_token,
        'players': list(rooms[room_code]['players'].keys())
    }, to=room_code)


@socketio.on('join_room')
def handle_join_room(data):
    """
    Join existing game room.
    Expects: { 'name': player_name, 'room_code': room_code }
    """
    player_name = data.get('name')
    room_code = data.get('room_code')
    client_host_token = data.get('host_token')

    # Check if room exists
    if room_code not in rooms:
        emit('error', {'message': 'Room not found'})
        return

    room_data = rooms[room_code]

    # Host reconnects with valid token
    if (room_data.get('host_name') == player_name and
        room_data.get('host_sid') is None and
        client_host_token is not None and
        client_host_token == room_data.get('host_token')):

            room_data['host_sid'] = request.sid
            join_room(room_code)
            emit('room_created', {
                'room_code': room_code,
                'is_host': True,
                'host_token': room_data.get('host_token'),
                'players': list(room_data['players'].keys())
            }, to=request.sid)
            return

    # A regular player joins (or the host joins for the first time)
    if player_name not in room_data['players']:
        room_data['players'][player_name] = 0
    join_room(room_code)

    emit('player_joined', {
        'players': list(room_data['players'].keys())
    }, to=room_code)

@socketio.on('start_game')
def handle_start_game(data):
    """
    Start the game (only host can do this).
    Expects: { 'room_code': room_code }
    """
    room_code = data.get('room_code')
    sid = request.sid

    if room_code not in rooms:
        emit('error', {'message': 'Room not found'})
        return

    # Only the host can start the game
    if sid != rooms[room_code]['host_sid']:
        emit('error', {'message': 'Only the host can start the game'})
        return

    rooms[room_code]['game_started'] = True
    emit('game_started', to=room_code)

@socketio.on('become_explainer')
def handle_become_explainer(data):
    room_code = data.get('room_code')
    player_name = data.get('player_name')

    if room_code not in rooms:
        return
    room_data = rooms[room_code]
    if room_data['round_active'] or room_data['explainer'] is not None:
        return

    room_data['explainer'] = player_name

    emit('round_started', {
        'explainer': player_name,
        'duration': room_data['duration']
    }, to=room_code)

def start_round_timer(room_code):
    if room_code not in rooms:
        return
    duration = rooms[room_code]['duration']
    rooms[room_code]['round_start_time'] = time.time()

    def timer_task():
        time_left = duration
        while time_left >= 0 and rooms[room_code]['round_active']:
            socketio.emit('timer_update', {'time_left': time_left}, to=room_code)
            time.sleep(1)
            time_left -= 1
        if rooms[room_code]['round_active']:
            rooms[room_code]['round_active'] = False
            rooms[room_code]['explainer'] = None
            socketio.emit('round_timeout', to=room_code)


    old = rooms[room_code].get('timer_thread')
    if old and old.is_alive():
        rooms[room_code]['round_active'] = False

    thread = threading.Thread(target=timer_task)
    thread.daemon = True # Thread will stop automatically when the main program ends
    rooms[room_code]['timer_thread'] = thread
    thread.start()

@socketio.on('start_timer')
def handle_start_timer(data):
    room_code = data.get('room_code')
    if room_code not in rooms:
        return
    room_data = rooms[room_code]
    if not room_data['round_active'] and room_data['explainer'] is not None:
        room_data['round_active'] = True
        # Send initial timer value immediately so non-explainers see it
        emit('timer_update', {'time_left': room_data['duration']}, to=room_code)
        start_round_timer(room_code)

@socketio.on('round_end')
def handle_round_end(data):
    """Handle end of round: update scores and send scoreboard"""
    room_code = data.get('room_code')
    player = data.get('player')
    round_score = data.get('round_score')

    if room_code not in rooms:
        return
    room_data = rooms[room_code]
    if not room_data['round_active']:
        return

    room_data['round_active'] = False
    room_data['explainer'] = None

    # Update player's total score
    if player in room_data['players']:
        room_data['players'][player] += round_score

    scoreboard = [{'name': name, 'display': str(total)} for name, total in room_data['players'].items()]
    emit('scoreboard_update', {'scoreboard': scoreboard}, to=room_code)

@socketio.on('next_round')
def handle_next_round(data):
    room_code = data.get('room_code')
    if room_code not in rooms:
        return
    rooms[room_code]['round_active'] = False
    rooms[room_code]['explainer'] = None
    emit('next_round_ready', to=room_code)

# Check if a room exists before the player tries to join
@socketio.on('check_room')
def handle_check_room(data):
    """
    Verify room existence and send appropriate response.
    Expected input: { 'room_code': 'AB12' }
    """
    room_code = data.get('room_code')
    print(f"Check room: {room_code}, exists: {room_code in rooms}") #For debug only

    # If room doesn't exist, notify the player
    if room_code not in rooms:
        emit('error', {'message': 'Room not found'})
    else:
        # Room exists — confirm it so the player can proceed
        emit('room_exists', {'exists': True})

@socketio.on('disconnect')
def handle_disconnect():
    """
    Handle client disconnection.
    If the disconnected client was the host, we mark them as offline
    but keep the room alive so they can reconnect later.
    """
    sid = request.sid

    for room_code, room_data in rooms.items():
        # Check if the disconnected client was the host
        if sid == room_data.get('host_sid'):
            room_data['host_sid'] = None
            emit('host_disconnected', {
                'message': 'Host disconnected. Waiting for them to return...'
            }, to=room_code)
            return

@socketio.on('kick_player')
def handle_kick_player(data):
    room_code = data['room_code']
    player_name = data['player_name']
    if room_code in rooms and request.sid == rooms[room_code].get('host_sid'):
        if player_name in rooms[room_code]['players']:
            del rooms[room_code]['players'][player_name]
            emit('player_kicked', {'player': player_name}, to=room_code)


# -------------------- RUN SERVER --------------------

if __name__ == '__main__':
    # debug=True auto-restarts when code changes
    socketio.run(app, debug=True)