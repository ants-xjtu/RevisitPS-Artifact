#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
main_cc="$repo_root/scratch/network-load-balance/main.cc"

python3 - "$main_cc" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text()
pattern = re.compile(r'if\s*\(\s*lb_mode\s*==\s*5\s*\|\|\s*lb_mode\s*==\s*7\s*\)')

if not pattern.search(text):
    print("missing lb_mode == 7 hostIp2SwitchId initialization branch", file=sys.stderr)
    sys.exit(1)
PY
