# Plot Workspace

This Bazel workspace contains the plotting code used by the paper artifact.
Artifact wrappers under `main/plot_artifact/` consume parsed simulation data
and call the lower-level plotting code under `main/plot_sample/`.

## Bazel Setup

The workspace pins Bazel 6.5.0 in `.bazelversion`. Bazelisk automatically uses
that version. See the
[Bazel installation guide](https://bazel.build/install) and
[Bazelisk documentation](https://github.com/bazelbuild/bazelisk) for other
platforms.

For x86_64 Linux, run the following commands from the repository root:

```bash
mkdir -p "$HOME/.local/bin"
curl -L \
  https://github.com/bazelbuild/bazelisk/releases/latest/download/bazelisk-linux-amd64 \
  -o "$HOME/.local/bin/bazel"
chmod +x "$HOME/.local/bin/bazel"
export PATH="$HOME/.local/bin:$PATH"

cd plot
bazel version
```

The workspace uses Bzlmod and Python requirements locked in
`third_party/py/requirements_lock.txt`. The first build may download Bazel
modules and Python wheels.

## Build Check

From `plot/`:

```bash
bazel build //main/plot_artifact/... //main/plot_sample:all
```

## Plot Parsed Results

Use the simulation artifact runner so that each wrapper receives the correct
input and output directories. From `simulation/` on the host:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --stage plot \
  --run-id trial1
```

Use `--section lossy`, `--section asymmetric`, or `--section all` to select
other sections. Add `--workload datacenter-workloads` or
`--workload collective-communication-workloads` to render one workload family.
The requested run must already contain parsed data under its `json/` directory.

To inspect the Bazel commands without rendering figures:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --stage plot \
  --run-id trial1 \
  --dry-run
```

Artifact wrappers for Figures 4 through 17 are grouped under:

```text
main/plot_artifact/lossless/
main/plot_artifact/lossy/
main/plot_artifact/asymmetric/
```

Generated CSV, JSON, PDF, PNG, `__pycache__`, and `bazel-*` paths are ignored by
Git. Use `bazel clean` only when intentionally discarding local Bazel outputs.
