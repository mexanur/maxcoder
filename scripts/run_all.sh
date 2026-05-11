#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
uvicorn server.app:app --host 127.0.0.1 --port 8000 &
SERVER_PID=$!
echo "Backend PID: $SERVER_PID"
sleep 3
python ui/gradio_app.py
kill $SERVER_PID
