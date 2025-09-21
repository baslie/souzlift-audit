#!/bin/bash
set -euo pipefail

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TARGET_PATH="${TARGET_PATH:-$PROJECT_ROOT}"
MEDIA_PATH="${MEDIA_PATH:-$PROJECT_ROOT/backend/media}"
WARN_THRESHOLD="${WARN_THRESHOLD:-80}"
CRITICAL_THRESHOLD="${CRITICAL_THRESHOLD:-90}"

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Project root not found at $PROJECT_ROOT" >&2
  exit 2
fi

df_line=$(df -P "$TARGET_PATH" | tail -n 1)
if [[ -z "$df_line" ]]; then
  echo "Unable to read disk usage for $TARGET_PATH" >&2
  exit 2
fi

filesystem=$(awk '{print $1}' <<<"$df_line")
size_kb=$(awk '{print $2}' <<<"$df_line")
used_kb=$(awk '{print $3}' <<<"$df_line")
avail_kb=$(awk '{print $4}' <<<"$df_line")
used_percent=$(awk '{print $5}' <<<"$df_line" | tr -d '%')
mount_point=$(awk '{print $6}' <<<"$df_line")

status="OK"
exit_code=0
if [[ "$used_percent" =~ ^[0-9]+$ ]]; then
  if (( used_percent >= CRITICAL_THRESHOLD )); then
    status="CRITICAL"
    exit_code=2
  elif (( used_percent >= WARN_THRESHOLD )); then
    status="WARNING"
    exit_code=1
  fi
else
  status="UNKNOWN"
  exit_code=1
fi

log "Disk usage for $TARGET_PATH (filesystem $filesystem mounted on $mount_point)"
log "  Total: ${size_kb}K, Used: ${used_kb}K, Available: ${avail_kb}K"
log "  Utilisation: ${used_percent}% (status: ${status})"

if [[ -d "$MEDIA_PATH" ]]; then
  if ! media_usage=$(du -sh "$MEDIA_PATH" 2>/dev/null); then
    if media_k=$(du -sk "$MEDIA_PATH" 2>/dev/null | awk '{print $1}'); then
      media_usage="${media_k}K"
    else
      media_usage="unknown"
    fi
  fi
  log "Media directory size ($MEDIA_PATH): ${media_usage}"
else
  log "Media directory not found: $MEDIA_PATH"
fi

exit "$exit_code"
