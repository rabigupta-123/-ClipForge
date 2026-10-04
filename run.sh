#!/bin/bash
# Supervisor: keep the ClipForge server alive (auto-restart on crash).
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
while true; do
  echo "[run.sh] starting server on port $PORT"
  python3 server.py
  echo "[run.sh] server exited (rc=$?) — restarting in 2s"
  sleep 2
done
