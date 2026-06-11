import time
import allure
import pytest
from app import app, rooms_game2, socketio


# ========================
# FIXTURES
# ========================

@pytest.fixture(autouse=True)
def clear_spy_rooms():
    """Fresh room dict for each test."""
    rooms_game2.clear()
    yield
    rooms_game2.clear()


@pytest.fixture(autouse=True)
def mock_spy_db(monkeypatch):
    """Room state lives in memory during tests."""

    def mock_save(*args, **kwargs):
        pass

    monkeypatch.setattr(
        'games.game_2_spy_in_ithaca.socket_handlers.save_room_to_db',
        mock_save,
    )


@pytest.fixture
def socket_client():
    client = socketio.test_client(app)
    yield client
    client.disconnect()


@pytest.fixture
def guest_client_factory():
    clients = []

    def _make():
        c = socketio.test_client(app)
        clients.append(c)
        return c

    yield _make
    for c in clients:
        try:
            c.disconnect()
        except RuntimeError:
            pass


def _default_start_payload(**overrides):
    payload = {
        'spy_count': 1,
        'extra_roles': False,
        'round_duration_sec': 540,
        'location_set': 'modern_world',
    }
    payload.update(overrides)
    return payload


def _create_room(client, name='Alice'):
    client.emit('spy_create_room', {'name': name})
    data = client.get_received()[0]['args'][0]
    return data['room_code']


def _join(client, room_code, name):
    client.emit('spy_join_room', {'room_code': room_code, 'name': name})
    client.get_received()


def _event_names(client):
    return [e['name'] for e in client.get_received()]


def _events(client, name):
    return [e for e in client.get_received() if e['name'] == name]


def _start_role_reveal(clients, room_code, settings=None):
    """Deal roles and move room to role_reveal."""
    settings = settings or _default_start_payload()
    clients[0].emit('spy_start_game', {'room_code': room_code, **settings})
    time.sleep(0.1)
    for client in clients:
        client.get_received()


def _enter_playing(clients, room_code, names, settings=None):
    _start_role_reveal(clients, room_code, settings)
    for client, name in zip(clients, names):
        client.emit('spy_role_ready', {'room_code': room_code, 'player_name': name})
    time.sleep(0.2)
    for client in clients:
        client.get_received()


def _spy_names(room_code):
    room = rooms_game2[room_code]
    return [n for n, role in room['roles'].items() if role['is_spy']]


# ========================
# ROOM MANAGEMENT
# ========================

@allure.epic("Spy in Ithaca")
@allure.feature("Room Management")
class TestSpyRoomManagement:

    @allure.story("Create a new game room")
    @allure.title("Host creates room - should return room code and default settings")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_create_room(self, socket_client):
        socket_client.emit('spy_create_room', {'name': 'Alice'})
        received = socket_client.get_received()

        assert received[0]['name'] == 'spy_room_created'

        data = received[0]['args'][0]
        assert len(data['room_code']) == 4
        assert 'Alice' in data['players']
        assert data['settings']['spy_count'] == 1
        assert data['settings']['extra_roles'] is True

    @allure.story("Join an existing room")
    @allure.title("Second player joins - should broadcast spy_player_joined")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_join_room(self, socket_client, guest_client_factory):
        room_code = _create_room(socket_client)
        socket_client.get_received()

        guest = guest_client_factory()
        guest.emit('spy_join_room', {'room_code': room_code, 'name': 'Bob'})
        received = guest.get_received()

        assert 'spy_room_created' in _event_names_from_list(received)
        guest_data = next(e for e in received if e['name'] == 'spy_room_created')['args'][0]
        assert 'Bob' in guest_data['players']
        assert 'Bob' in rooms_game2[room_code]['players']

    @allure.story("Join a non-existent room")
    @allure.title("Invalid room code - should return error")
    @allure.severity(allure.severity_level.NORMAL)
    def test_join_nonexistent_room(self, socket_client):
        socket_client.emit('spy_join_room', {'room_code': 'XXXX', 'name': 'Bob'})
        received = socket_client.get_received()

        assert received[0]['name'] == 'error'
        assert 'Room not found' in received[0]['args'][0]['message']

    @allure.story("Rejoin with same name")
    @allure.title("Same name reconnects - should refresh session, not duplicate player")
    @allure.severity(allure.severity_level.NORMAL)
    def test_rejoin_same_name(self, socket_client):
        room_code = _create_room(socket_client)
        socket_client.get_received()

        socket_client.emit('spy_join_room', {'room_code': room_code, 'name': 'Alice'})
        socket_client.get_received()

        assert len(rooms_game2[room_code]['players']) == 1

    @allure.story("Duplicate player name")
    @allure.title("Second player cannot join with a name already in the room")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_duplicate_name_rejected(self, socket_client, guest_client_factory):
        room_code = _create_room(socket_client)
        socket_client.get_received()

        guest = guest_client_factory()
        guest.emit('spy_join_room', {'room_code': room_code, 'name': 'Alice'})
        received = guest.get_received()

        assert received[0]['name'] == 'error'
        assert 'already taken' in received[0]['args'][0]['message']
        assert len(rooms_game2[room_code]['players']) == 1

    @allure.story("Reconnect after disconnect")
    @allure.title("Disconnected player can reclaim their name")
    @allure.severity(allure.severity_level.NORMAL)
    def test_reconnect_after_disconnect(self):
        host = socketio.test_client(app)
        room_code = _create_room(host)
        host.get_received()

        host.disconnect()

        replacement = socketio.test_client(app)
        try:
            replacement.emit('spy_join_room', {'room_code': room_code, 'name': 'Alice'})
            received = replacement.get_received()
            created = next(e for e in received if e['name'] == 'spy_room_created')['args'][0]

            assert created.get('reconnect') is True
            assert len(rooms_game2[room_code]['players']) == 1
            assert rooms_game2[room_code]['players']['Alice']['sid'] is not None
        finally:
            try:
                replacement.disconnect()
            except RuntimeError:
                pass


