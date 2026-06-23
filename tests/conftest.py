import pytest
import sys
import os

# Add project root to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, socketio, rooms_game1, rooms_game2


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "load: slow multi-room load tests (10 rooms x 15 players)",
    )
    config.addinivalue_line(
        "markers",
        "live: tests against a running server (set LIVE_TESTS_OK=1)",
    )


@pytest.fixture
def test_app():
    """Flask test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def socket_client():
    """SocketIO test client - each test gets a fresh connection."""
    client = socketio.test_client(app)
    yield client
    client.disconnect()


@pytest.fixture(autouse=True)
def clear_rooms():
    """Clear room state before each test.
    This runs in a SEPARATE test process - it will NOT touch
    real rooms on the live server. Only the test copies of
    rooms_game1 and rooms_game2 are cleared.
    """
    rooms_game1.clear()
    rooms_game2.clear()
