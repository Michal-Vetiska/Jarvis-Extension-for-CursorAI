#!/usr/bin/env bash
# Sestaví dist/JARVIS.app — jeden dvojklik, backend startuje sám.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="JARVIS"
DIST="$ROOT/dist"
APP="$DIST/$APP_NAME.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RES="$CONTENTS/Resources"
SWIFT_DIR="$ROOT/apps/JarvisMenuBar"

echo "==> Kontrola Python venv"
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Spouštím setup.sh..."
  "$ROOT/scripts/setup.sh"
fi

# Uživatelský config, pokud chybí
mkdir -p "$HOME/Library/Application Support/JARVIS"
if [[ ! -f "$HOME/Library/Application Support/JARVIS/config.toml" ]]; then
  cp "$ROOT/config/default.toml" "$HOME/Library/Application Support/JARVIS/config.toml"
fi

echo "==> Swift release build"
cd "$SWIFT_DIR"
swift build -c release
BIN="$(swift build -c release --show-bin-path)/JarvisMenuBar"
cd "$ROOT"

echo "==> Skládám $APP"
rm -rf "$APP"
mkdir -p "$MACOS" "$RES"

cp "$BIN" "$MACOS/$APP_NAME"
chmod +x "$MACOS/$APP_NAME"

# Kam má backend hledat projekt (venv + python package)
printf '%s\n' "$ROOT" > "$RES/jarvis-home"

cat > "$RES/launch-backend.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
RES_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(tr -d '\n' < "$RES_DIR/jarvis-home")"
export PATH="$HOME/.local/bin:$PATH"
export PYTHONUNBUFFERED=1
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "JARVIS: chybí $ROOT/.venv — spusť ./scripts/setup.sh" >&2
  exit 1
fi
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m jarvis.main
EOF
chmod +x "$RES/launch-backend.sh"

# Dev helper také do Resources (volitelný)
cp "$ROOT/scripts/launch-backend-dev.sh" "$RES/launch-backend-dev.sh"
chmod +x "$RES/launch-backend-dev.sh"

cat > "$CONTENTS/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>cs</string>
	<key>CFBundleExecutable</key>
	<string>${APP_NAME}</string>
	<key>CFBundleIdentifier</key>
	<string>com.jarvis.macos</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>${APP_NAME}</string>
	<key>CFBundleDisplayName</key>
	<string>ADAM</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>0.1.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>LSMinimumSystemVersion</key>
	<string>14.0</string>
	<key>LSUIElement</key>
	<true/>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>NSMicrophoneUsageDescription</key>
	<string>ADAM potřebuje mikrofon pro hands-free („Hej Adame“) a hlasový vstup.</string>
	<key>NSSpeechRecognitionUsageDescription</key>
	<string>ADAM používá rozpoznávání řeči pro české příkazy („Hej Adame…“).</string>
	<key>NSAppleEventsUsageDescription</key>
	<string>JARVIS ovládá aplikace přes Automation / AppleScript.</string>
</dict>
</plist>
EOF

# Ad-hoc podpis — stačí pro lokální použití
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep -s - "$APP" 2>/dev/null || true
fi

echo ""
echo "Hotovo: $APP"
echo "Spusť:  open \"$APP\""
echo "Nebo:   ./scripts/install-app.sh   (zkopíruje do ~/Applications)"
