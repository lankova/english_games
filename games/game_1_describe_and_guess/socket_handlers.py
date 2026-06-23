import json
import os
import random
import secrets
import time
import threading
from flask import request
from flask_socketio import emit, join_room

# These will be set by register_handlers
rooms = None
save_room_to_db = None
generate_room_code = None

_WORDS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "static", "game_1_describe_and_guess", "data", "words.json"
)
_ALL_WORDS = None


def _load_all_words():
    global _ALL_WORDS
    if _ALL_WORDS is None:
        with open(_WORDS_PATH, "r", encoding="utf-8") as f:
            _ALL_WORDS = json.load(f)
    return _ALL_WORDS


def _init_word_pool(room_data):
    words = list(_load_all_words())
    random.shuffle(words)
    room_data["word_pool"] = words
    room_data["word_pool_index"] = 0


def _next_word(room_data):
    pool = room_data.get("word_pool")
    if not pool:
        _init_word_pool(room_data)
        pool = room_data["word_pool"]
    idx = room_data.get("word_pool_index", 0)
    if idx >= len(pool):
        return None
    word = pool[idx]
    room_data["word_pool_index"] = idx + 1
    return word


def register_handlers(socketio, rooms_ref, save_room_fn, generate_code_fn):
    """Register all SocketIO event handlers for Game 1."""
    global rooms, save_room_to_db, generate_room_code
    rooms = rooms_ref
    save_room_to_db = save_room_fn
    generate_room_code = generate_code_fn

    @socketio.on('create_room')
    def handle_create_room(data):
        player_name = data.get('name')
        room_code = generate_room_code()
        sid = request.sid
        host_token = secrets.token_hex(16)

        rooms[room_code] = {
            'host_sid': sid,
            'host_name': player_name,
            'host_token': host_token,
            'players': {player_name: 0},
            'game_started': False,
            'round_active': False,
            'explainer': None,
            'round_start_time': None,
            'duration': 90,
            'timer_thread': None
        }

        save_room_to_db(room_code, rooms)
        join_room(room_code)

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
        if player_name in room_data['players']:
            emit('error', {'message': 'This name is already taken. Please choose another.'})
            return

        if player_name not in room_data['players']:
            room_data['players'][player_name] = 0
        join_room(room_code)

        save_room_to_db(room_code, rooms)

        emit('player_joined', {
            'player': player_name,
            'players': list(room_data['players'].keys())
        }, to=room_code)

        # Send current game state to the newly joined player
        if room_data.get('game_started'):
            emit('game_started', to=request.sid)
            if room_data.get('round_active') and room_data.get('explainer'):
                # Round is live
                emit('round_started', {
                    'explainer': room_data['explainer'],
                    'duration': room_data['duration'],
                    'late_join': True
                }, to=request.sid)

            elif room_data.get('last_round'):
                # Round just finished
                scoreboard = [{'name': name, 'display': str(total)} for name, total in room_data['players'].items()]

                emit('scoreboard_update', {
                    'scoreboard': scoreboard,
                    'last_round': room_data['last_round']
                }, to=request.sid)

                emit('scoreboard_update', {
                    'scoreboard': scoreboard,
                    'last_round': room_data['last_round']
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
        rooms[room_code]['all_cards_done'] = False
        _init_word_pool(rooms[room_code])
        emit('game_started', to=room_code)
        save_room_to_db(room_code, rooms)

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
        room_data['round_active'] = True

        emit('round_started', {
            'explainer': player_name,
            'duration': room_data['duration']
        }, to=room_code)

        room_data.pop('last_round', None)

    @socketio.on('request_word')
    def handle_request_word(data):
        room_code = data.get('room_code')
        player_name = data.get('player_name')
        if room_code not in rooms:
            return {'word': None}
        room_data = rooms[room_code]
        if room_data.get('explainer') != player_name:
            return {'word': None}
        word = _next_word(room_data)
        if word is None:
            room_data['all_cards_done'] = True
        save_room_to_db(room_code, rooms)
        return {'word': word}

    def start_round_timer(room_code):
        if room_code not in rooms:
            return
        room = rooms[room_code]

        old = room.get('timer_thread')
        if old and old.is_alive():
            room['round_active'] = False
            time.sleep(0.2)

        room['round_active'] = True
        room['timer_paused'] = False

        def timer_task():
            while room.get('round_active') and room_code in rooms:
                if room.get('timer_paused'):
                    time.sleep(0.1)
                    continue

                time_left = room.get('timer_time_left', room['duration'])
                socketio.emit('timer_update', {'time_left': time_left}, to=room_code)
                if time_left <= 0:
                    break
                time.sleep(1)
                if not room.get('round_active'):
                    return
                room['timer_time_left'] = time_left - 1

            room['last_round'] = {
                'player': room['explainer'],
            }
            socketio.emit('round_timeout', to=room_code)

            scoreboard = [{'name': name, 'display': str(total)} for name, total in room['players'].items()]

            # Reset AFTER emitting
            room['round_active'] = False
            room['explainer'] = None

        thread = threading.Thread(target=timer_task)
        thread.daemon = True
        room['timer_thread'] = thread
        thread.start()

    @socketio.on('start_timer')
    def handle_start_timer(data):
        room_code = data.get('room_code')
        if room_code not in rooms:
            return
        room_data = rooms[room_code]
        room_data.pop('last_round', None)
        if room_data['explainer'] is not None:
            room_data['timer_time_left'] = room_data['duration']
            room_data['timer_paused'] = False
            emit('timer_update', {'time_left': room_data['timer_time_left']}, to=room_code)
            start_round_timer(room_code)


    @socketio.on('pause_timer')
    def handle_pause_timer(data):
        room_code = data.get('room_code')
        if room_code not in rooms:
            return
        room = rooms[room_code]
        time_left = data.get('time_left')
        if time_left is not None:
            try:
                room['timer_time_left'] = int(time_left)
            except (TypeError, ValueError):
                pass
        room['timer_paused'] = True

    @socketio.on('resume_timer')
    def handle_resume_timer(data):
        room_code = data.get('room_code')
        if room_code not in rooms:
            return
        room = rooms[room_code]
        if room.get('explainer') is None:
            return
        if room.get('timer_time_left', 0) <= 0:
            return
        room['timer_paused'] = False
        emit('timer_update', {'time_left': room['timer_time_left']}, to=room_code)

    @socketio.on('score_update')
    def handle_score_update(data):
        room_code = data.get('room_code')
        increment = data.get('increment', 0)

        if room_code not in rooms:
            return

        room_data = rooms[room_code]

        if 'round_score' not in room_data:
            room_data['round_score'] = 0
        room_data['round_score'] += increment

    @socketio.on('round_end')
    def handle_round_end(data):
        room_code = data.get('room_code')
        if room_code not in rooms:
            return

        room_data = rooms[room_code]
        if room_data.get('round_ended'):
            return
        room_data['round_ended'] = True

        player = data.get('player')
        round_score = data.get('round_score')
        client_score = data.get('round_score', 0)


        room_data = rooms[room_code]

        round_score = room_data.pop('round_score', client_score)

        # Update total score
        if player in room_data['players']:
            room_data['players'][player] += round_score

        # Store last round info - use the actual explainer from the room
        room_data['last_round'] = {
            'player': player,
            'score': round_score
        }

        # Build scoreboard
        scoreboard = [{'name': name, 'display': str(total)} for name, total in room_data['players'].items()]

        emit('scoreboard_update', {
            'scoreboard': scoreboard,
            'last_round': room_data['last_round'],
            'all_cards_done': room_data.get('all_cards_done', False)
        }, to=room_code)

        # Reset round state
        room_data['round_active'] = False
        room_data['explainer'] = None

        save_room_to_db(room_code, rooms)


    @socketio.on('next_round')
    def handle_next_round(data):
        room_code = data.get('room_code')
        if room_code not in rooms:
            return
        room_data = rooms[room_code]
        room_data['round_active'] = False
        room_data['explainer'] = None
        room_data['timer_paused'] = False
        room_data.pop('last_round', None)
        emit('next_round_ready', to=room_code)
        room_data['round_ended'] = False

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
            # Room exists - confirm it so the player can proceed
            emit('room_exists', {'exists': True})

    @socketio.on('all_cards_done')
    def handle_all_cards_done(data):
        room_code = data.get('room_code')
        if room_code in rooms:
            rooms[room_code]['all_cards_done'] = True

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
                save_room_to_db(room_code, rooms)
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

    @socketio.on('new_game')
    def handle_new_game(data):
        room_code = data.get('room_code')
        if room_code not in rooms:
            return
        room_data = rooms[room_code]
        room_data['round_active'] = False
        room_data['explainer'] = None
        room_data['game_started'] = False
        room_data['all_cards_done'] = False
        room_data['round_ended'] = False
        room_data.pop('last_round', None)
        _init_word_pool(room_data)
        # Reset scores
        for player in room_data['players']:
            room_data['players'][player] = 0
        save_room_to_db(room_code, rooms)
        emit('new_game_ready', to=room_code)

