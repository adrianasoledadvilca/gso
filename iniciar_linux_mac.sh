#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Preparando el sistema por primera vez..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/python app.py
