#!/usr/bin/env bash
# Dev launcher — používá se při `swift run` (mimo .app bundle).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Chybí .venv — spusť ./scripts/setup.sh" >&2
  exit 1
fi
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m jarvis.main
