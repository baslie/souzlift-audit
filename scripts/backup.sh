#!/bin/bash
set -euo pipefail

# Souzlift backup script
# Creates timestamped archives of the SQLite database and media directory.

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
BACKUP_ROOT="${BACKUP_ROOT:-$PROJECT_ROOT/backups}"
DB_PATH="${DB_PATH:-$PROJECT_ROOT/backend/db/db.sqlite3}"
MEDIA_PATH="${MEDIA_PATH:-$PROJECT_ROOT/backend/media}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
SQLITE3_BIN="${SQLITE3_BIN:-sqlite3}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
TARGET_DIR="$BACKUP_ROOT/$TIMESTAMP"
DB_TARGET="$TARGET_DIR/db.sqlite3"
MEDIA_TARGET="$TARGET_DIR/media"
MANIFEST_FILE="$TARGET_DIR/manifest.json"

log "Starting backup run"
log "Project root: $PROJECT_ROOT"
log "Backup root: $BACKUP_ROOT"

if [[ ! -f "$DB_PATH" ]]; then
  log "ERROR: Database file not found at $DB_PATH"
  exit 1
fi

if [[ ! -d "$BACKUP_ROOT" ]]; then
  log "Creating backup root $BACKUP_ROOT"
  mkdir -p "$BACKUP_ROOT"
fi

mkdir -p "$TARGET_DIR"

log "Backing up SQLite database"
if command -v "$SQLITE3_BIN" >/dev/null 2>&1; then
  "$SQLITE3_BIN" "$DB_PATH" ".backup '$DB_TARGET'"
elif command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  "$PYTHON_BIN" - <<'PY' "$DB_PATH" "$DB_TARGET"
import sqlite3
import sys
source, target = sys.argv[1:3]
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
PY
else
  log "WARNING: sqlite3 and python3 binaries not found; falling back to cp"
  cp -p "$DB_PATH" "$DB_TARGET"
fi

log "Database backup created at $DB_TARGET"

if [[ -d "$MEDIA_PATH" ]]; then
  log "Backing up media from $MEDIA_PATH"
  mkdir -p "$MEDIA_TARGET"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete -- "$MEDIA_PATH/" "$MEDIA_TARGET/"
  else
    log "rsync not available; using tar pipeline fallback"
    (cd "$MEDIA_PATH" && tar -cf - .) | (cd "$MEDIA_TARGET" && tar -xf -)
  fi
  log "Media backup completed"
else
  log "WARNING: Media directory $MEDIA_PATH not found; creating empty placeholder"
  mkdir -p "$MEDIA_TARGET"
fi

log "Writing manifest"
if DB_SIZE=$(stat -c %s "$DB_TARGET" 2>/dev/null); then
  :
elif DB_SIZE=$(stat -f %z "$DB_TARGET" 2>/dev/null); then
  :
else
  DB_SIZE=0
fi

if MEDIA_SIZE=$(du -sb "$MEDIA_TARGET" 2>/dev/null | awk '{print $1}'); then
  :
else
  MEDIA_SIZE_BLOCKS=$(du -sk "$MEDIA_TARGET" 2>/dev/null | awk '{print $1}')
  if [[ "$MEDIA_SIZE_BLOCKS" =~ ^[0-9]+$ ]]; then
    MEDIA_SIZE=$((MEDIA_SIZE_BLOCKS * 1024))
  else
    MEDIA_SIZE=0
  fi
fi
if CREATED_AT=$(date --iso-8601=seconds 2>/dev/null); then
  :
else
  CREATED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
fi
cat <<JSON > "$MANIFEST_FILE"
{
  "created_at": "${CREATED_AT}",
  "project_root": "${PROJECT_ROOT}",
  "database": {
    "source": "${DB_PATH}",
    "target": "${DB_TARGET}",
    "size_bytes": ${DB_SIZE}
  },
  "media": {
    "source": "${MEDIA_PATH}",
    "target": "${MEDIA_TARGET}",
    "size_bytes": ${MEDIA_SIZE}
  }
}
JSON

log "Updating latest symlink"
ln -sfn "$TARGET_DIR" "$BACKUP_ROOT/latest"

if [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  log "Cleaning backups older than $RETENTION_DAYS days"
  find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" ! -name latest -print0 \
    | while IFS= read -r -d '' old_dir; do
        log "Removing old backup $old_dir"
        rm -rf "$old_dir"
      done
else
  log "Skipping cleanup: RETENTION_DAYS is not numeric ($RETENTION_DAYS)"
fi

log "Backup completed successfully"
