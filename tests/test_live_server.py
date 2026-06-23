import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
import socketio

from tests.live_config import (
    LIVE_EVENT_TIMEOUT,
    LIVE_GAME_SERVER_URL,
    LIVE_LOAD_PARALLEL,
    LIVE_LOAD_PLAYERS,
    LIVE_LOAD_ROOMS,
    LIVE_SSL_VERIFY,
    LIVE_SPY_EVENT_TIMEOUT,
    LIVE_SPY_LOAD_PARALLEL,
    LIVE_SPY_ROLE_READY_PAUSE,
    LIVE_TESTS_OK,
    LIVE_TRANSPORTS,
)

pytestmark = [pytest.mark.live]


def _require_live_opt_in():
    if not LIVE_TESTS_OK:
        pytest.skip(
            "Live server tests are disabled. "
            f"Set LIVE_TESTS_OK=1 and LIVE_GAME_SERVER_URL (now: {LIVE_GAME_SERVER_URL})"
        )


class LiveSocket:
    def __init__(self, run_id):
        self._run_id = run_id
        self._events = []
        self._lock = threading.Lock()
        self._client = socketio.Client(
            reconnection=False,
            logger=False,
            engineio_logger=False,
            ssl_verify=LIVE_SSL_VERIFY,
        )

        @self._client.event
        def connect():
            with self._lock:
                self._events.append(("connect", None))

        @self._client.event
        def disconnect():
            with self._lock:
                self._events.append(("disconnect", None))

        @self._client.on("*")
        def on_any(event, data=None):
            if event in ("connect", "disconnect"):
                return
            with self._lock:
                self._events.append((event, data))

    def connect(self):
        self._client.connect(
            LIVE_GAME_SERVER_URL,
            transports=LIVE_TRANSPORTS,
            socketio_path="/socket.io",
            wait=True,
            wait_timeout=LIVE_EVENT_TIMEOUT,
        )

    def disconnect(self):
        if self._client.connected:
            self._client.disconnect()

    def emit(self, event, data=None):
        self._client.emit(event, data or {})

    def wait_for(self, event_name, timeout=None):
        timeout = timeout or LIVE_EVENT_TIMEOUT
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                for index, (event, data) in enumerate(self._events):
                    if event == "error":
                        message = data.get("message", data) if isinstance(data, dict) else data
                        raise AssertionError(f"server error: {message}")
                    if event == event_name:
                        return self._events.pop(index)[1]
            time.sleep(0.05)
        raise TimeoutError(
            f"timed out waiting for '{event_name}' from {LIVE_GAME_SERVER_URL} "
            f"({timeout}s)"
        )

    def drain(self):
        with self._lock:
            self._events.clear()

    def wait_for_round_start(self, timeout=None):
        timeout = timeout or LIVE_SPY_EVENT_TIMEOUT
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                for index, (event, data) in enumerate(self._events):
                    if event == "error":
                        message = data.get("message", data) if isinstance(data, dict) else data
                        raise AssertionError(f"server error: {message}")
                    if event in ("spy_round_started", "spy_enter_game"):
                        return event, data
                    if (
                        event == "spy_state_update"
                        and isinstance(data, dict)
                        and data.get("phase") == "playing"
                    ):
                        return event, data
            time.sleep(0.05)
        raise TimeoutError(
            f"timed out waiting for round start from {LIVE_GAME_SERVER_URL} ({timeout}s)"
        )


_RUN_ID = uuid.uuid4().hex[:8]


def _player_name(room_index, player_index):
    return f"L{_RUN_ID}-R{room_index:02d}-P{player_index:02d}"


def _disconnect_all(clients):
    for client in clients:
        try:
            client.disconnect()
        except Exception:
            pass


def _setup_describe_room(room_index):
    clients = []
    host = LiveSocket(_RUN_ID)
    clients.append(host)
    host.connect()

    host.emit("create_room", {"name": _player_name(room_index, 1)})
    created = host.wait_for("room_created")
    room_code = created["room_code"]
    host.drain()

    last_players = created.get("players", [])
    for player_index in range(2, LIVE_LOAD_PLAYERS + 1):
        guest = LiveSocket(_RUN_ID)
        clients.append(guest)
        guest.connect()
        guest.emit("join_room", {
            "room_code": room_code,
            "name": _player_name(room_index, player_index),
            "host_token": "",
        })
        joined = guest.wait_for("player_joined")
        last_players = joined.get("players", last_players)
        guest.drain()

    host.emit("start_game", {"room_code": room_code})
    host.wait_for("game_started")
    host.drain()

    if len(last_players) < LIVE_LOAD_PLAYERS:
        raise AssertionError(
            f"room {room_index}: expected {LIVE_LOAD_PLAYERS} players, got {len(last_players)}"
        )

    return room_code, clients


