#!/usr/bin/env bash
# Jednoduchá instalace: sestaví appku a dá ji do ~/Applications.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/build-app.sh"

DEST_DIR="$HOME/Applications"
mkdir -p "$DEST_DIR"
rm -rf "$DEST_DIR/JARVIS.app"
cp -R "$ROOT/dist/JARVIS.app" "$DEST_DIR/JARVIS.app"

# Odstraň quarantine, ať Gatekeeper méně nadává při lokálním buildu
xattr -dr com.apple.quarantine "$DEST_DIR/JARVIS.app" 2>/dev/null || true

echo ""
echo "✅ Nainstalováno: $DEST_DIR/JARVIS.app"
echo "Spouštím…"
open "$DEST_DIR/JARVIS.app"
echo ""
echo "Ikona JARVIS je v menu baru (nahoře vpravo)."
echo "LM Studio musí běžet na adrese z configu."
echo "Projekty: ./scripts/register-project.sh ALIAS /cesta"
