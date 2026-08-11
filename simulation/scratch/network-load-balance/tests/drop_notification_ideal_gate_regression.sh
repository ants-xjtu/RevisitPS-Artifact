#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
rdma_hw="$repo_root/src/point-to-point/model/rdma-hw.cc"

python3 - "$rdma_hw" <<'PY'
import pathlib
import sys

text = pathlib.Path(sys.argv[1]).read_text()
start = text.index("void RdmaHw::NotifyPacketDrop(")
end = text.index("Ptr<Packet> RdmaHw::GetNxtPacket(", start)
body = text[start:end]

record_drop = body.index("qp->RecordArDrop(seq);")
ideal_gate = body.index("if (!qp->ideal.m_enabled)")
cnp_calls = (
    "cnp_received_mlx(qp);",
    "cnp_received_mlx_Dest(qp);",
    "cnp_received_mlx_Lane(qp);",
)

if not all(record_drop < ideal_gate < body.index(call) for call in cnp_calls):
    print(
        "NotifyPacketDrop must record AR drops before the ideal-recovery gate "
        "and invoke congestion-control callbacks only after that gate",
        file=sys.stderr,
    )
    sys.exit(1)
PY