def _event_names_from_list(received):
    return [e['name'] for e in received]


# ========================
# LOBBY RULES
# ========================

@allure.epic("Spy in Ithaca")
@allure.feature("Lobby Rules")
class TestSpyLobbyRules:

    @allure.story("Minimum players for one spy")
    @allure.title("Three players can start with spy_count=1")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_three_players_one_spy_ok(self, guest_client_factory):
        host = socketio.test_client(app)
        room_code = _create_room(host)
        _join(guest_client_factory(), room_code, 'Bob')
        _join(guest_client_factory(), room_code, 'Carol')

        host.emit('spy_start_game', {'room_code': room_code, **_default_start_payload()})
        time.sleep(0.1)
        received = host.get_received()

        assert 'error' not in _event_names_from_list(received)
        assert rooms_game2[room_code]['phase'] == 'role_reveal'
        host.disconnect()

    @allure.story("Minimum players for two spies")
    @allure.title("Three players cannot start with spy_count=2")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_three_players_two_spies_blocked(self, guest_client_factory):
        host = socketio.test_client(app)
        room_code = _create_room(host)
        _join(guest_client_factory(), room_code, 'Bob')
        _join(guest_client_factory(), room_code, 'Carol')
        host.get_received()

        host.emit('spy_start_game', {
            'room_code': room_code,
            **_default_start_payload(spy_count=2),
        })
        received = host.get_received()

        assert received[0]['name'] == 'error'
        assert 'at least 4 players' in received[0]['args'][0]['message']
        assert rooms_game2[room_code]['phase'] == 'waiting'
        host.disconnect()

    @allure.story("Minimum players for random spy count")
    @allure.title("Random spy mode needs four players")
    @allure.severity(allure.severity_level.NORMAL)
    def test_random_spy_mode_needs_four_players(self, guest_client_factory):
        host = socketio.test_client(app)
        room_code = _create_room(host)
        _join(guest_client_factory(), room_code, 'Bob')
        _join(guest_client_factory(), room_code, 'Carol')
        host.get_received()

        host.emit('spy_start_game', {
            'room_code': room_code,
            **_default_start_payload(spy_count=0),
        })
        received = host.get_received()

        assert received[0]['name'] == 'error'
        assert 'at least 4 players' in received[0]['args'][0]['message']
        host.disconnect()


# ========================
# GAME FLOW
# ========================

