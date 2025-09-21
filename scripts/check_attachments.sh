#!/bin/bash
set -euo pipefail

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
MEDIA_PATH="${MEDIA_PATH:-$PROJECT_ROOT/backend/media}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Project root not found at $PROJECT_ROOT" >&2
  exit 2
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python interpreter not found: $PYTHON_BIN" >&2
  exit 2
fi

attachments_path=""
if [[ -n "${ATTACHMENTS_PATH:-}" ]]; then
  attachments_path="$ATTACHMENTS_PATH"
else
  attachments_subdir="${ATTACHMENTS_SUBDIR:-audits/attachments}"
  attachments_subdir="${attachments_subdir#/}"
  attachments_path="$MEDIA_PATH/$attachments_subdir"
fi

log "Scanning attachments in $attachments_path"

if [[ ! -d "$attachments_path" ]]; then
  log "Attachments directory not found; nothing to report"
  exit 0
fi

summary="$("$PYTHON_BIN" <<'PY'
import datetime
import os
import sys


def human_size(value: int) -> str:
    if value <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_mtime(timestamp: float | None) -> str:
    if timestamp is None:
        return "n/a"
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

root = sys.argv[1]
if root.startswith("./"):
    root = os.path.abspath(root)

total_size = 0
file_count = 0
latest_mtime = None
latest_path = None
largest_size = 0
largest_path = None

for current_root, _dirs, files in os.walk(root):
    for name in files:
        file_path = os.path.join(current_root, name)
        try:
            stat = os.stat(file_path)
        except OSError:
            continue
        file_count += 1
        total_size += stat.st_size
        if stat.st_size > largest_size:
            largest_size = stat.st_size
            largest_path = file_path
        if latest_mtime is None or stat.st_mtime > latest_mtime:
            latest_mtime = stat.st_mtime
            latest_path = file_path

lines = [
    f"Total files: {file_count}",
    f"Total size: {human_size(total_size)} ({total_size} bytes)",
]

if largest_path:
    lines.append(
        f"Largest file: {largest_path} ({human_size(largest_size)})"
    )
else:
    lines.append("Largest file: n/a")

if latest_path:
    lines.append(
        f"Latest upload: {latest_path} at {format_mtime(latest_mtime)}"
    )
else:
    lines.append("Latest upload: n/a")

print("\n".join(lines))
PY
"$attachments_path")"
while IFS= read -r line; do
  log "$line"
done <<<"$summary"

exit 0

