#!/usr/bin/env bash
# Generate host-local SSH configuration; never copy private keys or contact devices.
set -euo pipefail
exec python3 "$(dirname "$0")/deployment/setup_ssh.py" "$@"
