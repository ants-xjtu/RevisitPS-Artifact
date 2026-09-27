# Testbed Artifact

Run the Figure 2 hardware experiments with BigSwitch, ECMP, and RPS in lossless
and lossy modes. The Docker container handles orchestration, parsing, and plotting.

## Requirements

- Docker with the Compose plugin, Git, Python 3, and an SSH agent on the control host.
- SSH access to the RDMA hosts and Tofino switches, with verified host keys and
  non-interactive sudo permissions for deployment.
- Working RDMA hardware/tools and a compatible Tofino SDE, driver, and Nix setup
  on the target devices.
- Enough free space on the control host and RDMA hosts for traces and raw logs.

## Configure

From the repository root:

```bash
git submodule update --init -- testbed/third_party/perftest
cd testbed
test -f conf/deployment.local.yaml || cp conf/deployment.yaml conf/deployment.local.yaml
```

Edit `conf/deployment.local.yaml` for your SSH users, RDMA stack, remote paths,
and Tofino SDE command. Check the host, switch, and topology files under `conf/`
against your physical testbed. The experiment matrix is in `artifact/experiments.yaml`.

Load a key already authorized on the devices and generate the container SSH settings:

```bash
eval "$(ssh-agent -s)"
ssh-add /path/to/authorized_private_key
./setup_ssh.sh
source "$HOME/.config/revisitps-artifact/env.sh"
```

The setup script reads `~/.ssh/config` and `~/.ssh/known_hosts`. Use `--ssh-config`
and `--known-hosts` to select other files. Copy the printed `SHA256:...` identity
fingerprint into `ssh.expected_fingerprints` in `conf/deployment.local.yaml`.
Run all remaining commands from `testbed/`.

## Build and Validate

```bash
./docker_artifact.sh build
./docker_artifact.sh --run-id trial1 --experiment all --dry-run
./docker_artifact.sh --run-id trial1 --experiment all --stage prepare
./docker_artifact.sh --run-id trial1 --experiment all --stage check
```

`prepare` installs missing supported dependencies and loads required modules.
`check` deploys the switches, configures NICs, and runs bidirectional throughput
and short-trace checks. Both stages access the hardware; run them when the
selected testbed is available. Resolve reported failures before starting a run.

## Run

Run all six experiment/algorithm combinations, then parse and plot:

```bash
./docker_artifact.sh --run-id trial1 --experiment all --repeat 1 --stage all
```

Use `--experiment lossless` or `--experiment lossy` for one mode, and `--repeat N`
for repeated measurements. Use a new run ID for each independent run. Only one
process should control the testbed at a time.

To run the stages separately:

```bash
./docker_artifact.sh --run-id trial1 --experiment all --stage run
./docker_artifact.sh --run-id trial1 --stage parse
./docker_artifact.sh --run-id trial1 --stage plot
```

## Monitor and Resume

From another terminal with the same SSH settings loaded:

```bash
./docker_artifact.sh --run-id trial1 --stage status
./docker_artifact.sh monitor --run-id trial1 --switch tf_sw2
```

Detach from the switch console with `Ctrl-b d`.

Resume an interrupted run with the original experiment selection and repeat count:

```bash
./docker_artifact.sh --run-id trial1 --experiment all --repeat 1 --stage all --resume
```

Resume requires unchanged input configuration and implementation. Completed
measurements are verified before reuse. Add `--refresh-environment` when remote
dependencies or device state have changed and cached readiness checks must be rerun.

## Results

Outputs are stored in `artifact/results/<run-id>/`:

- `status.json` and `manifest.csv`: task completion and failure details.
- `environment.json` and `checks/`: environment reports and check logs.
- `tasks/*/attempt-*/`: per-attempt configuration, commands, and raw measurements.
- `parsed/`: parsed FCT and Figure 2 bucket data.
- `figures/`: Figure 2a, Figure 2b, and the combined Figure 2 in PDF, SVG, and PNG.

Each plotted mode requires complete BigSwitch, ECMP, and RPS measurements.
The combined figure requires both modes.

## Refresh the Container

The launcher reuses the running container. After changing code, the image, or SSH
mounts, recreate it between experiments, after its experiment and switchd sessions
have ended. For the default container name:

```bash
docker stop testbed-artifact-1
docker rm testbed-artifact-1
./docker_artifact.sh build
```

The next artifact command creates the container. Results remain in the host
`artifact/results/` directory. After replacing the SSH agent, rerun `./setup_ssh.sh`
and source its `env.sh` before creating the container.
