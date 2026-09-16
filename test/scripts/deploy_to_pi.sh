#!/usr/bin/env bash
# Placeholder deploy script. Offline-safe: only prepares package layout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:-raspberrypi}"
DEST="${2:-~/ptz-offline-test}"

echo "[deploy] local package: $ROOT"
echo "[deploy] target host  : $HOST"
echo "[deploy] remote path  : $DEST"
echo
echo "This script is intentionally conservative."
echo "It will ask for your normal SSH password when connecting."
echo
read -r -p "Continue deploy to $HOST:$DEST ? [y/N] " ans
if [[ "${ans:-}" != "y" && "${ans:-}" != "Y" ]]; then
  echo "Cancelled."
  exit 0
fi

ssh "$HOST" "mkdir -p $DEST"
rsync -av --exclude 'data/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
  "$ROOT/" "$HOST:$DEST/"
echo "Deploy finished. On Pi: cd $DEST && python3 scripts/run_mock_demo.py"
