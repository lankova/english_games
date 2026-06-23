"""Automated tests for Describe & Guess (game 1)."""
import time

import allure
import pytest

from app import app, rooms_game1 as rooms, socketio


# =========
# FIXTURES
# =========

@pytest.fixture
def socket_client():
    """Single test client for Socket.IO"""
    client = socketio.test_client(app)
    yield client
    client.disconnect()


@pytest.fixture
def host_client():
    """Creates a room and returns (client, room_code, host_token)"""
    client = socketio.test_client(app)
    client.emit('create_room', {'name': 'Alice'})
    data = client.get_received()[0]['args'][0]
    yield client, data['room_code'], data['host_token']
    try:
        client.disconnect()
    except RuntimeError:
        pass


@pytest.fixture
def guest_client_factory():
    """Factory for multiple guest clients. Auto-disconnects on teardown."""
    clients = []

    def _make():
        c = socketio.test_client(app)
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.disconnect()


@pytest.fixture(autouse=True)
def mock_describe_db(monkeypatch):
    """Prevent database writes during tests."""

    def mock_save(*args, **kwargs):
        pass

    monkeypatch.setattr('games.game_1_describe_and_guess.socket_handlers.save_room_to_db', mock_save)


# ======================
# ROOM MANAGEMENT TESTS
# ======================

@allure.epic("Describe & Guess Game")
@allure.feature("Room Management")
class TestDnGRoomManagement:

    @allure.story("Create a new game room")
    @allure.title("Host creates room")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_create_room(self, socket_client):
        socket_client.emit('create_room', {'name': 'Alice'})
        received = socket_client.get_received()

        assert len(received) > 0, "Expected at least one event"
        assert received[0]['name'] == 'room_created', f"Expected 'room_created', got '{received[0]['name']}'"

        data = received[0]['args'][0]
        assert 'room_code' in data, "Response missing 'room_code'"
        assert len(data['room_code']) == 4, f"Room code should be 4 chars, got '{data['room_code']}'"
        assert data['is_host'] is True, "Host should have is_host=True"
        assert 'Alice' in data['players'], f"Expected 'Alice' in players list, got {data['players']}"
        assert 'host_token' in data, "Response missing 'host_token'"

    @allure.story("Join an existing room")
    @allure.title("Second player joins - should broadcast player_joined event")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_join_room(self, socket_client):
        # Create room as Alice
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        # Clear the room_created event
        socket_client.get_received()

        # Join as Bob
        socket_client.emit('join_room', {
            'room_code': room_code,
            'name': 'Bob',
            'host_token': ''
        })
        received = socket_client.get_received()
        event_names = [e['name'] for e in received]

        assert 'player_joined' in event_names, f"Expected 'player_joined' in {event_names}"

        # Verify player_joined contains correct data
        player_joined_event = next(e for e in received if e['name'] == 'player_joined')
        assert player_joined_event['args'][0]['player'] == 'Bob'
        assert 'Bob' in player_joined_event['args'][0]['players']

    @allure.story("Join a non-existent room")
    @allure.title("Joining invalid room code - should return error message")
    @allure.severity(allure.severity_level.NORMAL)
    def test_join_nonexistent_room(self, socket_client):
        socket_client.emit('join_room', {
            'room_code': 'XXXX',
            'name': 'Bob',
            'host_token': ''
        })
        received = socket_client.get_received()

        assert len(received) > 0, "Expected error event"
        assert received[0]['name'] == 'error', f"Expected 'error', got '{received[0]['name']}'"
        assert 'Room not found' in received[0]['args'][0]['message'], \
            f"Expected 'Room not found', got '{received[0]['args'][0]['message']}'"

    @allure.story("Reject duplicate player names")
    @allure.title("Joining with taken name - should return error message")
    @allure.severity(allure.severity_level.NORMAL)
    def test_duplicate_name(self, socket_client):
        # Create room as Alice
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        # Clear room_created event
        socket_client.get_received()

        # Try to join with same name
        socket_client.emit('join_room', {
            'room_code': room_code,
            'name': 'Alice',
            'host_token': ''
        })
        received = socket_client.get_received()

        assert len(received) > 0, "Expected error event"
        assert received[0]['name'] == 'error', f"Expected 'error', got '{received[0]['name']}'"
        assert 'already taken' in received[0]['args'][0]['message'], \
            f"Expected 'already taken', got '{received[0]['args'][0]['message']}'"


