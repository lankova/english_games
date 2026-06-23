"""Settings for tests against the live site (https://lankova.tech).

After you deploy files to a new VPS, the domain stays the same - just run:

    set LIVE_TESTS_OK=1
    python -m pytest tests/test_live_server.py -v -s

LIVE_GAME_SERVER_URL is only needed for a temporary/staging host.
"""
import os

_DEFAULT_URL = "https://lankova.tech"


def _env_bool(name, default=False):
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return int(raw)


# Default live site. Override only for staging or a direct IP test.
LIVE_GAME_SERVER_URL = os.environ.get("LIVE_GAME_SERVER_URL", _DEFAULT_URL).rstrip("/")
# Safety switch - live tests are skipped unless this is set.
LIVE_TESTS_OK = _env_bool("LIVE_TESTS_OK", False)

# Set to 0 if the new server uses a self-signed HTTPS certificate.
LIVE_SSL_VERIFY = _env_bool("LIVE_SSL_VERIFY", True)

LIVE_LOAD_ROOMS = _env_int("LIVE_LOAD_ROOMS", 10)
LIVE_LOAD_PLAYERS = _env_int("LIVE_LOAD_PLAYERS", 15)
LIVE_EVENT_TIMEOUT = _env_int("LIVE_EVENT_TIMEOUT", 20)
# Spy role flow on a real server needs more time under load.
LIVE_SPY_EVENT_TIMEOUT = _env_int("LIVE_SPY_EVENT_TIMEOUT", 60)

# How many rooms to set up at once (lower = gentler on the server).
LIVE_LOAD_PARALLEL = _env_int("LIVE_LOAD_PARALLEL", 5)
LIVE_SPY_LOAD_PARALLEL = _env_int("LIVE_SPY_LOAD_PARALLEL", 2)
# Pause between each OK click on the live server (seconds).
LIVE_SPY_ROLE_READY_PAUSE = float(os.environ.get("LIVE_SPY_ROLE_READY_PAUSE", "0.1"))

# Comma-separated list, e.g. "polling" or "polling,websocket"
_raw_transports = os.environ.get("LIVE_TRANSPORTS", "polling")
LIVE_TRANSPORTS = [t.strip() for t in _raw_transports.split(",") if t.strip()]
