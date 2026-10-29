#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "[StreamToOffline] Creating Python environment..."
    python3 -m venv .venv
fi

export PYTHONUNBUFFERED=1
if ! ".venv/bin/python" -c "import streamtooffline, textual, yt_dlp, pydantic, yaml, mutagen" >/dev/null 2>&1; then
    echo "[StreamToOffline] Installing dependencies..."
    ".venv/bin/python" -m pip install -e ".[dev]" --disable-pip-version-check
fi
".venv/bin/python" -m streamtooffline wizard || {
    echo
    echo "[StreamToOffline] Unexpected error. See messages above."
    read -r -p "Press Enter to exit..."
    exit 1
}
