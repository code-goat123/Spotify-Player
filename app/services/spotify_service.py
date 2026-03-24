"""
Spotify Web API integration layer.

Implemented:
  - Access token via optional SPOTIFY_ACCESS_TOKEN or refresh_token exchange
  - GET /v1/me/player for combined playback + currently playing
  - Play/pause toggle via PUT /v1/me/player/play|pause
  - Seek via PUT /v1/me/player/seek
  - Mock playback payload when credentials are missing or SPOTIFY_USE_MOCK=true

Planned / TODO (needs device + real account testing):
  - Full authorization-code flow hosted on the Pi (currently: refresh/access token via .env)
  - Token persistence with file-backed storage and rotation
  - Exponential backoff on 429; finer handling of 204 empty player
  - Debounced seek: batch rapid ring gestures (see api routes)
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)

SPOTIFY_ACCOUNTS = "https://accounts.spotify.com"
SPOTIFY_API = "https://api.spotify.com/v1"

# Shared mock album art (real CDN image, stable for offline UI dev).
MOCK_ALBUM_ART_URL = (
    "https://i.scdn.co/image/ab67616d0000b273bb87f32c3c58525dff0f3e14"
)


@dataclass
class SpotifyService:
    client_id: str
    client_secret: str
    refresh_token: str
    access_token: str
    redirect_uri: str
    use_mock: bool

    def __post_init__(self) -> None:
        self._token_lock = threading.Lock()
        self._cached_access_token: str | None = None
        self._access_expires_at: float = 0.0
        self._mock_is_playing: bool = True
        self._mock_progress_ms: int = 42_000
        self._mock_last_toggle: float = time.monotonic()

    def get_playback_state(self) -> dict[str, Any]:
        """Returns a normalized dict for the frontend (see routes for schema)."""
        if self.use_mock:
            return self._mock_playback_payload()

        token = self._get_valid_access_token()
        if not token:
            log.warning("No valid Spotify token; falling back to mock playback.")
            return self._mock_playback_payload()

        r = requests.get(
            f"{SPOTIFY_API}/me/player",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code == 204:
            # Nothing playing — return idle shape the UI understands.
            return self._empty_playback_payload()
        if r.status_code == 401:
            log.warning("Spotify 401; clearing cached token.")
            with self._token_lock:
                self._cached_access_token = None
                self._access_expires_at = 0.0
            return self._empty_playback_payload()
        if not r.ok:
            log.error("Spotify player GET failed: %s %s", r.status_code, r.text[:500])
            return self._empty_playback_payload()

        data = r.json()
        return self._normalize_player_json(data)

    def toggle_playback(self) -> dict[str, Any]:
        if self.use_mock:
            self._mock_last_toggle = time.monotonic()
            self._mock_is_playing = not self._mock_is_playing
            return {"ok": True, "mock": True, "is_playing": self._mock_is_playing}

        token = self._get_valid_access_token()
        if not token:
            return {"ok": False, "error": "no_token"}

        state = requests.get(
            f"{SPOTIFY_API}/me/player",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if state.status_code in (204, 401):
            return {"ok": False, "error": "no_active_device"}
        if not state.ok:
            return {"ok": False, "error": f"player_http_{state.status_code}"}

        playing = bool(state.json().get("is_playing"))
        endpoint = "pause" if playing else "play"
        # TODO: If PUT returns 404 "No active device", pass ?device_id= from player JSON after Pi tests.
        r = requests.put(
            f"{SPOTIFY_API}/me/player/{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        # Spotify returns 204 on success
        ok = r.status_code in (200, 204)
        return {"ok": ok, "is_playing": not playing if ok else playing}

    def seek_by_ms(self, delta_ms: int) -> dict[str, Any]:
        """
        Relative seek. Positive = forward.

        TODO: Hardware test seek granularity on Pi + phone remote interference
        TODO: If no active device, surface explicit error to UI
        """
        if self.use_mock:
            self._mock_last_toggle = time.monotonic()
            dur = 245_000
            self._mock_progress_ms = max(
                0, min(dur, self._mock_progress_ms + int(delta_ms))
            )
            return {"ok": True, "mock": True, "progress_ms": self._mock_progress_ms}

        token = self._get_valid_access_token()
        if not token:
            return {"ok": False, "error": "no_token"}

        r = requests.get(
            f"{SPOTIFY_API}/me/player",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code != 200:
            return {"ok": False, "error": "no_player_state"}
        data = r.json()
        cur = int(data.get("progress_ms") or 0)
        item = data.get("item") or {}
        duration = int(item.get("duration_ms") or 0)
        target = max(0, min(duration, cur + int(delta_ms)))

        rs = requests.put(
            f"{SPOTIFY_API}/me/player/seek",
            headers={"Authorization": f"Bearer {token}"},
            params={"position_ms": target},
            timeout=10,
        )
        ok = rs.status_code in (200, 204)
        return {"ok": ok, "position_ms": target if ok else cur}

    # --- internals ---

    def _get_valid_access_token(self) -> str | None:
        static = (self.access_token or "").strip()
        if static:
            return static

        if not (
            self.client_id and self.client_secret and self.refresh_token
        ):
            return None

        now = time.time()
        with self._token_lock:
            if self._cached_access_token and now < self._access_expires_at - 30:
                return self._cached_access_token
            refreshed = self._refresh_access_token()
            if not refreshed:
                return None
            self._cached_access_token = refreshed["access_token"]
            # Spotify returns expires_in (seconds)
            ttl = float(refreshed.get("expires_in") or 3600)
            self._access_expires_at = now + ttl
            return self._cached_access_token

    def _refresh_access_token(self) -> dict[str, Any] | None:
        r = requests.post(
            f"{SPOTIFY_ACCOUNTS}/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if not r.ok:
            log.error("Token refresh failed: %s %s", r.status_code, r.text[:500])
            return None
        return r.json()

    def _normalize_player_json(self, data: dict[str, Any]) -> dict[str, Any]:
        item = data.get("item") or {}
        album = item.get("album") or {}
        images = album.get("images") or []
        art_url = images[0]["url"] if images else None
        artists = item.get("artists") or []
        artist_names = [a.get("name") for a in artists if a.get("name")]

        return {
            "is_playing": bool(data.get("is_playing")),
            "progress_ms": int(data.get("progress_ms") or 0),
            "duration_ms": int(item.get("duration_ms") or 0),
            "track": {
                "name": item.get("name") or "Unknown track",
                "artists": artist_names,
                "album": album.get("name") or "",
            },
            "album_art_url": art_url,
            "device_name": (data.get("device") or {}).get("name"),
            "mock": False,
            "timestamp": int(time.time() * 1000),
        }

    def _empty_playback_payload(self) -> dict[str, Any]:
        return {
            "is_playing": False,
            "progress_ms": 0,
            "duration_ms": 0,
            "track": {"name": "Nothing playing", "artists": [], "album": ""},
            "album_art_url": None,
            "device_name": None,
            "mock": False,
            "timestamp": int(time.time() * 1000),
        }

    def _mock_playback_payload(self) -> dict[str, Any]:
        # Advance mock progress while "playing" so the progress bar moves without polling Spotify.
        now = time.monotonic()
        elapsed_ms = int(max(0, (now - self._mock_last_toggle)) * 1000)
        dur = 245_000
        if self._mock_is_playing:
            self._mock_progress_ms = (self._mock_progress_ms + elapsed_ms) % max(
                dur, 1
            )
        self._mock_last_toggle = now

        return {
            "is_playing": self._mock_is_playing,
            "progress_ms": self._mock_progress_ms,
            "duration_ms": dur,
            "track": {
                "name": "Satellite",
                "artists": ["Harry Styles"],
                "album": "Harry's House",
            },
            "album_art_url": MOCK_ALBUM_ART_URL,
            "device_name": "Mock Pi Touch Display",
            "mock": True,
            "timestamp": int(time.time() * 1000),
        }


def build_spotify_service(app_config: dict) -> SpotifyService:
    return SpotifyService(
        client_id=str(app_config.get("SPOTIFY_CLIENT_ID") or ""),
        client_secret=str(app_config.get("SPOTIFY_CLIENT_SECRET") or ""),
        refresh_token=str(app_config.get("SPOTIFY_REFRESH_TOKEN") or ""),
        access_token=str(app_config.get("SPOTIFY_ACCESS_TOKEN") or ""),
        redirect_uri=str(app_config.get("SPOTIFY_REDIRECT_URI") or ""),
        use_mock=bool(app_config.get("SPOTIFY_USE_MOCK")),
    )
