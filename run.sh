#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
pip install -q -r requirements.txt
# Only watch app + web — avoids reload loops when pip touches .venv (e.g. numpy)
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --reload-dir app --reload-dir web
