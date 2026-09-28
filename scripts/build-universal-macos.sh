#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
exec "$PYTHON" "$ROOT/scripts/build-universal.py" "$@"
