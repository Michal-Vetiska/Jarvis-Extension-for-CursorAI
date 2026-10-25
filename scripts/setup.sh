#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> JARVIS setup"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
# STT optional (Apple Silicon)
if [[ "$(uname -m)" == "arm64" ]]; then
  pip install -e ".[stt]" || echo "Varování: mlx-whisper se nepodařilo nainstalovat (STT bude omezené)"
fi

mkdir -p "$HOME/Library/Application Support/JARVIS"
if [[ ! -f "$HOME/Library/Application Support/JARVIS/config.toml" ]]; then
  cp config/default.toml "$HOME/Library/Application Support/JARVIS/config.toml"
  echo "Vytvořen uživatelský config.toml"
fi

# Ensure agent on PATH hint
if [[ -x "$HOME/.local/bin/agent" ]]; then
  echo "Cursor Agent CLI: OK ($HOME/.local/bin/agent)"
else
  echo "Cursor Agent CLI chybí. Nainstaluj: curl https://cursor.com/install -fsS | bash"
  echo "Pak: agent login"
fi

echo "Setup hotov. Spusť: ./scripts/start.sh"
