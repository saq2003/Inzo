#!/usr/bin/env bash
# Developer startup command: creates a venv, installs deps, runs INZO.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "Created .env from .env.example (edit it to add provider keys)."
fi

exec .venv/bin/python -m inzo
