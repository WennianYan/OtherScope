#!/bin/bash
# OtherScope launcher for macOS
# Usage: double-click run_macos.command (or: chmod +x run_macos.command && ./run_macos.command)

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 not found. Install Python 3.9+ first."
    read -r -p "Press Enter to close..."
    exit 1
fi

python3 launcher.py
