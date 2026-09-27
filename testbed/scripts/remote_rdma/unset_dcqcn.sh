#!/usr/bin/env bash
set -euo pipefail
# Pass --hosts, --deployment, and optionally --lossless / --check.
exec python3 "$(dirname "$0")/config_nic.py" --dcqcn 0 "$@"
