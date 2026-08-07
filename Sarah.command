#!/bin/bash
# Sarah launcher (macOS).
# Starts the local server if it isn't already running, then opens the avatar.
# Double-click this file, or put an alias to it on your Desktop.

cd "$(dirname "$0")" || exit 1

URL="http://127.0.0.1:8765/"

# Is anything already listening on 8765?
if ! nc -z 127.0.0.1 8765 >/dev/null 2>&1; then
  echo "Starting Sarah server..."
  nohup python3 sarah_server.py >/dev/null 2>&1 &
  # wait up to 10s for it to come up
  for i in $(seq 1 20); do
    nc -z 127.0.0.1 8765 >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

if nc -z 127.0.0.1 8765 >/dev/null 2>&1; then
  echo "Sarah is running. Opening..."
  open "$URL"
  sleep 1
else
  echo "Server failed to start. Try running: python3 sarah_server.py"
  read -r -p "Press Enter to close..."
fi
