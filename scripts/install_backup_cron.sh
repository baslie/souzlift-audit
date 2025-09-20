#!/bin/bash
set -euo pipefail

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="${BACKUP_SCRIPT:-$SCRIPT_DIR/backup.sh}"
SCHEDULE="${SCHEDULE:-0 2 * * *}"
LOG_FILE="${LOG_FILE:-/var/log/souzlift/backup.log}"
CRONTAB_BIN="${CRONTAB_BIN:-crontab}"
DRY_RUN="${DRY_RUN:-false}"

LOG_DIR="$(dirname "$LOG_FILE")"
if [[ ! -d "$LOG_DIR" ]]; then
  if mkdir -p "$LOG_DIR" 2>/dev/null; then
    log "Created log directory $LOG_DIR"
  else
    log "WARNING: Unable to create log directory $LOG_DIR; please create it manually"
  fi
fi

if [[ ! -x "$BACKUP_SCRIPT" ]]; then
  log "ERROR: Backup script $BACKUP_SCRIPT is not executable"
  exit 1
fi

if ! command -v "$CRONTAB_BIN" >/dev/null 2>&1; then
  log "ERROR: $CRONTAB_BIN command not found"
  exit 1
fi

TMP_CRON=$(mktemp)
TMP_FILTERED="${TMP_CRON}.filtered"
trap 'rm -f "$TMP_CRON" "$TMP_FILTERED"' EXIT

if ! "$CRONTAB_BIN" -l >"$TMP_CRON" 2>/dev/null; then
  : >"$TMP_CRON"
fi

grep -vF -- "$BACKUP_SCRIPT" "$TMP_CRON" >"$TMP_FILTERED" || true
mv "$TMP_FILTERED" "$TMP_CRON"

echo "$SCHEDULE $BACKUP_SCRIPT >> $LOG_FILE 2>&1" >>"$TMP_CRON"

if [[ "$DRY_RUN" == "true" ]]; then
  log "Dry run enabled; resulting crontab would be:"
  cat "$TMP_CRON"
  exit 0
fi

"$CRONTAB_BIN" "$TMP_CRON"
log "Cron job installed: $SCHEDULE $BACKUP_SCRIPT >> $LOG_FILE 2>&1"
