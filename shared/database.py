# Database functions shared across all games

import sqlite3
import json

DB_PATH = 'game.db'

# Runtime-only fields kept in memory but never persisted.
_NON_SERIALIZABLE_ROOM_KEYS = frozenset({'timer_thread', 'question_thread'})


def init_db():
    """Create the database tables if they don't exist yet."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS rooms (
        room_code TEXT PRIMARY KEY,
        host_token TEXT,
        game_started INTEGER DEFAULT 0,
        data TEXT
    )''')
    conn.commit()
    conn.close()
    print("Database initialized.")


def save_room_to_db(room_code, rooms):
    """Save a single room's data to the database."""
    if room_code not in rooms:
        return
    room = rooms[room_code]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''INSERT OR REPLACE INTO rooms (room_code, host_token, game_started, data)
                      VALUES (?, ?, ?, ?)''',
                   (room_code,
                    room.get('host_token'),
                    int(room.get('game_started', False)),
                    json.dumps({
                        k: v for k, v in room.items()
                        if k not in _NON_SERIALIZABLE_ROOM_KEYS
                    })))
    conn.commit()
    conn.close()


def load_rooms_from_db():
    """Load all saved rooms from the database into memory. Returns a dict."""
    rooms = {}
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT room_code, data FROM rooms')
    for row in cursor.fetchall():
        room_code = row[0]
        room_data = json.loads(row[1])
        rooms[room_code] = room_data
        print(f"Loaded room: {room_code}")
    conn.close()
    return rooms