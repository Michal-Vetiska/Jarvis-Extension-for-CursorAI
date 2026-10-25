#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ALIAS="${1:-}"
PATH_ARG="${2:-}"
if [[ -z "$ALIAS" || -z "$PATH_ARG" ]]; then
  echo "Použití: $0 <ALIAS> <ABSOLUTNÍ_CESTA>"
  exit 1
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m jarvis.main --register-project "$ALIAS" "$PATH_ARG"
