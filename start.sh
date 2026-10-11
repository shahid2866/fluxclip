#!/usr/bin/env bash
# FluxClip Studio - one-click start for macOS / Linux
# Needs: Python 3.10+, Node.js 20+, FFmpeg
set -e
cd "$(dirname "$0")"
for b in python3 node ffmpeg; do command -v $b >/dev/null || { echo "Please install $b first"; exit 1; }; done
if [ ! -d .venv ]; then
  echo "Setting up Python environment (first run takes a few minutes)…"
  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -e ".[all]"
fi
[ -d web/node_modules ] || (cd web && npm install --no-audit --no-fund)
[ -f web/.next/BUILD_ID ] || (cd web && npm run build)
.venv/bin/fluxclip studio --port 8000 & API=$!
(cd web && npm start) & WEB=$!
trap 'kill $API $WEB 2>/dev/null' EXIT
sleep 6
echo "FluxClip Studio is running at http://localhost:3000  (Ctrl+C to stop)"
(command -v open >/dev/null && open http://localhost:3000) || (command -v xdg-open >/dev/null && xdg-open http://localhost:3000) || true
wait
