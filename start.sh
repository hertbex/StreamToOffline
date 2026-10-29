#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "[StreamToOffline] Python environment is missing."
    echo "Expected: $(pwd)/.venv/bin/python"
    echo
    read -r -p "Press Enter to exit..."
    exit 1
fi

export PYTHONUNBUFFERED=1
".venv/bin/python" -m streamtooffline wizard || {
    echo
    echo "[StreamToOffline] Unexpected error. See messages above."
    read -r -p "Press Enter to exit..."
    exit 1
}