def _setup_spy_room(room_index):
    clients = []
    names = [_player_name(room_index, i) for i in range(1, LIVE_LOAD_PLAYERS + 1)]

    host = LiveSocket(_RUN_ID)
    clients.append(host)
    host.connect()
    host.emit("spy_create_room", {"name": names[0]})
    created = host.wait_for("spy_room_created")
    room_code = created["room_code"]
    host.drain()

    last_players = created.get("players", [])
    for name in names[1:]:
        guest = LiveSocket(_RUN_ID)
        clients.append(guest)
        guest.connect()
        guest.emit("spy_join_room", {"room_code": room_code, "name": name})
        joined = guest.wait_for("spy_room_created")
        last_players = joined.get("players", last_players)
        guest.drain()

    if len(last_players) < LIVE_LOAD_PLAYERS:
        raise AssertionError(
            f"room {room_index}: expected {LIVE_LOAD_PLAYERS} players, got {len(last_players)}"
        )

    host.emit("spy_start_game", {
        "room_code": room_code,
        "spy_count": 1,
        "extra_roles": False,
        "round_duration_sec": 540,
        "location_set": "modern_world",
    })

    for client in clients:
        client.wait_for("spy_role_assigned", timeout=LIVE_SPY_EVENT_TIMEOUT)
        client.drain()

    for client, name in zip(clients, names):
        client.emit("spy_role_ready", {
            "room_code": room_code,
            "player_name": name,
        })
        time.sleep(LIVE_SPY_ROLE_READY_PAUSE)

    host.wait_for_round_start(timeout=LIVE_SPY_EVENT_TIMEOUT)
    for client in clients:
        client.drain()

    return room_code, clients


def _run_parallel_room_setup(setup_fn, max_workers=None):
    room_codes = []
    all_clients = []
    errors = []
    workers = max_workers if max_workers is not None else LIVE_LOAD_PARALLEL

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(setup_fn, room_index): room_index
            for room_index in range(1, LIVE_LOAD_ROOMS + 1)
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
        assert len(room_codes) == LIVE_LOAD_ROOMS
        assert len(all_clients) == LIVE_LOAD_ROOMS * LIVE_LOAD_PLAYERS
        return elapsed, room_codes
    finally:
        _disconnect_all(all_clients)


class TestLiveServerConnection:

    def setup_method(self):
        _require_live_opt_in()

    def test_socket_connects(self):
        client = LiveSocket(_RUN_ID)
        try:
            client.connect()
            assert client._client.connected
        finally:
            client.disconnect()

        print(f"\nConnected to {LIVE_GAME_SERVER_URL}")


class TestDescribeAndGuessLive:

    def setup_method(self):
        _require_live_opt_in()

    @pytest.mark.load
    def test_ten_rooms_fifteen_players(self):
        elapsed, room_codes = _run_parallel_room_setup(_setup_describe_room)

        assert len(set(room_codes)) == LIVE_LOAD_ROOMS
        print(
            f"\nDescribe and Guess @ {LIVE_GAME_SERVER_URL}: "
            f"{LIVE_LOAD_ROOMS} rooms x {LIVE_LOAD_PLAYERS} players = "
            f"{LIVE_LOAD_ROOMS * LIVE_LOAD_PLAYERS} clients in {elapsed:.2f}s"
        )


class TestSpyInIthacaLive:

    def setup_method(self):
        _require_live_opt_in()

    @pytest.mark.load
    def test_ten_rooms_fifteen_players(self):
        elapsed, room_codes = _run_parallel_room_setup(
            _setup_spy_room,
            max_workers=LIVE_SPY_LOAD_PARALLEL,
        )

        assert len(set(room_codes)) == LIVE_LOAD_ROOMS
        print(
            f"\nSpy in Ithaca @ {LIVE_GAME_SERVER_URL}: "
            f"{LIVE_LOAD_ROOMS} rooms x {LIVE_LOAD_PLAYERS} players = "
            f"{LIVE_LOAD_ROOMS * LIVE_LOAD_PLAYERS} clients in {elapsed:.2f}s"
        )
