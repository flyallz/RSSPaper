#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/src/universal/macos-v1.1"
PYTHON="${PYTHON:-python3}"
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$ROOT/dist/.pyinstaller-config}"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

cd "$SOURCE"
"$PYTHON" -m unittest discover -s tests -v
if [ ! -f assets/icon.icns ]; then
  "$PYTHON" make_icon.py
fi
"$PYTHON" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist/universal-macos" \
  --workpath "$ROOT/dist/universal-macos-build" \
  JournalRadar-mac.spec

APP="$ROOT/dist/universal-macos/JournalRadar.app"
"$APP/Contents/MacOS/JournalRadar" --self-test
codesign --verify --deep --strict "$APP"
mkdir -p "$ROOT/releases/macos"
ditto -c -k --sequesterRsrc --keepParent "$APP" \
  "$ROOT/releases/macos/JournalRadar-Universal-v1.3.2-Mac-arm64.zip"
