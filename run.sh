#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python -r requirements.txt
  else
    python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required; install uv or upgrade Python."'
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
  fi
fi
exec .venv/bin/python -m streamlit run app.py "$@"
