"""
REST-style API consumed by the kiosk frontend.

Implemented:
  - GET /api/playback — normalized now-playing + progress
  - POST /api/playback/toggle — play/pause
  - POST /api/playback/seek — relative seek in milliseconds (JSON body)

TODO (Pi + production hardening):
  - Optional API key / localhost-only middleware when bound to 0.0.0.0
  - Rate-limit seek endpoint to protect Spotify quota and avoid UI fighting the API
  - WebSocket push for playback updates (optional; polling is fine for v1)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from app.services.spotify_service import build_spotify_service

log = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")

_service_cache: dict[str, Any] = {"svc": None, "cfg_id": None}
_seek_lock = threading.Lock()
_last_seek_mono: float = 0.0


def _service():
    """Single service instance per process; rebuild if config identity changes."""
    cfg = current_app.config
    cfg_id = (
        cfg.get("SPOTIFY_USE_MOCK"),
        cfg.get("SPOTIFY_CLIENT_ID"),
        cfg.get("SPOTIFY_REFRESH_TOKEN"),
        bool(cfg.get("SPOTIFY_ACCESS_TOKEN")),
    )
    if _service_cache["svc"] is None or _service_cache["cfg_id"] != cfg_id:
        _service_cache["svc"] = build_spotify_service(cfg)
        _service_cache["cfg_id"] = cfg_id
    return _service_cache["svc"]


@api_bp.get("/playback")
def get_playback():
    svc = _service()
    return jsonify(svc.get_playback_state())


@api_bp.post("/playback/toggle")
def toggle_playback():
    svc = _service()
    result = svc.toggle_playback()
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@api_bp.post("/playback/seek")
def seek_playback():
    """
    Body: { "delta_ms": number }

    Throttle: coalesce rapid ring gestures (first-pass; tune after hardware tests).
    """
    global _last_seek_mono
    data = request.get_json(silent=True) or {}
    try:
        delta = int(data.get("delta_ms", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_delta_ms"}), 400

    if delta == 0:
        return jsonify({"ok": True, "skipped": True})

    # TODO: Make interval configurable via env after measuring gesture noise on the round DSI panel
    min_interval_s = 0.35
    now = time.monotonic()
    with _seek_lock:
        if now - _last_seek_mono < min_interval_s:
            return jsonify({"ok": True, "throttled": True, "delta_ms": delta})
        _last_seek_mono = now

    svc = _service()
    result = svc.seek_by_ms(delta)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@api_bp.get("/health")
def health():
    cfg = current_app.config
    return jsonify(
        {
            "ok": True,
            "mock": bool(cfg.get("SPOTIFY_USE_MOCK")),
            "env": cfg.get("ENV"),
        }
    )
