#!/bin/bash
# Fidelity — native install on the Mac mini (spec §10, Phase 6). Idempotent: safe to run again.
#   ./deploy/mac/install.sh            install / update and start the service
#   ./deploy/mac/install.sh --check    only check prerequisites
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
say() { printf '\n== %s\n' "$*"; }
[ "$(uname -s)" = "Darwin" ] || { echo "macOS only"; exit 1; }
command -v brew >/dev/null || { echo "Homebrew is required: https://brew.sh"; exit 1; }
if [ "${1:-}" = "--check" ]; then
  for c in python3.11 tesseract node ollama; do printf '%-10s %s\n' "$c" "$(command -v $c || echo MISSING)"; done
  exit 0
fi

say "System packages (Homebrew)"
brew install python@3.11 tesseract node@20 ollama

say "Python environment"
[ -d "$ROOT/.venv" ] || "$(brew --prefix python@3.11)/bin/python3.11" -m venv "$ROOT/.venv"
PIP="$ROOT/.venv/bin/pip"
"$PIP" install --upgrade pip
if [ -f "$ROOT/deploy/mac/requirements-macos.lock" ]; then          # locked versions (from CI on macOS)
  "$PIP" install -r "$ROOT/deploy/mac/requirements-macos.lock"
else
  "$PIP" install -r "$ROOT/backend/requirements.txt"
fi
"$PIP" install -r "$ROOT/deploy/mac/requirements-mac.txt"

say "Models"
( cd "$ROOT/backend" && "$ROOT/.venv/bin/python" scripts/fetch_ocr_models.py )
brew services start ollama
ollama pull "$(grep -E '^FIDELITY_LLM_MODEL=' "$ROOT/deploy/mac/mac.env" 2>/dev/null | cut -d= -f2 || echo qwen2.5:7b-instruct)"

say "Web interface"
( cd "$ROOT/web" && npm ci && npm run build )

say "Configuration"
[ -f "$ROOT/deploy/mac/mac.env" ] || cp "$ROOT/deploy/mac/mac.env.example" "$ROOT/deploy/mac/mac.env"
mkdir -p "$ROOT/data/logs"
chmod +x "$ROOT/deploy/mac/run.sh"

say "Service (starts at login, restarts if it stops)"
PL="$HOME/Library/LaunchAgents/com.fidelity.app.plist"
sed "s#__ROOT__#$ROOT#g" "$ROOT/deploy/mac/com.fidelity.app.plist" > "$PL"
launchctl unload "$PL" 2>/dev/null || true
launchctl load "$PL"

say "Benchmark the engines on this machine and choose the best two"
( cd "$ROOT/backend" && "$ROOT/.venv/bin/python" scripts/ocr_benchmark.py --synthetic --out ../docs/benchmarks/ocr-mac --select )
( cd "$ROOT/backend" && "$ROOT/.venv/bin/python" scripts/perf_benchmark.py --pdf "${PERF_PDF:-}" --label "Mac mini" --out ../docs/benchmarks/perf-mac ) || \
  echo "Set PERF_PDF=<a text PDF> to record throughput (docs/benchmarks/perf-mac.md)."

say "Done — open http://127.0.0.1:${QA_SERVER_PORT:-8000} in a browser: create the first administrator on the sign-in page, then connect Dropbox under Settings → Cloud storage."
