import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from framework.cli import main
from framework.config import load_deployment
from framework import runner
from experiments.ai_workload.scripts import run, build, parse, plot

ROOT = Path(__file__).resolve().parents[2]


def specs(workload='all', mode='all'):
    return run.specifications(SimpleNamespace(workload=workload, network_mode=mode), load_deployment('deployment/deployment.yaml'))


def normalize(command, binary):
    """Compare all measurement options; exclude explicitly changed orchestration paths."""
    index = command.index(binary)
    launcher = command[1:index]
    exports = []; options = {}
    i = 0
    while i < len(launcher):
        flag = launcher[i]; value = launcher[i + 1]; i += 2
        if flag == '-x':
            if value != 'LD_LIBRARY_PATH':
                exports.append(value)
        elif flag not in ('--prefix', '--wdir', '--map-by'):
            options[flag] = value
    args = command[index + 1:]; benchmark = {}; i = 0
    while i < len(args):
        flag = args[i]; i += 1
        value = True
        if i < len(args) and not args[i].startswith('--'):
            value = args[i]; i += 1
        if flag not in ('--group-dump-csvs', '--group-dump-iter-fct'):
            benchmark[flag] = value
    return dict(options=options, exports=sorted(exports), benchmark=benchmark)


class AiTests(unittest.TestCase):
    def test_old_engine_commands_and_rankfiles_are_equivalent(self):
        baseline = json.loads((Path(__file__).parent / 'legacy_commands.json').read_text())
        mpi = load_deployment('deployment/deployment.yaml')['mpi']
        for workload, old in baseline.items():
            spec = specs(workload)[0]
            command = run.mpi_command(spec, mpi, '/run', '/binary', 3)
            self.assertEqual(normalize(old['command'], old['binary']), normalize(command, '/binary'))
            self.assertEqual(old['rankfile'].strip(), run.merged_rankfile(spec).strip())

    def test_dry_run_never_accesses_hardware_builds_or_creates_results(self):
        with patch('subprocess.run', side_effect=AssertionError('subprocess in dry-run')), \
             patch.object(build, 'build', side_effect=AssertionError('build in dry-run')), \
             patch.object(Path, 'mkdir', side_effect=AssertionError('output in dry-run')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            main(['--experiment', 'ai_workload', '--workload', 'all', '--network-mode', 'all',
                  '--run-id', 'dry-test', '--repeat', '2', '--dry-run'])
        tasks = json.loads(output.getvalue())['tasks']
        self.assertEqual(len(tasks), 36)
        self.assertEqual([task['spec']['workload'] for task in tasks[::12]], ['ring_allreduce', 'alltoall', 'alltoallv'])

    def test_launcher_must_own_each_group_csv(self):
        deployment = load_deployment('deployment/deployment.yaml')
        deployment['mpi']['launcher'] = 'dc21'
        with self.assertRaisesRegex(ValueError, 'rank 0'):
            run.specifications(SimpleNamespace(workload='all', network_mode='all'), deployment)

    def test_short_invalid_or_nonfinite_samples_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'group.csv'
            for rows in ('iter,jct_us\n0,1\n', 'iter,jct_us\n0,1\n1,nan\n',
                         'iter,jct_us\n0,1\n0,2\n', 'iter,jct_us\n0,0\n1,2\n'):
                path.write_text(rows)
                with self.assertRaises(ValueError):
                    parse.samples(path, 2)
            path.write_text('iter,jct_us\n0,1\n1,4\n')
            self.assertEqual(parse.summarize(parse.samples(path, 2))['p99_us'], 4)

    def test_timeout_cleans_launcher_and_each_owned_rank(self):
        spec = specs('alltoall')[0]; spec['parameters']['iters'] = 2
        mpi = load_deployment('deployment/deployment.yaml')['mpi']
        remotes = {host: Mock(target='user@' + host) for host in ('dc20', 'dc21', 'dc22', 'dc23')}
        for remote in remotes.values():
            remote.ssh.return_value = SimpleNamespace(stdout='')
        launcher = remotes['dc20']; launcher.start.return_value = dict(log='/log', state='/state', token='t')
        launcher.wait.side_effect = TimeoutError('test timeout')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TimeoutError):
                run.execute(spec, mpi, Path(directory), remotes, '/bin', '/run', 3, 1)
            self.assertEqual(sum(remote.stop.call_count for remote in remotes.values()), 17)
            journal = [json.loads(line) for line in (Path(directory) / 'processes.jsonl').read_text().splitlines()]
            self.assertEqual(len(journal), 16)
            self.assertTrue(all(not p['process_group'] for p in journal))

    def test_failed_start_acknowledgement_still_cleans_owned_launcher(self):
        spec = specs('alltoall')[0]
        mpi = load_deployment('deployment/deployment.yaml')['mpi']
        remotes = {host: Mock(target='user@' + host) for host in ('dc20', 'dc21', 'dc22', 'dc23')}
        for remote in remotes.values():
            remote.ssh.return_value = SimpleNamespace(stdout='')
        launcher = remotes['dc20']; launcher.processes = []
        owned = dict(log='/log', state='/state', token='owned')
        def failed_start(*args):
            launcher.processes.append(owned)
            raise TimeoutError('PID acknowledgement lost')
        launcher.start.side_effect = failed_start
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TimeoutError):
                run.execute(spec, mpi, Path(directory), remotes, '/bin', '/run', 3, 1)
        self.assertIn(unittest.mock.call(owned), launcher.stop.call_args_list)
        self.assertEqual(sum(remote.stop.call_count for remote in remotes.values()), 17)

    def test_missing_group_csv_does_not_complete_even_when_mpi_succeeds(self):
        spec = specs('alltoall')[0]; spec['parameters']['iters'] = 2
        mpi = load_deployment('deployment/deployment.yaml')['mpi']
        remotes = {host: Mock(target='user@' + host) for host in ('dc20', 'dc21', 'dc22', 'dc23')}
        for remote in remotes.values():
            remote.ssh.return_value = SimpleNamespace(stdout='')
        remotes['dc20'].start.return_value = dict(log='/log', state='/state', token='t')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(FileNotFoundError):
                run.execute(spec, mpi, Path(directory), remotes, '/bin', '/run', 3, 1)

    def test_result_integrity_and_offline_plot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); attempt = root / 'tasks/test/attempt-001'
            (attempt / 'configs').mkdir(parents=True); (attempt / 'raw').mkdir()
            spec = specs('alltoall')[0]; spec['parameters']['iters'] = 2
            runner.atomic_json(attempt / 'configs/ai.json', spec)
            for group in spec['groups']:
                (attempt / 'raw' / (group['name'] + '.csv')).write_text('iter,jct_us\n0,10\n1,20\n')
            files = {str(p.relative_to(attempt)): runner.digest(p) for p in attempt.rglob('*') if p.is_file()}
            state = {'tasks': {'t': dict(task_id='t', status='completed', repeat=1,
                     attempt=str(attempt.relative_to(root)), files=files)}}
            with patch('subprocess.run', side_effect=AssertionError('external process')):
                rows = parse.parse_results(root, state)
                plot.plot_results(root)
            self.assertEqual(len(rows), 2)
            self.assertTrue((root / 'figures/alltoall.png').exists())
            (attempt / 'raw/nic02.csv').write_text('bad')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                parse.parse_results(root, state)

    def test_build_identity_rejects_incompatible_mpi_before_compilation(self):
        mpi = load_deployment('deployment/deployment.yaml')['mpi']
        def local(argv, **kwargs):
            result = {'--showme': 'g++ -lmpi', '--version': 'g++ version', '--showme:version': 'Open MPI 4.1.4',
                      '-m': 'x86_64', 'GNU_LIBC_VERSION': 'glibc 2.36', '-p': 'libraries'}
            return SimpleNamespace(stdout=result[argv[-1]])
        with patch.object(build, 'logged_run', side_effect=local), \
             patch('subprocess.run', side_effect=AssertionError('must not compile')):
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                build.build('alltoall', mpi, {'dc20': 'x86_64\nglibc 2.36\nmpirun (Open MPI) 4.1.2'})

    def test_rank_cleanup_targets_pid_not_unrelated_process_group(self):
        from framework.remote import RemoteRDMAHelper
        remote = RemoteRDMAHelper('u', 'h')
        with patch.object(remote, 'ssh') as ssh:
            remote.stop(dict(state='/owned', token='secret', process_group=False))
        self.assertIn('kill -TERM -- $pid', ssh.call_args.args[0])
        self.assertNotIn('kill -TERM -- -$pid', ssh.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
