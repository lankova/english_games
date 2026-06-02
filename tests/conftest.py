import pytest
import sys
import os

# Add project root to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, socketio, rooms


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
    """Clear rooms before each test."""
    rooms.clear()
