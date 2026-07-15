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


_ROTATE_EXPLAINER = '__rotate__'
_WORD_SET_KEYS = frozenset({'easy', 'medium', 'odyssey'})


def _word_list_for_set(word_set):
    data = _load_all_words()
    if isinstance(data, list):
        return list(data)
    return list(data.get(word_set, data.get('odyssey', data.get('easy', []))))


def _default_settings():
    return {'word_set': 'odyssey', 'explainer': _ROTATE_EXPLAINER}


def _init_word_pool(room_data):
    word_set = room_data.get('settings', _default_settings()).get('word_set', 'odyssey')
    words = _word_list_for_set(word_set)
    random.shuffle(words)
    room_data['word_pool'] = words
    room_data['word_pool_index'] = 0


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


def _validate_player_name(name):
    name = (name or "").strip()
    if not name or len(name) > 10:
        return None
    return name


def _rename_ordered_key(mapping, old_key, new_key):
    if old_key not in mapping:
        return
    items = [(new_key if k == old_key else k, v) for k, v in mapping.items()]
    mapping.clear()
    mapping.update(items)


def _rename_player_in_room(room_data, old_name, new_name):
    _rename_ordered_key(room_data["players"], old_name, new_name)

    if room_data.get("host_name") == old_name:
        room_data["host_name"] = new_name
    if room_data.get("explainer") == old_name:
        room_data["explainer"] = new_name

    settings = room_data.get("settings")
    if settings and settings.get("explainer") == old_name:
        settings["explainer"] = new_name

    last_round = room_data.get("last_round")
    if last_round and last_round.get("player") == old_name:
        last_round["player"] = new_name

    sids = room_data.setdefault("player_sids", {})
    if old_name in sids:
        _rename_ordered_key(sids, old_name, new_name)


def _can_rename_player(room_data, old_name, sid):
    if room_data.get("host_sid") == sid and room_data.get("host_name") == old_name:
        return True
    sids = room_data.get("player_sids", {})
    return sids.get(old_name) == sid


def _validate_player_name(name):
    name = (name or "").strip()
    if not name or len(name) > 10:
        return None
    return name


def _rename_ordered_key(mapping, old_key, new_key):
    if old_key not in mapping:
        return
    items = [(new_key if k == old_key else k, v) for k, v in mapping.items()]
    mapping.clear()
    mapping.update(items)


def _rename_player_in_room(room_data, old_name, new_name):
    _rename_ordered_key(room_data["players"], old_name, new_name)

    if room_data.get("host_name") == old_name:
        room_data["host_name"] = new_name
    if room_data.get("explainer") == old_name:
        room_data["explainer"] = new_name

    last_round = room_data.get("last_round")
    if last_round and last_round.get("player") == old_name:
        last_round["player"] = new_name

    sids = room_data.setdefault("player_sids", {})
    if old_name in sids:
        _rename_ordered_key(sids, old_name, new_name)


def _can_rename_player(room_data, old_name, sid):
    if room_data.get("host_sid") == sid and room_data.get("host_name") == old_name:
        return True
    sids = room_data.get("player_sids", {})
    return sids.get(old_name) == sid


