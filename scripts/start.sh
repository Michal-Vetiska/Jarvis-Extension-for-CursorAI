#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="$HOME/.local/bin:$PATH"

if [[ ! -d .venv ]]; then
  echo "Nejdřív spusť ./scripts/setup.sh"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# Start Python backend
python -m jarvis.main "$@" &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Try to build/run Swift menu bar if possible
SWIFT_DIR="$ROOT/apps/JarvisMenuBar"
if command -v swift >/dev/null 2>&1; then
  echo "Spouštím menu-bar UI..."
  (cd "$SWIFT_DIR" && swift run JarvisMenuBar) || {
    echo "Swift UI se nespustilo — backend běží dál (IPC + wake word)."
    wait "$BACKEND_PID"
  }
else
  echo "Swift není k dispozici — běží jen backend."
  wait "$BACKEND_PID"
fi
