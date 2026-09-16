# Plot Workspace

This focused Bazel workspace contains only the plotting code used by the paper
artifact. Artifact-specific wrappers live in `main/plot_artifact/` and call the
lower-level targets in `main/plot_sample/`.

The packaged artifact layout is:

```text
RevisitPS-Artifact/
|-- simulation/
`-- plot/
```

## Bazel Setup

Install Bazel through Bazelisk, which selects an appropriate Bazel release for
the workspace. The official Bazel installation page is
https://bazel.build/install, and Bazelisk is documented at
https://github.com/bazelbuild/bazelisk.

For x86_64 Linux, one common setup is:

```bash
mkdir -p "$HOME/.local/bin"
curl -L https://github.com/bazelbuild/bazelisk/releases/latest/download/bazelisk-linux-amd64 \
  -o "$HOME/.local/bin/bazel"
chmod +x "$HOME/.local/bin/bazel"
export PATH="$HOME/.local/bin:$PATH"
bazel version
```

If `bazel` is already available on the machine, just verify it:

```bash
cd plot
bazel version
```

This workspace uses Bzlmod (`.bazelrc` enables `--enable_bzlmod`) and Python
requirements locked in `third_party/py/requirements_lock.txt`. The first build
may download Bazel modules and Python wheels.

## Build Checks

From `plot/`:

```bash
bazel build //main/plot_artifact/...
bazel build //main/plot_sample:all
```

Use `bazel clean` only when you intentionally want to discard Bazel build
outputs. Local Bazel symlinks (`bazel-*`) and plot outputs are ignored by Git.

## Plot Through the Artifact Runner

The normal path is to let `simulation/artifact/run_artifact.sh` call the correct
plot wrappers:

```bash
cd ../simulation
./artifact/run_artifact.sh --section all --stage plot --run-id latest
./artifact/run_artifact.sh --section asymmetric --stage plot --run-id trial1
```

Use `--dry-run` to inspect the Bazel commands without rendering figures:

```bash
./artifact/run_artifact.sh --section lossless --stage plot --dry-run
```

## Manual Plot Commands

You can also run one artifact plot wrapper directly from `plot/`:

```bash
bazel run //main/plot_artifact/asymmetric:plot_fig14_asym_dcn_fct -- \
  --input-dir ../simulation/artifact/results/asymmetric/datacenter-workloads/runs/latest/json/fig14_asym_dcn_fct \
  --output-dir ../simulation/artifact/results/asymmetric/datacenter-workloads/runs/latest/figures
```

Or run a lower-level plotting target directly:

```bash
bazel run //main/plot_sample:plot_dcn_rto_fct -- \
  ../simulation/artifact/results/lossy/datacenter-workloads/runs/latest/json/fig11_lossy_dcn_p99_fct_leafspine
```

## Plot Targets

- `//main/plot_sample:plot_dcn_fct`
- `//main/plot_sample:plot_dcn_ooo`
- `//main/plot_sample:plot_dcn_pfc_incast`
- `//main/plot_sample:plot_dcn_pfc_trigger`
- `//main/plot_sample:plot_dcn_rto_fct`
- `//main/plot_sample:plot_dcn_rto_fct_trim_vs_rto`
- `//main/plot_sample:plot_dcn_unnecessary_retrans`
- `//main/plot_sample:plot_sim_ai_jct_avg`
- `//main/plot_sample:plot_sim_ai_jct_avg_asy`
- `//main/plot_sample:plot_single_spine_qlen`

Artifact wrappers include:

- `//main/plot_artifact/lossless:plot_fig04_lossless_dcn_p99_fct`
- `//main/plot_artifact/lossless:plot_fig07_lossless_ai_collective_cct`
- `//main/plot_artifact/lossy:plot_fig13_lossy_ai_collective_cct`
- `//main/plot_artifact/asymmetric:plot_fig14_asym_dcn_fct`
- `//main/plot_artifact/asymmetric:plot_fig17_asym_ai_collective_cct`

The wrappers copy or route generated PDFs into the artifact result directory.
Do not commit generated CSV, JSON, PDF, PNG, or `__pycache__` files.
