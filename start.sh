#!/usr/bin/env bash
# Local dev for the dashboard + API. No SSH tunnel needed anymore — this talks
# straight to the (managed) Postgres in DATABASE_URL. Set it in a local .env
# (see .env.example) or export it before running.
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV="${VENV:-.venv-api}"
if [ ! -d "$VENV" ]; then
  echo "▶ Creating virtualenv ($VENV)…"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -r api/requirements.txt uvicorn
fi

# Load .env if present (DATABASE_URL, etc.)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

echo "▶ Dashboard + API at http://localhost:8000"
echo "   (serving index.html and /api/* from api/index.py)"
echo ""
exec "$VENV/bin/uvicorn" api.index:app --host 0.0.0.0 --port 8000 --reload
