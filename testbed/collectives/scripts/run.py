#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENGINES = {
    "ring-allreduce": "run_p2p_ring8_dual.sh",
    "alltoall": "run_alltoall_3mb.sh",
    "alltoallv": "run_alltoallv_zipfian_incast_150mb.sh",
}


def main():
    parser = argparse.ArgumentParser(description="Two concurrent groups; no network access in dry-run.")
    parser.add_argument("workload", choices=ENGINES)
    parser.add_argument("--site", type=Path, default=ROOT / "configs/sites/dc20-dc23.json")
    parser.add_argument("--experiment", type=Path, default=ROOT / "configs/experiments/150mib.json")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.run_id):
        parser.error("run-id must contain only letters, numbers, dot, underscore or hyphen")
    site = json.loads(args.site.read_text())
    experiment = json.loads(args.experiment.read_text())
    groups = site["groups"]
    if not groups or len({group["name"] for group in groups}) != len(groups):
        parser.error("groups must have unique names")
    target = experiment["target_recv_bytes"]
    if not isinstance(target, int) or target <= 0:
        parser.error("target_recv_bytes must be a positive integer")
    group_sizes = {group["np"] for group in groups}
    if len(group_sizes) != 1 or min(group_sizes) < 2:
        parser.error("this preset requires equal group sizes, each at least 2")
    for group in groups:
        if len(group["devices"]) != group["np"]:
            parser.error("device count must match group np")
        if sorted(group["ring_order"]) != list(range(group["np"])):
            parser.error("ring_order must be a permutation of group ranks")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", group["name"]):
            parser.error("invalid group name")
        rankfile = ROOT / group["rankfile"]
        ranks = re.findall(r"^rank\s+(\d+)=(\S+)\s+slot=.+$", rankfile.read_text(), re.MULTILINE)
        if sorted(int(rank) for rank, host in ranks) != list(range(group["np"])):
            parser.error(f"rankfile must contain each group rank exactly once: {rankfile}")
        if any(host not in site["hosts"] for rank, host in ranks):
            parser.error("rankfile host is absent from site hosts")
        leader = next(host for rank, host in ranks if int(rank) == 0)
        if not args.dry_run and leader != socket.gethostname().split(".")[0]:
            parser.error("launch on each group's rank-0 host (dc20 in this preset) so CSVs are local")
    out = ROOT / "results" / args.workload / args.run_id
    out.mkdir(parents=True, exist_ok=False)
    snapshots = out / "configs"
    snapshots.mkdir()
    (snapshots / "site.json").write_text(json.dumps(site, indent=2) + "\n")
    (snapshots / "experiment.json").write_text(json.dumps(experiment, indent=2) + "\n")
    size = target // (groups[0]["np"] - 1) if args.workload == "alltoall" else target
    command = ["bash", str(ROOT / "scripts/engines" / ENGINES[args.workload]),
               "--hosts", ",".join(site["hosts"]), "--outdir", str(out),
               "--total-np", str(sum(group["np"] for group in groups)),
               "--warmup", str(experiment["warmup"]), "--iters", str(experiment["iters"]),
               "--bind-to", site["bind_to"], "--gid-index", str(site["gid_index"])]
    if args.workload == "ring-allreduce":
        command += ["--bench", "latency", "--size", str(size),
                    "--write-chunk", experiment["ring_write_chunk"],
                    "--sig-interval", str(experiment["ring_signal_interval"]),
                    "--write-notify", experiment["ring_write_notify"]]
    else:
        command += ["--size-bytes", str(size), "--use-rdma-cm", "0", "--no-auto-gid-detect"]
        if args.workload == "alltoallv":
            command += ["--zipf-alpha", str(experiment["zipf_alpha"])]
    for group in groups:
        rankfile = ROOT / group["rankfile"]
        snapshot = snapshots / (group["name"] + ".rankfile")
        snapshot.write_text(rankfile.read_text().rstrip() + "\n")
        spec = (f"name={group['name']};np={group['np']};map-by=rankfile:file={snapshot};"
                f"dev-map={','.join(group['devices'])};rankfile={snapshot}")
        if args.workload == "ring-allreduce":
            spec += (f";ring-order={','.join(map(str, group['ring_order']))}"
                     f";dump-iter-fct={out / ('ring_' + group['name'] + '.csv')}")
        command += ["--group", spec]
    if args.dry_run:
        command.append("--dry-run")
    (out / "command.txt").write_text(shlex.join(command) + "\n")
    print(shlex.join(command), flush=True)
    try:
        if not args.dry_run:
            with (out / "build.log").open("w") as log:
                subprocess.run(["bash", str(ROOT / "scripts/build.sh")], stdout=log, stderr=subprocess.STDOUT, check=True)
        with (out / "launcher.log").open("w") as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        return result.returncode
    except (OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        print(f"Results: {out}")


if __name__ == "__main__":
    sys.exit(main())
