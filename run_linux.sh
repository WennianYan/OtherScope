#!/bin/bash
# OtherScope launcher for Linux
# Usage: chmod +x run_linux.sh && ./run_linux.sh

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 not found. Install Python 3.9+ first."
    exit 1
fi

python3 launcher.py