# ================
# GAME FLOW TESTS
# ================

@allure.epic("Describe & Guess Game")
@allure.feature("Game Flow")
class TestDnGGameFlow:

    @allure.story("Start the game")
    @allure.title("Host starts game - should broadcast game_started event")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_host_starts_game(self, socket_client):
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        # Clear room_created event
        socket_client.get_received()

        socket_client.emit('start_game', {'room_code': room_code})
        received = socket_client.get_received()
        event_names = [e['name'] for e in received]

        assert 'game_started' in event_names, f"Expected 'game_started' in {event_names}"

        # Verify game_started flag in rooms dict
        from app import rooms_game1 as rooms
        assert rooms[room_code]['game_started'] is True

    @allure.story("Block non-host from starting")
    @allure.title("Non-host tries to start game - should return error")
    @allure.severity(allure.severity_level.NORMAL)
    def test_non_host_cannot_start_game(self, socket_client):
        # Create room as Alice
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        # Second client joins as Bob
        guest = socketio.test_client(app)
        guest.emit('join_room', {
            'room_code': room_code,
            'name': 'Bob',
            'host_token': ''
        })
        guest.get_received()

        # Bob tries to start the game
        guest.emit('start_game', {'room_code': room_code})
        received = guest.get_received()

        assert len(received) > 0, "Expected error event"
        assert received[0]['name'] == 'error', f"Expected 'error', got '{received[0]['name']}'"
        assert 'Only the host' in received[0]['args'][0]['message']
        guest.disconnect()

    @allure.story("Choose an explainer")
    @allure.title("Player becomes explainer - should trigger round_started event")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_become_explainer(self, socket_client):
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        socket_client.emit('start_game', {'room_code': room_code})
        socket_client.get_received()

        socket_client.emit('become_explainer', {
            'room_code': room_code,
            'player_name': 'Alice'
        })
        received = socket_client.get_received()

        assert len(received) > 0, "Expected round_started event"
        assert received[0]['name'] == 'round_started', f"Expected 'round_started', got '{received[0]['name']}'"
        assert received[0]['args'][0]['explainer'] == 'Alice'
        assert received[0]['args'][0]['duration'] == 90

        # Verify room state
        from app import rooms_game1 as rooms
        assert rooms[room_code]['explainer'] == 'Alice'
        assert rooms[room_code]['round_active'] is True

    @allure.story("Late join during round")
    @allure.title("Player joining mid-round - should get game_started and round_started with late_join flag")
    @allure.severity(allure.severity_level.NORMAL)
    def test_late_join_during_round(self, socket_client):
        # Host creates room and starts round
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        socket_client.emit('start_game', {'room_code': room_code})
        socket_client.get_received()

        socket_client.emit('become_explainer', {
            'room_code': room_code,
            'player_name': 'Alice'
        })
        socket_client.get_received()

        # Late player joins
        guest = socketio.test_client(app)
        guest.emit('join_room', {
            'room_code': room_code,
            'name': 'Bob',
            'host_token': ''
        })
        received = guest.get_received()
        event_names = [e['name'] for e in received]

        assert 'game_started' in event_names, f"Expected 'game_started' in {event_names}"
        assert 'round_started' in event_names, f"Expected 'round_started' in {event_names}"

        round_event = next(e for e in received if e['name'] == 'round_started')
        assert round_event['args'][0]['late_join'] is True
        assert round_event['args'][0]['explainer'] == 'Alice'
        guest.disconnect()


# ====================
# MULTI-CLIENT TESTS
# ====================

