#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Set up the Python 3.12 environment using README.md first."
  exit 1
fi
exec .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 "$@"