@allure.epic("Spy in Ithaca")
@allure.feature("Game Flow")
class TestSpyGameFlow:

    @allure.story("Role reveal to playing")
    @allure.title("All players ready - should emit spy_enter_game")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_all_ready_enters_game(self, guest_client_factory):
        host = socketio.test_client(app)
        bob = guest_client_factory()
        carol = guest_client_factory()
        room_code = _create_room(host)
        _join(bob, room_code, 'Bob')
        _join(carol, room_code, 'Carol')

        clients = [host, bob, carol]
        names = ['Alice', 'Bob', 'Carol']
        _start_role_reveal(clients, room_code)

        for client, name in zip(clients, names):
            client.emit('spy_role_ready', {'room_code': room_code, 'player_name': name})

        time.sleep(0.2)
        for client in clients:
            events = _event_names(client)
            assert 'spy_enter_game' in events

        assert rooms_game2[room_code]['phase'] == 'playing'
        host.disconnect()

    @allure.story("Private role payload")
    @allure.title("Civilian gets location, spy does not")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_role_assigned_differs_by_team(self, guest_client_factory):
        host = socketio.test_client(app)
        bob = guest_client_factory()
        carol = guest_client_factory()
        room_code = _create_room(host)
        _join(bob, room_code, 'Bob')
        _join(carol, room_code, 'Carol')

        clients = [host, bob, carol]
        clients[0].emit('spy_start_game', {
            'room_code': room_code,
            **_default_start_payload(),
        })
        time.sleep(0.15)

        payloads = {}
        for client, name in zip(clients, ['Alice', 'Bob', 'Carol']):
            role_events = _events(client, 'spy_role_assigned')
            assert role_events, f'{name} should get spy_role_assigned'
            payloads[name] = role_events[0]['args'][0]

        spy_payloads = [p for p in payloads.values() if p['is_spy']]
        civ_payloads = [p for p in payloads.values() if not p['is_spy']]
        assert len(spy_payloads) == 1
        assert len(civ_payloads) == 2
        assert 'location' not in spy_payloads[0]
        assert all('location' in p for p in civ_payloads)

        host.disconnect()

    @allure.story("Random spy count")
    @allure.title("spy_count=0 resolves to 1 or 2 on deal")
    @allure.severity(allure.severity_level.NORMAL)
    def test_random_spy_count_resolved(self, guest_client_factory):
        host = socketio.test_client(app)
        players = [host]
        room_code = _create_room(host)
        for name in ('Bob', 'Carol', 'Dave'):
            c = guest_client_factory()
            _join(c, room_code, name)
            players.append(c)

        _start_role_reveal(players, room_code, _default_start_payload(spy_count=0))

        resolved = rooms_game2[room_code]['resolved_spy_count']
        assert resolved in (1, 2)
        assert len(_spy_names(room_code)) == resolved
        host.disconnect()

    @allure.story("Mid-game join")
    @allure.title("Late joiner gets civilian role during an active round")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_mid_game_join_civilian(self, guest_client_factory):
        host = socketio.test_client(app)
        bob = guest_client_factory()
        carol = guest_client_factory()
        room_code = _create_room(host)
        _join(bob, room_code, 'Bob')
        _join(carol, room_code, 'Carol')

        clients = [host, bob, carol]
        _enter_playing(clients, room_code, ['Alice', 'Bob', 'Carol'])
        assert rooms_game2[room_code]['phase'] == 'playing'

        dave = guest_client_factory()
        dave.emit('spy_join_room', {'room_code': room_code, 'name': 'Dave'})
        time.sleep(0.1)
        received = dave.get_received()

        created = next(e for e in received if e['name'] == 'spy_room_created')['args'][0]
        assert created.get('mid_game') is True
        assert rooms_game2[room_code]['roles']['Dave']['is_spy'] is False

        role_events = [e for e in received if e['name'] == 'spy_role_assigned']
        assert role_events, 'Late joiner should receive civilian role'
        assert role_events[0]['args'][0]['location'] == rooms_game2[room_code]['secret_location']

        host.disconnect()


# ========================
# VOTING
# ========================

