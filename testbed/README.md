# Testbed experiments

This directory runs two experiments through one Docker entry point:

- **DCN workload** (`dcn_workload`): the paper's Figure 2 trace/FCT experiment.
- **AI workload** (`ai_workload`): `ring_allreduce`, `alltoall`, and `alltoallv`.

Both use the explicitly registered BigSwitch, ECMP, and RPS configurations in
lossless and lossy modes. AI enables DCQCN in all six network profiles. Workloads
and network profiles run sequentially; an AI launch retains two concurrent groups
of eight ranks (16 ranks in one `mpirun`).

## Layout

| Directory | Responsibility |
| --- | --- |
| `docker/` | Image, Compose configuration, locked Python dependencies |
| `deployment/` | SSH/MPI/SDE settings, shared host inventory, physical topologies |
| `switches/` | P4 dataplanes, Python controlplanes, BFRT helpers, deployment and verification |
| `experiments/dcn_workload/` | DCN matrix, traffic/configuration, pinned perftest submodule, trace/FCT/plot code |
| `experiments/ai_workload/` | AI matrix, endpoint groups/rankfiles, unchanged C++ sources, build/MPI/JCT/plot code |
| `framework/` | CLI, device lock, task/attempt state, readiness cache, SSH and RDMA operations |
| `tests/` | Framework, switches, DCN and AI regression tests |
| `build/`, `results/`, `runtime/` | Ignored, persistent build cache, results and device locks |

All project paths in configuration resolve relative to **testbed/**, independent
of the invoking working directory. MPI remote paths are explicit absolute paths.

## Configure the deployment

The control host needs Docker/Compose, Git, Python 3 and an SSH agent. RDMA nodes
need supported device tools and noninteractive sudo; switches need their matching
Tofino SDE/driver and existing Nix installation.

```bash
cd testbed
git submodule update --init -- experiments/dcn_workload/sources/perftest
test -f deployment/deployment.local.yaml || cp deployment/deployment.yaml deployment/deployment.local.yaml
```

Edit `deployment/deployment.local.yaml`, `deployment/hosts.yaml`, the topology
files and `switches/configs/` to match the actual devices. AI groups reference
endpoint IDs in the shared inventory instead of maintaining another NIC list.
The AI MPI section in the base deployment file is merged with local overrides.

```bash
eval "$(ssh-agent -s)"
ssh-add /path/to/authorized_private_key
./setup_ssh.sh
source "$HOME/.config/revisitps-artifact/env.sh"
```

The helper reads verified SSH configuration/known hosts and never copies private
keys. Record the printed public-key fingerprint in `ssh.expected_fingerprints`.
The MPI launcher (default `dc20`) also needs its **own** working SSH credentials
and verified host keys for all rank hosts; agent forwarding is disabled.

## Build and inspect the plan

```bash
./run.sh build
./run.sh --experiment dcn_workload --network-mode all --run-id trial1 --dry-run
./run.sh --experiment ai_workload --workload all --network-mode all --run-id trial1 --dry-run
```

`build` builds the controller image. AI binaries are compiled only by the AI
`prepare`, `check`, `run` or `all` stages. Offline stages require a prebuilt image
and never rebuild or replace a running console. Without Docker, the offline CLI
can be used with the locked Python dependencies:

```bash
PYTHONPATH="$PWD" python -m framework.cli --experiment ai_workload \
  --workload alltoall --network-mode lossless --run-id inspect --dry-run
```

The default image contains Debian Bookworm Open MPI and RDMA development packages.
It is **not assumed compatible with every node**. `mpi.compiler`, `mpi.prefix`
and `mpi.library_path` describe the intended toolchain/runtime. Preparation checks
CPU architecture, Open MPI version, glibc, ELF dependencies and a compiled
MPI/C++/RDMA loader probe on every node. Use a matching custom image/Dockerfile
(`ARTIFACT_IMAGE`, `ARTIFACT_DOCKERFILE`) if the supplied toolchain does not match.
A mismatch fails before measurement; it does not silently rebuild on dc20.

## Prepare, check, measure

DCN:

```bash
./run.sh --experiment dcn_workload --network-mode lossless --run-id dcn-trial1 --stage prepare
./run.sh --experiment dcn_workload --network-mode lossless --run-id dcn-trial1 --stage check
./run.sh --experiment dcn_workload --network-mode lossless --run-id dcn-trial1 --stage all
```

AI:

```bash
./run.sh --experiment ai_workload --workload alltoall --network-mode lossless --run-id ai-trial1 --stage prepare
./run.sh --experiment ai_workload --workload alltoall --network-mode lossless --run-id ai-trial1 --stage check
./run.sh --experiment ai_workload --workload alltoall --network-mode lossless --run-id ai-trial1 --stage all
```

Use `--network-mode all`, `--workload all` and `--repeat N` to expand registered
combinations. DCN has six tasks per repeat; AI has eighteen when both selectors
are `all`. `run` measures without parsing/plotting; `all` also parses and plots.

- `prepare`: check/provision common dependencies; AI probes the launcher and nodes,
  builds or verifies the content-addressed cache, distributes directly from the
  container, verifies checksums and runs the loader probe.
- `check`: apply and verify the chosen switch/NIC configuration. DCN runs its
  bidirectional throughput and trace checks. AI validates actual CPU binding and
  performs a short two-group RDMA collective.
- `run` / `all`: apply the chosen hardware settings and measure. AI always passes
  the small collective before formal measurement. The GID index is probed from
  the actual endpoint/IP mapping, not copied from the old hardcoded value.

All hardware stages share `runtime/locks/testbed.lock` across both experiments.
Do not run legacy checkouts against the same hardware concurrently. Switch
builds still run in the matching SDE environment; DCN perftest still builds on
the RDMA nodes. AI sources compile in the container, and MPI launches via SSH
on the configured launcher. CSVs return to the container automatically.

## Results, retries and offline stages

Outputs are under `results/<experiment>/<run-id>/`: `status.json`, `manifest.csv`,
`environment.json`, `tasks/<task-id>/attempt-*/{configs,raw,logs}`, `parsed/`, and
`figures/`. DCN retains its existing endpoint/check/counter log layout inside
attempts. Raw samples for each AI group and repeat remain separate. AI plots
show per-group/per-repeat mean JCT in microseconds; summaries also contain median
and nearest-rank p99. Figure 2's FCT/statistical definitions are unchanged.

```bash
./run.sh --experiment ai_workload --run-id ai-trial1 --stage status
./run.sh --experiment ai_workload --run-id ai-trial1 --stage parse
./run.sh --experiment ai_workload --run-id ai-trial1 --stage plot
./run.sh --experiment ai_workload --workload alltoall --network-mode lossless \
  --run-id ai-trial1 --stage all --resume
