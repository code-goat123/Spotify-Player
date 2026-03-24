#!/usr/bin/env python3
"""
Entry point for local / Raspberry Pi runs.

Production-ish Pi usage (example):
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  cp .env.example .env  # then edit
  python run.py

TODO: On-device, prefer a systemd unit + wait-for-network; see README.
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config.get("DEBUG", False),
        use_reloader=app.config.get("DEBUG", False),
    )
