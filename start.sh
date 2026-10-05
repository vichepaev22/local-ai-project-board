#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$ROOT/run.py" "$@"
fi
exec python "$ROOT/run.py" "$@"