@allure.epic("Describe & Guess Game")
@allure.feature("Multi-Client Scenarios")
class TestDnGMultiClient:

    @allure.story("Host and guest receive game_started")
    @allure.title("Both players should get game_started when host starts")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_both_receive_game_started(self, host_client, guest_client_factory):
        host, room_code, _ = host_client
        guest = guest_client_factory()

        # Guest joins
        guest.emit('join_room', {
            'room_code': room_code,
            'name': 'Bob',
            'host_token': ''
        })
        guest.get_received()

        # Clear host's buffer before starting
        host.get_received()

        # Host starts game
        host.emit('start_game', {'room_code': room_code})

        # Check host received game_started
        host_received = host.get_received()
        host_events = [e['name'] for e in host_received]
        assert 'game_started' in host_events, "Host should receive game_started"

        # Check guest received game_started
        guest_received = guest.get_received()
        guest_events = [e['name'] for e in guest_received]
        assert 'game_started' in guest_events, "Guest should receive game_started"

        # Verify game state
        from app import rooms_game1 as rooms
        assert rooms[room_code]['game_started'] is True

    @allure.story("Host disconnect notifies guests")
    @allure.title("When host disconnects, guests should receive host_disconnected")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_host_disconnected(self, host_client, guest_client_factory):
        host, room_code, _ = host_client
        guest = guest_client_factory()

        # Guest joins
        guest.emit('join_room', {
            'room_code': room_code,
            'name': 'Bob',
            'host_token': ''
        })
        guest.get_received()

        # Disconnect host
        host.disconnect()

        # Give time for event to propagate
        time.sleep(0.3)

        # Guest should receive host_disconnected
        received = guest.get_received()
        disconnect_events = [e for e in received if e['name'] == 'host_disconnected']

        assert len(disconnect_events) > 0, "Guest should receive host_disconnected event"

        # Verify room state
        from app import rooms_game1 as rooms
        if room_code in rooms:
            assert rooms[room_code]['host_sid'] is None, "Host SID should be cleared"

    @allure.story("Host reconnects with token")
    @allure.title("Host should regain host status when reconnecting with valid token")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_host_reconnect_with_token(self, host_client, guest_client_factory):
        host, room_code, host_token = host_client

        # Disconnect host
        host.disconnect()

        # Give time for cleanup
        time.sleep(0.2)

        # Reconnect with same name and token
        new_host = guest_client_factory()
        new_host.emit('join_room', {
            'room_code': room_code,
            'name': 'Alice',
            'host_token': host_token
        })
        received = new_host.get_received()

        # Should get host privileges back
        event_names = [e['name'] for e in received]
        assert 'room_created' in event_names, f"Expected 'room_created', got {event_names}"

        room_event = next(e for e in received if e['name'] == 'room_created')
        assert room_event['args'][0]['is_host'] is True, "Reconnected host should have is_host=True"

        # Verify room state updated
        from app import rooms_game1 as rooms
        assert rooms[room_code]['host_sid'] is not None, "Host SID should be restored"


# ==============
# SCORING TESTS
# ==============

@allure.epic("Describe & Guess Game")
@allure.feature("Scoring")
class TestDnGScoring:

    @allure.story("Round end scoreboard")
    @allure.title("Round ends - should return correct score in scoreboard_update")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_round_end_scoreboard(self, socket_client):
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        socket_client.emit('start_game', {'room_code': room_code})
        socket_client.emit('become_explainer', {
            'room_code': room_code,
            'player_name': 'Alice'
        })
        socket_client.get_received()

        socket_client.emit('score_update', {'room_code': room_code, 'increment': 1})
        socket_client.emit('score_update', {'room_code': room_code, 'increment': 1})
        socket_client.emit('round_end', {
            'room_code': room_code,
            'player': 'Alice',
            'round_score': 2
        })
        received = socket_client.get_received()

        # Find scoreboard_update event by name instead of using received[-1]
        scoreboard_events = [e for e in received if e['name'] == 'scoreboard_update']
        assert len(scoreboard_events) > 0, "Expected 'scoreboard_update' event, but none found"

        scoreboard_event = scoreboard_events[0]
        data = scoreboard_event['args'][0]
        assert data['last_round']['player'] == 'Alice'
        assert data['last_round']['score'] == 2


# ========================
# STATE MANAGEMENT TESTS
# ========================