```

Run IDs contain only letters, digits, `_` and `-`. Existing measurement state
requires explicit `--resume`. Resume verifies configuration, implementation,
dependency identity and result checksums. Failed retries use a new attempt;
completed, verified tasks can be reused. Keep the original selectors and repeat
count for AI resume.

For DCN, `prepare`, `check`, and `run/all` share a readiness report covering the
union of selected devices: SSH access, dependencies, RDMA and perftest are checked
once per unchanged deployment profile. A local SSH-agent check still runs when
reusing a report. During `check`, bidirectional throughput and short-trace checks
run once per algorithm, in the first selected mode that passes. The other mode
reuses that evidence; every mode still deploys its switch/NIC configuration and
reads it back. Thus the six standard configurations need one common readiness
check and three sets of traffic checks, with six mode configuration/readbacks.

Traffic evidence is scoped to the same run ID and stored under `checks/traffic/`;
it records the actually tested mode, not a claim that both modes passed traffic
tests. Failed checks, changed inputs/code, or missing/modified evidence prevent
reuse. `--refresh-environment` forces shared readiness and, for DCN `check`, one
new traffic check per algorithm. `run/all` performs the measurements without
implicitly running the diagnostic throughput/short-trace checks.

AI failures/timeouts stop only journaled launcher/rank processes, using PID start
time and an ownership token. Cleanup failures are recorded and prevent success.
Exit code zero alone is insufficient: every group CSV must contain the expected
number of finite positive samples and valid iteration IDs.

`parse`, `plot`, `status` and `--dry-run` need no SSH agent or hardware. Result,
build and runtime directories are separate persistent Docker mounts. A dry run
creates no experiment output and neither compiles nor distributes AI programs.

## Diagnostics and migration

```bash
./run.sh diagnose --cmd check_one_link --config /absolute/path/to/configs/runtime.yaml \
  --src 10.150.240.201 --dst 10.150.240.205
./run.sh monitor --run-id dcn-trial1 --switch tf_sw2
```

NIC wrapper commands are now exposed through the same entry point:

```bash
./run.sh nic --hosts deployment/hosts.yaml --deployment deployment/deployment.local.yaml --lossless --check
```

Omit `--check` to apply the configured settings; `--dcqcn 0|1` provides the old
DCQCN toggle. Firmware PSN settings are validated, not silently scheduled for a
reboot. Diagnostics retain switch build/run/configuration, link checks, trace generation
and synchronization, and the existing single-step DCN functions. Use the
**container-visible** path to a generated runtime snapshot for diagnostics.

`docker_artifact.sh` remains a thin DCN compatibility wrapper: its old
`--experiment lossless|lossy|all` becomes `--experiment dcn_workload
--network-mode ...`. The old Makefile dispatcher and AI Shell engines are removed.
Do not resume pre-migration tasks by just moving their directories: absolute
paths and implementation identities have changed. Historical AI raw results
remain in `experiments/ai_workload/reference_results/` with unchanged checksums.
Unused historical FCT merge, parsing and CDF utilities have been removed;
DCN scripts retain the current Figure 2 pipeline and throughput diagnostics.

See [the migration report](docs/testbed-reorganization-report.md) for changes and
validation, and the individual [DCN](experiments/dcn_workload/README.md) and
[AI](experiments/ai_workload/README.md) experiment notes.

## Tests

```bash
python -m pip install -r docker/requirements.lock.txt
PYTHONPATH="$PWD" MPLBACKEND=Agg FIGURE2_RENDER_TEST=1 \
  python -m unittest discover -s tests -t . -v
```

Figure 2 render tests require LaTeX. Offline tests validate commands, parsers,
cleanup and recovery, but do not replace real MPI/RDMA/Tofino hardware acceptance.