@allure.epic("Spy in Ithaca")
@allure.feature("Voting")
class TestSpyVoting:

    @allure.story("Vote nomination broadcast")
    @allure.title("spy_vote_nomination_started reaches every client")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_vote_nomination_reaches_all_players(self, guest_client_factory):
        host = socketio.test_client(app)
        bob = guest_client_factory()
        carol = guest_client_factory()
        room_code = _create_room(host)
        _join(bob, room_code, 'Bob')
        _join(carol, room_code, 'Carol')

        clients = [host, bob, carol]
        _enter_playing(clients, room_code, ['Alice', 'Bob', 'Carol'])

        host.emit('spy_start_vote', {'room_code': room_code, 'player_name': 'Alice'})
        time.sleep(0.15)

        for name, client in zip(['Alice', 'Bob', 'Carol'], clients):
            nominations = _events(client, 'spy_vote_nomination_started')
            assert nominations, f'{name} missed nomination event'
            assert nominations[0]['args'][0]['initiator'] == 'Alice'

        host.disconnect()

    @allure.story("Open voting phase")
    @allure.title("Nomination opens spy_vote_started for everyone")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_vote_started_reaches_all_players(self, guest_client_factory):
        host = socketio.test_client(app)
        bob = guest_client_factory()
        carol = guest_client_factory()
        room_code = _create_room(host)
        _join(bob, room_code, 'Bob')
        _join(carol, room_code, 'Carol')

        clients = [host, bob, carol]
        _enter_playing(clients, room_code, ['Alice', 'Bob', 'Carol'])

        host.emit('spy_start_vote', {'room_code': room_code, 'player_name': 'Alice'})
        time.sleep(0.1)
        for client in clients:
            client.get_received()

        host.emit('spy_nominate_accused', {
            'room_code': room_code,
            'player_name': 'Alice',
            'target': 'Bob',
        })
        time.sleep(0.15)

        for name, client in zip(['Alice', 'Bob', 'Carol'], clients):
            started = _events(client, 'spy_vote_started')
            assert started, f'{name} missed vote_started'
            payload = started[0]['args'][0]
            assert payload['accused'] == 'Bob'
            assert payload['initiator'] == 'Alice'

        host.disconnect()

    @allure.story("Unanimous vote on spy")
    @allure.title("Correct accusation ends round - civilians win")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_unanimous_vote_on_spy_civilians_win(self, guest_client_factory):
        host = socketio.test_client(app)
        bob = guest_client_factory()
        carol = guest_client_factory()
        room_code = _create_room(host)
        _join(bob, room_code, 'Bob')
        _join(carol, room_code, 'Carol')

        clients = [host, bob, carol]
        names = ['Alice', 'Bob', 'Carol']
        _enter_playing(clients, room_code, names)

        spy_name = _spy_names(room_code)[0]
        accusers = [n for n in names if n != spy_name]
        initiator = accusers[0]
        voter = accusers[1]
        initiator_client = clients[names.index(initiator)]
        voter_client = clients[names.index(voter)]

        initiator_client.emit('spy_start_vote', {
            'room_code': room_code,
            'player_name': initiator,
        })
        time.sleep(0.1)
        for client in clients:
            client.get_received()

        initiator_client.emit('spy_nominate_accused', {
            'room_code': room_code,
            'player_name': initiator,
            'target': spy_name,
        })
        time.sleep(0.1)
        for client in clients:
            client.get_received()

        # initiator already voted yes on server
        voter_client.emit('spy_cast_vote', {
            'room_code': room_code,
            'player_name': voter,
            'target': spy_name,
        })
        time.sleep(0.15)

        results = _events(voter_client, 'spy_round_result')
        assert results, 'Expected round result after unanimous yes'
        result = results[0]['args'][0]['result']
        assert result['winner'] == 'civilians'
        assert spy_name in result['message'] or 'found the spy' in result['message']
        assert rooms_game2[room_code]['phase'] == 'results'

        host.disconnect()

    @allure.story("Vote cancelled")
    @allure.title("One No vote resumes discussion")
    @allure.severity(allure.severity_level.NORMAL)
    def test_vote_cancelled_on_no(self, guest_client_factory):
        host = socketio.test_client(app)
        bob = guest_client_factory()
        carol = guest_client_factory()
        room_code = _create_room(host)
        _join(bob, room_code, 'Bob')
        _join(carol, room_code, 'Carol')

        clients = [host, bob, carol]
        names = ['Alice', 'Bob', 'Carol']
        _enter_playing(clients, room_code, names)

        host.emit('spy_start_vote', {'room_code': room_code, 'player_name': 'Alice'})
        time.sleep(0.1)
        for client in clients:
            client.get_received()

        host.emit('spy_nominate_accused', {
            'room_code': room_code,
            'player_name': 'Alice',
            'target': 'Bob',
        })
        time.sleep(0.1)
        for client in clients:
            client.get_received()

        carol.emit('spy_vote_no', {
            'room_code': room_code,
            'player_name': 'Carol',
            'target': 'Bob',
        })
        time.sleep(0.15)

        cancelled = _events(carol, 'spy_vote_cancelled')
        assert cancelled, 'Expected vote cancel event'
        assert rooms_game2[room_code]['phase'] == 'playing'

        host.disconnect()

    @allure.story("Hidden spy count in random mode")
    @allure.title("During vote, clients get spy_count=0 when mode is random")
    @allure.severity(allure.severity_level.NORMAL)
    def test_random_mode_hides_spy_count_during_vote(self, guest_client_factory):
        host = socketio.test_client(app)
        players = [host]
        names = ['Alice', 'Bob', 'Carol', 'Dave']
        room_code = _create_room(host)
        for name in names[1:]:
            c = guest_client_factory()
            _join(c, room_code, name)
            players.append(c)

        _enter_playing(players, room_code, names, _default_start_payload(spy_count=0))

        host.emit('spy_start_vote', {'room_code': room_code, 'player_name': 'Alice'})
        time.sleep(0.1)
        host.get_received()

        host.emit('spy_nominate_accused', {
            'room_code': room_code,
            'player_name': 'Alice',
            'target': 'Bob',
        })
        time.sleep(0.15)

        started = _events(host, 'spy_vote_started')[0]['args'][0]
        assert started['spy_count'] == 0

        host.disconnect()

    @allure.story("Voter disconnect")
    @allure.title("Vote continues when a player disconnects without voting")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_vote_continues_after_voter_disconnect(self, guest_client_factory):
        host = socketio.test_client(app)
        bob = guest_client_factory()
        carol = guest_client_factory()
        room_code = _create_room(host)
        _join(bob, room_code, 'Bob')
        _join(carol, room_code, 'Carol')

        clients = [host, bob, carol]
        names = ['Alice', 'Bob', 'Carol']
        _enter_playing(clients, room_code, names)

        spy_name = _spy_names(room_code)[0]
        initiator = [n for n in names if n != spy_name][0]
        initiator_client = clients[names.index(initiator)]
        voter_name = [n for n in names if n != spy_name and n != initiator][0]
        voter_client = clients[names.index(voter_name)]

        initiator_client.emit('spy_start_vote', {
            'room_code': room_code,
            'player_name': initiator,
        })
        time.sleep(0.1)
        for client in clients:
            client.get_received()

        initiator_client.emit('spy_nominate_accused', {
            'room_code': room_code,
            'player_name': initiator,
            'target': spy_name,
        })
        time.sleep(0.1)
        for client in clients:
            client.get_received()

        initiator_client.get_received()

        voter_client.disconnect()
        time.sleep(0.2)

        post_disconnect = initiator_client.get_received()
        left_events = [e for e in post_disconnect if e['name'] == 'spy_vote_player_left']
        assert left_events, 'Expected vote continues notification'
        assert voter_name in left_events[0]['args'][0]['message']
        assert voter_name not in rooms_game2[room_code]['players']

        results = [e for e in post_disconnect if e['name'] == 'spy_round_result']
        assert results, 'Vote should resolve after voter leaves'
        assert results[0]['args'][0]['result']['winner'] == 'civilians'

        for client in clients:
            if client is not voter_client:
                try:
                    client.disconnect()
                except RuntimeError:
                    pass


# ========================
# HTTP ROUTES
# ========================

@allure.epic("Spy in Ithaca")
@allure.feature("HTTP Routes")
class TestSpyRoutes:

    @pytest.fixture
    def http_client(self):
        with app.test_client() as client:
            yield client

    @allure.story("Game page loads")
    @allure.title("GET /spy-in-ithaca/game should return 200")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_game_page_loads(self, http_client):
        response = http_client.get('/spy-in-ithaca/game')
        assert response.status_code == 200

    @allure.story("Room URL loads")
    @allure.title("GET /spy-in-ithaca/<code> should return 200")
    @allure.severity(allure.severity_level.NORMAL)
    def test_room_page_loads(self, http_client):
        response = http_client.get('/spy-in-ithaca/ABCD')
        assert response.status_code == 200

    @allure.story("Locations API")
    @allure.title("GET /api/spy-in-ithaca/locations returns location sets")
    @allure.severity(allure.severity_level.NORMAL)
    def test_locations_api(self, http_client):
        response = http_client.get('/api/spy-in-ithaca/locations')
        assert response.status_code == 200
        data = response.get_json()
        assert 'myths' in data
        assert 'odyssey' in data
        assert 'modern_world' in data