@allure.epic("Describe & Guess Game")
@allure.feature("State Management")
class TestDnGStateManagement:

    @allure.story("Next round transitions")
    @allure.title("After round ends, next_round should reset round_ended flag")
    @allure.severity(allure.severity_level.NORMAL)
    def test_next_round(self, socket_client):
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        # Setup: start game, become explainer, end round
        socket_client.emit('start_game', {'room_code': room_code})
        socket_client.emit('become_explainer', {
            'room_code': room_code,
            'player_name': 'Alice'
        })
        socket_client.get_received()

        socket_client.emit('round_end', {
            'room_code': room_code,
            'player': 'Alice',
            'round_score': 2
        })
        socket_client.get_received()

        # Request next round
        socket_client.emit('next_round', {'room_code': room_code})
        received = socket_client.get_received()

        event_names = [e['name'] for e in received]
        assert 'next_round_ready' in event_names, f"Expected 'next_round_ready', got {event_names}"

        # Verify room state
        from app import rooms_game1 as rooms
        assert rooms[room_code]['round_ended'] is False, "round_ended flag should be cleared"

    @allure.story("Idempotent round_end")
    @allure.title("Second round_end should be ignored when round already ended")
    @allure.severity(allure.severity_level.NORMAL)
    def test_round_end_idempotent(self, socket_client):
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        socket_client.emit('start_game', {'room_code': room_code})
        socket_client.emit('become_explainer', {
            'room_code': room_code,
            'player_name': 'Alice'
        })
        socket_client.get_received()

        # First round_end - should work
        socket_client.emit('round_end', {
            'room_code': room_code,
            'player': 'Alice',
            'round_score': 2
        })
        first_received = socket_client.get_received()
        scoreboard_events_first = [e for e in first_received if e['name'] == 'scoreboard_update']
        assert len(scoreboard_events_first) > 0, "First round_end should emit scoreboard_update"

        # Second round_end - should be ignored
        socket_client.emit('round_end', {
            'room_code': room_code,
            'player': 'Alice',
            'round_score': 0
        })
        second_received = socket_client.get_received()
        scoreboard_events_second = [e for e in second_received if e['name'] == 'scoreboard_update']

        assert len(scoreboard_events_second) == 0, \
            "Second round_end should be ignored and not emit another scoreboard_update"


# ======================
# TIMER CONTROLS TESTS
# ======================

@allure.epic("Describe & Guess Game")
@allure.feature("Timer Controls")
class TestDnGTimer:

    @allure.story("Pause the countdown")
    @allure.title("Pause timer - should set timer_paused flag and save remaining time")
    @allure.severity(allure.severity_level.NORMAL)
    def test_pause_timer(self, socket_client):
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        socket_client.emit('start_game', {'room_code': room_code})
        socket_client.emit('become_explainer', {
            'room_code': room_code,
            'player_name': 'Alice'
        })
        socket_client.get_received()

        socket_client.emit('pause_timer', {
            'room_code': room_code,
            'time_left': 45
        })

        from app import rooms_game1 as rooms
        assert rooms[room_code]['timer_paused'] is True, "Timer should be paused"
        assert rooms[room_code]['timer_time_left'] == 45, f"Expected 45, got {rooms[room_code]['timer_time_left']}"

    @allure.story("Resume the countdown")
    @allure.title("Resume timer - should emit timer_update with remaining time")
    @allure.severity(allure.severity_level.NORMAL)
    def test_resume_timer(self, socket_client):
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        socket_client.emit('start_game', {'room_code': room_code})
        socket_client.emit('become_explainer', {
            'room_code': room_code,
            'player_name': 'Alice'
        })
        socket_client.get_received()

        socket_client.emit('pause_timer', {'room_code': room_code, 'time_left': 45})
        socket_client.emit('resume_timer', {'room_code': room_code})
        received = socket_client.get_received()

        assert len(received) > 0, "Expected timer_update event after resume"
        assert received[0]['name'] == 'timer_update', \
            f"Expected 'timer_update', got '{received[0]['name']}'"
        assert received[0]['args'][0]['time_left'] == 45, "Should resume from paused time"

    @allure.story("Round timeout")
    @allure.title("Timer expires - should emit round_timeout and reset room state")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_round_timeout(self, socket_client, monkeypatch):
        # Create room and start round with short duration
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        socket_client.emit('start_game', {'room_code': room_code})
        socket_client.get_received()

        socket_client.emit('become_explainer', {
            'room_code': room_code,
            'player_name': 'Alice'
        })
        socket_client.get_received()

        # Set duration to 2 seconds for fast timeout
        from app import rooms_game1 as rooms
        rooms[room_code]['duration'] = 2

        socket_client.emit('start_timer', {'room_code': room_code})
        socket_client.get_received()

        # Wait for timeout
        deadline = time.time() + 5
        round_timeout_received = False
        while time.time() < deadline:
            for event in socket_client.get_received():
                if event['name'] == 'round_timeout':
                    round_timeout_received = True
                    break
            if round_timeout_received:
                break
            time.sleep(0.1)

        assert round_timeout_received, "Expected 'round_timeout' event within 5 seconds"
        assert rooms[room_code]['explainer'] is None, "Explainer should be reset after timeout"
        assert rooms[room_code]['round_active'] is False, "Round should be inactive after timeout"


