#!/usr/bin/env bash
# Cron-friendly wrapper: fetch one batch of quotes, store, and print.
set -euo pipefail

# Resolve project root regardless of where cron invokes us from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

# Activate a local virtualenv if present.
if [[ -f ".venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source ".venv/bin/activate"
fi

exec python -m src.main "$@"
