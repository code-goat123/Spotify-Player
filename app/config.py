"""
Configuration loaded from environment.

Implemented: host/port, Spotify-related env vars, mock fallback flag.
Planned: per-device paths for kiosk browser profile, optional TLS termination behind nginx.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> dict:
    env = os.getenv("FLASK_ENV", "development")
    debug = env != "production"

    host = os.getenv("FLASK_RUN_HOST", "127.0.0.1")
    port_raw = os.getenv("FLASK_RUN_PORT", "8765")
    try:
        port = int(port_raw)
    except ValueError:
        port = 8765

    use_mock = _bool_env("SPOTIFY_USE_MOCK", False)
    client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip()
    refresh = (os.getenv("SPOTIFY_REFRESH_TOKEN") or "").strip()
    access = (os.getenv("SPOTIFY_ACCESS_TOKEN") or "").strip()

    # Auto-mock when nothing usable is configured (still overridable explicitly).
    credentials_ok = bool(access) or (
        bool(client_id) and bool(client_secret) and bool(refresh)
    )
    if not credentials_ok:
        use_mock = True

    return {
        "ENV": env,
        "DEBUG": debug,
        "HOST": host,
        "PORT": port,
        "SPOTIFY_CLIENT_ID": client_id,
        "SPOTIFY_CLIENT_SECRET": client_secret,
        "SPOTIFY_REFRESH_TOKEN": refresh,
        "SPOTIFY_ACCESS_TOKEN": access,
        "SPOTIFY_REDIRECT_URI": (
            os.getenv("SPOTIFY_REDIRECT_URI") or "http://127.0.0.1:8765/callback"
        ).strip(),
        "SPOTIFY_USE_MOCK": use_mock,
    }