def register_handlers(socketio, rooms_ref, save_room_fn, generate_code_fn):
    """Register all SocketIO event handlers for Game 1."""
    global rooms, save_room_to_db, generate_room_code
    rooms = rooms_ref
    save_room_to_db = save_room_fn
    generate_room_code = generate_code_fn

    def _players_list(room_data):
        return list(room_data.get('players', {}).keys())

    def _suggested_explainer(room_data):
        players = _players_list(room_data)
        if not players:
            return None
        idx = room_data.get('explainer_index', 0) % len(players)
        return players[idx]

    def _public_settings(room_data):
        settings = room_data.setdefault('settings', _default_settings())
        players = _players_list(room_data)
        suggested = _suggested_explainer(room_data)
        explainer = settings.get('explainer', _ROTATE_EXPLAINER)
        if explainer == _ROTATE_EXPLAINER or explainer not in players:
            explainer = suggested
        return {
            'word_set': settings.get('word_set', 'odyssey'),
            'explainer': explainer,
            'suggested_explainer': suggested,
        }

    def _lobby_payload(room_data):
        return {
            'players': _players_list(room_data),
            'settings': _public_settings(room_data),
            'host_name': room_data.get('host_name'),
        }

    def _finalize_round(room_code, player=None, client_score=0):
        room_data = rooms.get(room_code)
        if not room_data or room_data.get('round_ended'):
            return False

        room_data['round_ended'] = True
        room_data['round_active'] = False
        room_data['timer_paused'] = False

        round_score = room_data.pop('round_score', client_score)
        explainer = player or room_data.get('explainer')
        if explainer and explainer in room_data['players']:
            room_data['players'][explainer] += round_score

        room_data['last_round'] = {
            'player': explainer,
            'score': round_score,
        }
        scoreboard = [
            {'name': name, 'display': str(total)}
            for name, total in room_data['players'].items()
        ]
        socketio.emit('scoreboard_update', {
            'scoreboard': scoreboard,
            'last_round': room_data['last_round'],
            'all_cards_done': room_data.get('all_cards_done', False),
        }, to=room_code)
        room_data['explainer'] = None
        save_room_to_db(room_code, rooms)
        return True

    def _identify_explainer(room_data):
        players = _players_list(room_data)
        if not players:
            return None
        choice = room_data.get('settings', {}).get('explainer', _ROTATE_EXPLAINER)
        if choice == _ROTATE_EXPLAINER:
            return _suggested_explainer(room_data)
        if choice in players:
            return choice
        return players[0]

    def _apply_settings(room_data, data):
        settings = room_data.setdefault('settings', _default_settings())
        word_set = data.get('word_set')
        if word_set in _WORD_SET_KEYS:
            settings['word_set'] = word_set
        explainer = data.get('explainer')
        if explainer in room_data.get('players', {}):
            settings['explainer'] = explainer

    def _emit_lobby_state(room_code, target=None):
        room_data = rooms.get(room_code)
        if not room_data:
            return
        payload = _lobby_payload(room_data)
        if target:
            emit('lobby_state', payload, to=target)
        else:
            socketio.emit('lobby_state', payload, to=room_code)

    def _start_round(room_code):
        room_data = rooms[room_code]
        explainer = _identify_explainer(room_data)
        if not explainer:
            return False
        room_data['game_started'] = True
        room_data['all_cards_done'] = False
        room_data['round_ended'] = False
        _init_word_pool(room_data)
        room_data['explainer'] = explainer
        room_data['round_active'] = True
        room_data.pop('last_round', None)
        socketio.emit('round_started', {
            'explainer': explainer,
            'duration': room_data['duration'],
            'settings': _public_settings(room_data),
        }, to=room_code)
        return True

    @socketio.on('create_room')
    def handle_create_room(data):
        player_name = _validate_player_name(data.get('name'))
        if not player_name:
            emit('error', {'message': 'Name must be 1-10 characters'})
            return
        room_code = generate_room_code()
        sid = request.sid
        host_token = secrets.token_hex(16)

        rooms[room_code] = {
            'host_sid': sid,
            'host_name': player_name,
            'host_token': host_token,
            'players': {player_name: 0},
            'player_sids': {player_name: sid},
            'game_started': False,
            'round_active': False,
            'explainer': None,
            'round_start_time': None,
            'duration': 90,
            'timer_thread': None,
            'settings': {**_default_settings(), 'explainer': player_name},
            'explainer_index': 0,
        }

        save_room_to_db(room_code, rooms)
        join_room(room_code)

        emit('room_created', {
            'room_code': room_code,
            'is_host': True,
            'host_token': host_token,
            'host_name': player_name,
            'players': _players_list(rooms[room_code]),
            'settings': _public_settings(rooms[room_code]),
        }, to=room_code)

    @socketio.on('join_room')
    def handle_join_room(data):
        """
        Join existing game room.
        Expects: { 'name': player_name, 'room_code': room_code }
        """
        player_name = _validate_player_name(data.get('name'))
        room_code = data.get('room_code')
        client_host_token = data.get('host_token')

        if not player_name:
            emit('error', {'message': 'Name must be 1-10 characters'})
            return

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
                room_data.setdefault('player_sids', {})[player_name] = request.sid
                join_room(room_code)
                emit('room_created', {
                    'room_code': room_code,
                    'is_host': True,
                    'host_token': room_data.get('host_token'),
                    'host_name': room_data.get('host_name'),
                    'players': _players_list(room_data),
                    'settings': _public_settings(room_data),
                }, to=request.sid)
                return

        # A regular player joins (or the host joins for the first time)
        if player_name in room_data['players']:
            emit('error', {'message': 'This name is already taken. Please choose another.'})
            return

        if player_name not in room_data['players']:
            room_data['players'][player_name] = 0
        room_data.setdefault('player_sids', {})[player_name] = request.sid
        join_room(room_code)

        save_room_to_db(room_code, rooms)

        emit('player_joined', {
            'player': player_name,
            'players': _players_list(room_data),
            'settings': _public_settings(room_data),
            'host_name': room_data.get('host_name'),
        }, to=room_code)

        # Send current game state to the newly joined player
        if room_data.get('round_active') and room_data.get('explainer'):
            emit('round_started', {
                'explainer': room_data['explainer'],
                'duration': room_data['duration'],
                'late_join': True,
            }, to=request.sid)
        elif room_data.get('last_round') and room_data.get('round_ended'):
            scoreboard = [
                {'name': name, 'display': str(total)}
                for name, total in room_data['players'].items()
            ]
            emit('scoreboard_update', {
                'scoreboard': scoreboard,
                'last_round': room_data['last_round'],
                'all_cards_done': room_data.get('all_cards_done', False),
            }, to=request.sid)
        elif room_data.get('game_started'):
            _emit_lobby_state(room_code, target=request.sid)


    @socketio.on('dng_update_settings')
    def handle_dng_update_settings(data):
        room_code = data.get('room_code')
        if room_code not in rooms:
            return
        room_data = rooms[room_code]
        if request.sid != room_data.get('host_sid'):
            emit('error', {'message': 'Only the host can change settings'}, to=request.sid)
            return
        if room_data.get('round_active'):
            return
        _apply_settings(room_data, data)
        save_room_to_db(room_code, rooms)
        _emit_lobby_state(room_code)

    @socketio.on('start_game')
    def handle_start_game(data):
        """
        Start a round (only host). Applies lobby settings and begins play.
        """
        room_code = data.get('room_code')
        sid = request.sid

        if room_code not in rooms:
            emit('error', {'message': 'Room not found'})
            return

        room_data = rooms[room_code]
        if sid != room_data.get('host_sid'):
            emit('error', {'message': 'Only the host can start the game'})
            return

        if room_data.get('round_active'):
            return

        _apply_settings(room_data, data)
        if not _start_round(room_code):
            emit('error', {'message': 'Need at least one player'}, to=request.sid)
            return
        save_room_to_db(room_code, rooms)

    @socketio.on('become_explainer')
    def handle_become_explainer(data):
        # Legacy clients/tests: start round if explainer volunteers before round begins.
        room_code = data.get('room_code')
        player_name = data.get('player_name')

        if room_code not in rooms:
            return
        room_data = rooms[room_code]
        if room_data.get('round_active') or room_data.get('explainer') is not None:
            return

        settings = room_data.setdefault('settings', _default_settings())
        settings['explainer'] = player_name
        if not room_data.get('game_started'):
            room_data['game_started'] = True
            room_data['all_cards_done'] = False
            _init_word_pool(room_data)
        room_data['explainer'] = player_name
        room_data['round_active'] = True

        emit('round_started', {
            'explainer': player_name,
            'duration': room_data['duration'],
            'settings': _public_settings(room_data),
        }, to=room_code)

        room_data.pop('last_round', None)
        save_room_to_db(room_code, rooms)

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
        socketio.emit('timer_paused', {
            'time_left': room.get('timer_time_left'),
        }, to=room_code)

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
        socketio.emit('timer_resumed', {
            'time_left': room['timer_time_left'],
        }, to=room_code)
        emit('timer_update', {'time_left': room['timer_time_left']}, to=room_code)

    @socketio.on('dng_restart_round')
    def handle_dng_restart_round(data):
        room_code = data.get('room_code')
        if room_code not in rooms:
            emit('error', {'message': 'Room not found'}, to=request.sid)
            return
        room_data = rooms[room_code]
        if request.sid != room_data.get('host_sid'):
            return
        if room_data.get('round_ended'):
            return
        if not room_data.get('round_active') or room_data.get('explainer') is None:
            return
        room_data['round_active'] = False
        _finalize_round(room_code)

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

        player = data.get('player') or room_data.get('explainer')
        _finalize_round(
            room_code,
            player=player,
            client_score=data.get('round_score', 0),
        )


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
        room_data['round_ended'] = False
        players = _players_list(room_data)
        if players:
            room_data['explainer_index'] = (
                room_data.get('explainer_index', 0) + 1
            ) % len(players)
            suggested = _suggested_explainer(room_data)
            if suggested:
                room_data.setdefault('settings', _default_settings())['explainer'] = suggested
        emit('next_round_ready', {
            **_lobby_payload(room_data),
        }, to=room_code)

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

    @socketio.on('rename_player')
    def handle_rename_player(data):
        room_code = data.get('room_code')
        old_name = _validate_player_name(data.get('old_name'))
        new_name = _validate_player_name(data.get('new_name'))

        if not old_name or not new_name:
            emit('rename_error', {'message': 'Invalid name'}, to=request.sid)
            return

        if room_code not in rooms:
            emit('rename_error', {'message': 'Room not found'}, to=request.sid)
            return

        room_data = rooms[room_code]
        sid = request.sid

        if not _can_rename_player(room_data, old_name, sid):
            emit('rename_error', {'message': 'You can only rename yourself'}, to=request.sid)
            return

        if old_name not in room_data['players']:
            emit('rename_error', {'message': 'Player not found'}, to=request.sid)
            return

        if new_name != old_name and new_name in room_data['players']:
            emit('rename_error', {
                'message': 'This name is already taken. Please choose another.',
            }, to=request.sid)
            return

        if new_name == old_name:
            return

        _rename_player_in_room(room_data, old_name, new_name)
        save_room_to_db(room_code, rooms)

        emit('player_renamed', {
            'old_name': old_name,
            'new_name': new_name,
            'players': list(room_data['players'].keys()),
            'host_name': room_data.get('host_name'),
            'explainer': room_data.get('explainer'),
            'last_round': room_data.get('last_round'),
            'scoreboard': [
                {'name': name, 'display': str(total)}
                for name, total in room_data['players'].items()
            ],
        }, to=room_code)

    @socketio.on('rename_player')
    def handle_rename_player(data):
        room_code = data.get('room_code')
        old_name = _validate_player_name(data.get('old_name'))
        new_name = _validate_player_name(data.get('new_name'))

        if not old_name or not new_name:
            emit('rename_error', {'message': 'Invalid name'}, to=request.sid)
            return

        if room_code not in rooms:
            emit('rename_error', {'message': 'Room not found'}, to=request.sid)
            return

        room_data = rooms[room_code]
        sid = request.sid

        if not _can_rename_player(room_data, old_name, sid):
            emit('rename_error', {'message': 'You can only rename yourself'}, to=request.sid)
            return

        if old_name not in room_data['players']:
            emit('rename_error', {'message': 'Player not found'}, to=request.sid)
            return

        if new_name != old_name and new_name in room_data['players']:
            emit('rename_error', {
                'message': 'This name is already taken. Please choose another.',
            }, to=request.sid)
            return

        if new_name == old_name:
            return

        _rename_player_in_room(room_data, old_name, new_name)
        save_room_to_db(room_code, rooms)

        emit('player_renamed', {
            'old_name': old_name,
            'new_name': new_name,
            'players': list(room_data['players'].keys()),
            'explainer': room_data.get('explainer'),
            'last_round': room_data.get('last_round'),
            'scoreboard': [
                {'name': name, 'display': str(total)}
                for name, total in room_data['players'].items()
            ],
        }, to=room_code)

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
        room_data['settings'] = _default_settings()
        room_data['explainer_index'] = 0
        players = _players_list(room_data)
        if players:
            room_data['settings']['explainer'] = players[0]
        # Reset scores
        for player in room_data['players']:
            room_data['players'][player] = 0
        save_room_to_db(room_code, rooms)
        emit('new_game_ready', _lobby_payload(room_data), to=room_code)

