import csv
import json
import os
import shlex
import sys
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from experiments.ai_workload.scripts import connectivity_support as support
from framework.config import load_deployment


class ConnectivityTests(unittest.TestCase):
    def test_dry_run_pairs_from_another_working_directory(self):
        script = support.ROOT / 'experiments/ai_workload/scripts/check_pair_connectivity.sh'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'endpoints.txt').write_text('dc20:mlx5_0\ndc20:mlx5_1\ndc21:mlx5_0\n')
            for extra, count in (([], 3), (['--same-host-only'], 1)):
                subprocess.run([str(script), '--selected-endpoints', 'endpoints.txt',
                                '--outdir', 'output', '--dry-run', '--jobs', '2', *extra],
                               cwd=root, check=True, capture_output=True, text=True)
                with (root / 'output/pair_connectivity.csv').open() as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), count)
                self.assertTrue(all(row['status'] == 'DRY_RUN' for row in rows))
                self.assertTrue(all((root / row['log_path']).is_file() for row in rows))

    def test_gid_matches_inventory_ip_and_roce_version(self):
        config = load_deployment('deployment/deployment.yaml')
        helper = Mock()
        helper.ssh.return_value.stdout = (
            '1 ::ffff:10.150.240.201 IB/RoCE v1\n'
            '3 ::ffff:10.150.240.202 RoCE v2\n'
            '4 ::ffff:10.150.240.201 RoCE v2\n')
        with patch.object(support, 'remote', return_value=helper):
            self.assertEqual(support.gid('dc20:mlx5_0', config), 4)

    def test_launch_uses_configured_launcher_and_remote_timeout(self):
        config = load_deployment('deployment/deployment.yaml')
        helper = Mock()
        helper.ssh.return_value = SimpleNamespace(stdout='', stderr='', returncode=124)
        with patch.object(support, 'remote', return_value=helper) as remote:
            self.assertEqual(support.launch(['30', '--host', 'dc20,dc21', '-np', '2', '/tmp/bin'], config), 124)
        remote.assert_called_once_with(config['mpi']['launcher'], config)
        command = helper.ssh.call_args.args[0]
        self.assertIn('timeout --kill-after=5s 30s', command)
        self.assertIn('--prefix ' + config['mpi']['prefix'], command)

    def test_prepare_reuses_build_and_distribution(self):
        config = load_deployment('deployment/deployment.yaml')
        with tempfile.TemporaryDirectory() as directory:
            endpoints = Path(directory) / 'endpoints'
            endpoints.write_text('dc20:mlx5_0\ndc21:mlx5_0\n')
            with patch.object(support, 'remote'), \
                 patch.object(support, 'target_environments', return_value={'target': 'probe'}) as targets, \
                 patch.object(support, 'build', return_value=(Path('/cache'), {'key': 'hash'})) as build, \
                 patch.object(support, 'distribute', return_value='/remote/build/hash') as distribute:
                result = support.prepare(['connectivity_ring', str(endpoints), '1', '0', ''], config)
                self.assertEqual(result, '/remote/build/hash/mpi_verbs_ringallreduce')
                build.assert_called_once_with('connectivity_ring', config['mpi'], {'target': 'probe'}, allow_build=False)
                self.assertEqual(set(targets.call_args.args[1]), {'dc20', 'dc21'})
                distribute.assert_called_once()

    def test_bandwidth_dry_run_uses_native_defaults(self):
        script = support.ROOT / 'experiments/ai_workload/scripts/check_pair_connectivity.sh'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'endpoints').write_text('dc20:mlx5_0\ndc20:mlx5_2\n')
            subprocess.run([str(script), '--selected-endpoints', 'endpoints', '--outdir', 'out',
                            '--bench', 'bw', '--dry-run'], cwd=root, check=True, capture_output=True)
            log = next((root / 'out').glob('pair_*.log')).read_text()
            command = shlex.split(log.split('command: ', 1)[1])
            self.assertIn('mpi_verbs_p2p_bw', command)
            self.assertEqual(command[command.index('--iters') + 1], '2000')
            self.assertNotIn('--groupsize', command)
            self.assertIn('IB_DEV_MAP=mlx5_0,mlx5_2', command)
            self.assertIn('IB_DEV_MAP_BY_HOST=', command)

    def test_bandwidth_launch_with_same_and_mixed_gid(self):
        script = support.ROOT / 'experiments/ai_workload/scripts/check_pair_connectivity.sh'
        for gids in (('3', '3'), ('3', '4')):
            with self.subTest(gids=gids), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'endpoints').write_text('dc20:mlx5_0\ndc21:mlx5_0\n')
                # Replace only the remote/build adapter process; exercise the real shell control flow.
                fake = root / 'python3'
                fake.write_text('#!' + sys.executable + '\n' +
                    'import json, os, sys\n'
                    'action = sys.argv[2]\n'
                    'with open(os.environ["CALLS"], "a") as f: f.write(json.dumps(sys.argv[2:]) + "\\n")\n'
                    'if action == "prepare": print("/remote/mpi_verbs_p2p_bw")\n'
                    'elif action == "gid": print(os.environ["SRC_GID"] if sys.argv[3].startswith("dc20:") else os.environ["DST_GID"])\n'
                    'elif action == "launch": print("send,1048576,64,16,1048576,imm,95.000,95.000,95.000,95.000")\n')
                fake.chmod(0o755)
                env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                           CALLS=str(root / 'calls'), SRC_GID=gids[0], DST_GID=gids[1],
                           ARTIFACT_LOCK_DIR=str(root / 'locks'))
                subprocess.run([str(script), '--selected-endpoints', 'endpoints', '--outdir', 'out',
                                '--bench', 'bw', '--sizes', '1M', '--mode', 'send',
                                '--inflight', '32', '--iters', '10'], cwd=root, env=env,
                               check=True, capture_output=True, text=True)
                calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
                self.assertEqual([call[1] for call in calls if call[0] == 'prepare'], ['p2p_bw'])
                command = next(call for call in calls if call[0] == 'launch')
                self.assertIn('/remote/mpi_verbs_p2p_bw', command)
                self.assertNotIn('--groupsize', command)
                self.assertEqual(command[command.index('--bench') + 1], 'bw')
                self.assertEqual(command[command.index('--inflight') + 1], '32')
                if gids[0] != gids[1]:
                    self.assertIn('GID_INDEX_BY_HOST_DEV=dc20:mlx5_0=3|dc21:mlx5_0=4', command)
                else:
                    self.assertIn('GID_INDEX=3', command)
                self.assertIn('95.000', next((root / 'out').glob('pair_*.log')).read_text())
