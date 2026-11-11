#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "Starting EarArray FastAPI Telemetry Backend on http://127.0.0.1:8765 ..."
python3 backend/server.py &
BACKEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting Vite Dev UI on http://127.0.0.1:5173 ..."
cd "$DIR/ui"
npm run dev
