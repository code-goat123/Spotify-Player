# Spotify-Player — Pi Round Touch Kiosk (prototype)

## Prototype note

This repository is an **in-progress prototype** for a wall-powered **Raspberry Pi** music station: a **720×720 circular touchscreen** (Waveshare 4″ round DSI) running **Raspberry Pi OS**, showing **now-playing** artwork and metadata from **Spotify**, with **tap-to-play/pause** and an **outer-ring jog** gesture for seeking. The backend is **Flask**; the UI is a **kiosk-style web front end** intended for full-screen Chromium.

The code is structured for a real hardware bring-up: service layer, HTTP API, and a separated gesture module. Some behaviors are **stubbed or TODO** where only on-device testing can validate timing, bezel geometry, and Spotify device selection.

## Current feature status (honest checklist)

| Area | Status |
|------|--------|
| Flask app + `/api/*` JSON | Implemented |
| Spotify: player GET, play/pause, seek | Implemented (needs user token) |
| Auto-fallback **mock playback** without credentials | Implemented |
| Circular **720×720** layout + progress ring | Implemented |
| **Tap** play/pause (short, low-motion press) | Implemented |
| **5s idle** dim + smaller title; tap wakes | Implemented |
| **Idle** slow album rotation (CSS) | Implemented |
| **Outer ring** clockwise / CCW → seek chunks | Implemented (throttled server-side) |
| OAuth login page on the Pi | **Not implemented** — use `.env` tokens for now |
| Kiosk autostart systemd unit | Documented only (see below) |

## Repository layout

```
Spotify-Player/
├── README.md
├── requirements.txt
├── .env.example
├── run.py                 # python entry (dev / Pi)
├── app/
│   ├── __init__.py        # Flask factory + blueprint registration
│   ├── config.py          # env → app config (incl. mock fallback)
│   ├── routes/
│   │   └── api.py         # HTTP routes → service calls
│   └── services/
│       └── spotify_service.py   # Spotify Web API + mock payloads
├── templates/
│   └── index.html         # single-page kiosk shell
└── static/
    ├── css/main.css       # circular UI, idle transitions, idle spin
    └── js/
        ├── app.js         # polling, DOM, API, timers
        └── gestures.js    # ring hit-test, angle unwrap, tap vs spin
```

## Quick start (development machine)

```bash
cd Spotify-Player
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Leave Spotify vars empty to run in mock mode, or set SPOTIFY_USE_MOCK=true
python run.py
```

Open `http://127.0.0.1:8765/`.

### Spotify credentials (first pass)

Spotify **playback control** requires a **user** access token with the right scopes. This prototype expects one of:

1. **`SPOTIFY_ACCESS_TOKEN`** — quick manual copy (expires ~1h), **or**
2. **`SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` + `SPOTIFY_REFRESH_TOKEN`** — backend refreshes access tokens.

Generating a refresh token is a one-time OAuth step (any small helper script or Postman flow is fine). **TODO:** add a minimal auth route on the Pi for a classroom-friendly setup.

If nothing usable is configured, **`SPOTIFY_USE_MOCK` is effectively forced on** so the UI still runs.

## API (frontend ↔ backend)

| Method | Path | Body | Purpose |
|--------|------|------|---------|
| `GET` | `/api/playback` | — | Normalized now-playing + progress |
| `POST` | `/api/playback/toggle` | — | Play/pause |
| `POST` | `/api/playback/seek` | `{ "delta_ms": 5000 }` | Relative seek |
| `GET` | `/api/health` | — | Process health + mock flag |

Seek calls are **lightly throttled** in `app/routes/api.py` to avoid hammering the API during fast spins—tune after hardware tests.

## Gesture notes (Waveshare round DSI)

- **Ring** active between **62%** and **~98.5%** of the circular radius (see `static/js/app.js` and `static/js/gestures.js`). **TODO:** adjust ratios after measuring finger comfort and the visible LCD circle.
- **Tap** classification: short duration, movement under ~16px, no accumulated spin.
- **Debug overlay:** `Ctrl/Cmd + D` toggles a small ring state readout (`ring-debug` in `index.html`).

## Kiosk mode on the Pi (example only)

**TODO:** validate flags on your Chromium build; this is a starting point, not verified on every Pi OS revision.

```bash
chromium-browser \
  --kiosk \
  --window-size=720,720 \
  --app=http://127.0.0.1:8765/
```

Also **TODO:** `systemd` service for `run.py`, `graphical-session` target, and **on-screen keyboard** decisions (likely none for music control only).

## Coding-course realism

The project intentionally reads like **substantial mid-quarter progress**: clear separation of concerns, working mock path, and explicit **TODO** comments where the physical panel and Spotify account quirks matter more than desk development.
