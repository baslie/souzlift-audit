#!/bin/bash
set -euo pipefail

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
MANAGE_PY="${MANAGE_PY:-$PROJECT_ROOT/backend/manage.py}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings}"

if [[ -n "${VENV_PATH:-}" ]]; then
  PYTHON_BIN="$VENV_PATH/bin/python"
fi

if [[ ! -f "$MANAGE_PY" ]]; then
  echo "manage.py not found at $MANAGE_PY" >&2
  exit 1
fi

export DJANGO_SETTINGS_MODULE
log "Running clearsessions via $PYTHON_BIN $MANAGE_PY"
"$PYTHON_BIN" "$MANAGE_PY" clearsessions "$@"
log "Session cleanup completed"
