#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -r requirements.txt
exec .venv/bin/python app.py "$@"
