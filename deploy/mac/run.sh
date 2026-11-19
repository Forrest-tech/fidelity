#!/bin/bash
# Started by launchd (com.fidelity.app). Loads deploy/mac/mac.env, then runs the app in the foreground.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -f "$ROOT/deploy/mac/mac.env" ]; then
  set -a; . "$ROOT/deploy/mac/mac.env"; set +a
fi
export PYTHONUTF8=1
cd "$ROOT/backend"
exec "$ROOT/.venv/bin/python" -m scripts.serve
