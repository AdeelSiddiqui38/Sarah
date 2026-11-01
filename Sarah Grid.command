#!/bin/bash
# Starts Sarah Core on this Mac (only reachable from this computer) and opens the control room.
cd "$(dirname "$0")"
PORT=8770
if ! python3 -c "import keyring" 2>/dev/null; then
  echo "Installing keyring once so secrets go into the macOS Keychain..."
  python3 -m pip install --user --quiet keyring || echo "keyring not installed; Sarah will use a local vault file instead."
fi
if ! nc -z 127.0.0.1 $PORT 2>/dev/null; then
  nohup python3 sarah_core.py > data_core.log 2>&1 &
  for i in 1 2 3 4 5 6 7 8 9 10; do nc -z 127.0.0.1 $PORT 2>/dev/null && break; sleep 0.5; done
fi
open "http://127.0.0.1:$PORT/"
