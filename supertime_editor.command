#!/bin/bash
# Supertime sequence editor launcher for the Mac (double-click in Finder).
cd "$(dirname "$0")"
python3 -m supertime_editor.app "$@"
