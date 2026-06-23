"""Load tests: 10 rooms with 15 players each (150 concurrent sessions per game)."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from app import app, rooms_game1, rooms_game2, socketio

LOAD_ROOM_COUNT = 10
LOAD_PLAYERS_PER_ROOM = 15

pytestmark = pytest.mark.load


@pytest.fixture(autouse=True)
def mock_db_writes(monkeypatch):
    def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(
        'games.game_1_describe_and_guess.socket_handlers.save_room_to_db',
        noop,
    )
    monkeypatch.setattr(
        'games.game_2_spy_in_ithaca.socket_handlers.save_room_to_db',
        noop,
    )


def _disconnect_all(clients):
    for client in clients:
        try:
            client.disconnect()
        except RuntimeError:
            pass


def _player_name(room_index, player_index):
    return f"R{room_index:02d}-P{player_index:02d}"


def _setup_describe_room(room_index):
    clients = []
    host_name = _player_name(room_index, 1)
    host = socketio.test_client(app)
    clients.append(host)

    host.emit('create_room', {'name': host_name})
    received = host.get_received()
    if not received or received[0]['name'] != 'room_created':
        raise AssertionError(f"room {room_index}: host did not get room_created")
    room_code = received[0]['args'][0]['room_code']

    for i in range(2, LOAD_PLAYERS_PER_ROOM + 1):
        guest = socketio.test_client(app)
        clients.append(guest)
        guest.emit('join_room', {
            'room_code': room_code,
            'name': _player_name(room_index, i),
            'host_token': '',
        })
        guest_received = guest.get_received()
        if guest_received and guest_received[0]['name'] == 'error':
            raise AssertionError(
                f"room {room_index}: join failed for {_player_name(room_index, i)}: "
                f"{guest_received[0]['args'][0].get('message')}"
            )

    host.emit('start_game', {'room_code': room_code})
    host.get_received()

    room = rooms_game1.get(room_code)
    if not room:
        raise AssertionError(f"room {room_index}: missing from rooms_game1")
    if len(room['players']) != LOAD_PLAYERS_PER_ROOM:
        raise AssertionError(
            f"room {room_index}: expected {LOAD_PLAYERS_PER_ROOM} players, "
            f"got {len(room['players'])}"
        )
    if not room.get('game_started'):
        raise AssertionError(f"room {room_index}: game did not start")

    return room_code, clients


def _setup_spy_room(room_index):
    clients = []
    names = [_player_name(room_index, i) for i in range(1, LOAD_PLAYERS_PER_ROOM + 1)]

    host = socketio.test_client(app)
    clients.append(host)
    host.emit('spy_create_room', {'name': names[0]})
    received = host.get_received()
    if not received or received[0]['name'] != 'spy_room_created':
        raise AssertionError(f"room {room_index}: host did not get spy_room_created")
    room_code = received[0]['args'][0]['room_code']

    for name in names[1:]:
        guest = socketio.test_client(app)
        clients.append(guest)
        guest.emit('spy_join_room', {'room_code': room_code, 'name': name})
        guest_received = guest.get_received()
        if guest_received and guest_received[0]['name'] == 'error':
            raise AssertionError(
                f"room {room_index}: join failed for {name}: "
                f"{guest_received[0]['args'][0].get('message')}"
            )

    host.emit('spy_start_game', {
        'room_code': room_code,
        'spy_count': 1,
        'extra_roles': False,
        'round_duration_sec': 540,
        'location_set': 'modern_world',
    })
    time.sleep(0.15)

    for client, name in zip(clients, names):
        client.emit('spy_role_ready', {
            'room_code': room_code,
            'player_name': name,
        })
    time.sleep(0.25)

    for client in clients:
        client.get_received()

    room = rooms_game2.get(room_code)
    if not room:
        raise AssertionError(f"room {room_index}: missing from rooms_game2")
    if len(room['players']) != LOAD_PLAYERS_PER_ROOM:
        raise AssertionError(
            f"room {room_index}: expected {LOAD_PLAYERS_PER_ROOM} players, "
            f"got {len(room['players'])}"
        )
    if room.get('phase') != 'playing':
        raise AssertionError(
            f"room {room_index}: expected phase 'playing', got {room.get('phase')}"
        )

    return room_code, clients


def _run_parallel_room_setup(setup_fn):
    room_codes = []
    all_clients = []
    errors = []

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=LOAD_ROOM_COUNT) as pool:
        futures = {
            pool.submit(setup_fn, room_index): room_index
            for room_index in range(1, LOAD_ROOM_COUNT + 1)
        }
        for future in as_completed(futures):
            room_index = futures[future]
            try:
                room_code, clients = future.result()
                room_codes.append(room_code)
                all_clients.extend(clients)
            except Exception as exc:
                errors.append(f"room {room_index}: {exc}")

    elapsed = time.perf_counter() - started

    try:
        assert not errors, "setup errors:\n" + "\n".join(errors)
        assert len(room_codes) == LOAD_ROOM_COUNT
        assert len(all_clients) == LOAD_ROOM_COUNT * LOAD_PLAYERS_PER_ROOM
        return elapsed, room_codes, all_clients
    finally:
        _disconnect_all(all_clients)


class TestDescribeAndGuessLoad:

    def test_ten_rooms_fifteen_players(self):
        elapsed, room_codes, _ = _run_parallel_room_setup(_setup_describe_room)

        assert len(set(room_codes)) == LOAD_ROOM_COUNT
        for room_code in room_codes:
            assert len(rooms_game1[room_code]['players']) == LOAD_PLAYERS_PER_ROOM

        print(
            f"\nDescribe and Guess: {LOAD_ROOM_COUNT} rooms x "
            f"{LOAD_PLAYERS_PER_ROOM} players = "
            f"{LOAD_ROOM_COUNT * LOAD_PLAYERS_PER_ROOM} clients in {elapsed:.2f}s"
        )


class TestSpyInIthacaLoad:

    def test_ten_rooms_fifteen_players(self):
        elapsed, room_codes, _ = _run_parallel_room_setup(_setup_spy_room)

        assert len(set(room_codes)) == LOAD_ROOM_COUNT
        for room_code in room_codes:
            room = rooms_game2[room_code]
            assert len(room['players']) == LOAD_PLAYERS_PER_ROOM
            assert room['phase'] == 'playing'

        print(
            f"\nSpy in Ithaca: {LOAD_ROOM_COUNT} rooms x "
            f"{LOAD_PLAYERS_PER_ROOM} players = "
            f"{LOAD_ROOM_COUNT * LOAD_PLAYERS_PER_ROOM} clients in {elapsed:.2f}s"
        )