# ==================
# EDGE CASES TESTS
# ==================

@allure.epic("Describe & Guess Game")
@allure.feature("Edge Cases")
class TestDnGEdgeCases:

    @allure.story("Start a new game")
    @allure.title("New game - should emit new_game_ready and reset all scores to 0")
    @allure.severity(allure.severity_level.NORMAL)
    def test_new_game_resets(self, socket_client):
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        socket_client.emit('start_game', {'room_code': room_code})
        socket_client.get_received()

        socket_client.emit('new_game', {'room_code': room_code})
        received = socket_client.get_received()

        assert len(received) > 0, "Expected new_game_ready event"
        assert received[0]['name'] == 'new_game_ready', \
            f"Expected 'new_game_ready', got '{received[0]['name']}'"

        from app import rooms_game1 as rooms
        for player, score in rooms[room_code]['players'].items():
            assert score == 0, f"Score for '{player}' should be 0, got {score}"

    @allure.story("All cards finished")
    @allure.title("All cards done - should set all_cards_done flag in room data")
    @allure.severity(allure.severity_level.MINOR)
    def test_all_cards_done(self, socket_client):
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        socket_client.emit('all_cards_done', {'room_code': room_code})

        from app import rooms_game1 as rooms
        assert rooms[room_code]['all_cards_done'] is True, "Flag 'all_cards_done' should be set to True"

    @allure.story("Kick a player")
    @allure.title("Host kicks player - should remove player from room and notify kicked player")
    @allure.severity(allure.severity_level.NORMAL)
    def test_kick_player(self, socket_client):
        # Create room as Alice (host)
        socket_client.emit('create_room', {'name': 'Alice'})
        room_data = socket_client.get_received()[0]['args'][0]
        room_code = room_data['room_code']

        # Bob joins
        guest = socketio.test_client(app)
        guest.emit('join_room', {
            'room_code': room_code,
            'name': 'Bob',
            'host_token': ''
        })
        guest.get_received()

        # Host kicks Bob
        socket_client.emit('kick_player', {
            'room_code': room_code,
            'player_name': 'Bob'
        })

        # Bob receives kick event
        received = guest.get_received()
        assert len(received) > 0, "Kicked player should receive an event"
        assert received[0]['name'] == 'player_kicked', f"Expected 'player_kicked', got '{received[0]['name']}'"
        assert received[0]['args'][0]['player'] == 'Bob'

        # Verify Bob removed from room
        from app import rooms_game1 as rooms
        assert 'Bob' not in rooms[room_code]['players'], "Bob should be removed from players list"

        guest.disconnect()


# ==================
# HTTP ROUTES TESTS
# ==================

@allure.epic("Describe & Guess Game")
@allure.feature("HTTP Routes")
class TestDnGRoutes:

    @pytest.fixture
    def http_client(self):
        """HTTP test client without WebSocket"""
        with app.test_client() as client:
            yield client

    @allure.story("Game page loads")
    @allure.title("GET /describe-and-guess/<code> should return 200")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_game_page_loads(self, http_client):
        """Verify the game page loads successfully"""
        response = http_client.get('/describe-and-guess/TEST')
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    @allure.story("Game page includes Socket.IO")
    @allure.title("Game page should include Socket.IO client library")
    @allure.severity(allure.severity_level.NORMAL)
    def test_game_page_has_socketio(self, http_client):
        """Verify the game page includes required JavaScript"""
        response = http_client.get('/describe-and-guess/TEST')
        html = response.data.decode('utf-8').lower()
        assert 'socket.io' in html, "Page should include Socket.IO client"

    @allure.story("Main game menu loads")
    @allure.title("GET /game1/game should return 200")
    @allure.severity(allure.severity_level.NORMAL)
    def test_game_menu_loads(self, http_client):
        """Verify the game menu page loads"""
        response = http_client.get('/game1/game')
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    @allure.story("Invalid room code handled gracefully")
    @allure.title("Game page with invalid room code should still load")
    @allure.severity(allure.severity_level.MINOR)
    def test_invalid_room_code(self, http_client):
        """Verify the page loads even with non-existent room (JS handles the error)"""
        response = http_client.get('/describe-and-guess/NONEXIST')
        assert response.status_code == 200, "Page should load even with invalid room code"
