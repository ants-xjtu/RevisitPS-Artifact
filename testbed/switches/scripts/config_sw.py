"""Deploy all switches before configuring/validating inter-switch physical links."""
import shlex
import shutil
import tempfile
import re
from pathlib import Path
import click
from framework.conf_parser.yaml_parser import SwitchConfParser
from switches.remote import RemoteTofinoHelper
from framework.remote import logged_run, SSH_OPTIONS
from framework.paths import resolve_repo_path
from framework.progress import progress, stage
from framework.results import canonical_hash, digest


def switch_process_identity(helper):
    command = ('cat /proc/sys/kernel/random/boot_id; pids=$(pgrep -x bf_switchd) && '
               'for pid in $pids; do awk \'{print $1, $22}\' /proc/$pid/stat; done')
    result = helper.remote.ssh(command, check=False)
    if result.returncode or not result.stdout.strip():
        return None
    return sorted(result.stdout.splitlines())


def verify_deployments(deployments, settings, require_identity=False):
    identities = []
    for helper, _, paths in deployments:
        verify = settings.cmd.config.replace('{{cp_script_path}}', 'switches/scripts/verify.py')
        verify = verify.replace(' --topo {{topo}}', '').replace(' --hosts {{hosts}}', '')
        with stage(f'Switch readback verification: {helper.switch_id}'):
            output = helper.remote_config(verify, 'switches/scripts/verify.py', settings.grpc_listen_port, **paths)
            if require_identity:
                matches = re.findall(r'^ARTIFACT_SWITCH_STATE=([0-9a-f]{64})$', output, re.MULTILINE)
                if len(matches) != 1:
                    raise RuntimeError(f'{helper.switch_id}: missing switch readback identity')
                identities.append(matches[0])
    return identities


def run_switch_config(test_conf_parser, do_build=False, do_run=False, do_config=False, built=None, reuse=None):
    conf = test_conf_parser.get()
    settings = conf.applications.remote_tofino
    switches = SwitchConfParser(conf.config.switches)
    switches.load_conf_file()
    reuse_key = None
    if reuse is not None and do_run and do_config:
        source_root = resolve_repo_path(conf.root_path) / 'switches'
        reuse_key = canonical_hash(dict(
            configs={name: digest(Path(conf.config.get(name))) for name in ('topo', 'switches', 'hosts')},
            settings={name: settings.get(name) for name in ('user', 'cwd', 'grpc_listen_port')},
            commands={name: settings.cmd.get(name) for name in ('build', 'deploy', 'config')},
            sources={str(p.relative_to(source_root)): digest(p) for p in source_root.rglob('*')
                     if p.is_file() and p.suffix in ('.py', '.p4', '.sh')}))
        if reuse.get('key') == reuse_key:
            active = reuse['deployments']
            identities = [switch_process_identity(helper) for helper, _, _ in active]
            if all(identities) and identities == reuse['processes']:
                # Read current hardware even when the intended configuration is unchanged.
                expected = reuse['readback']
                reuse.clear()
                actual = verify_deployments(active, settings, require_identity=True)
                if actual == expected:
                    reuse.update(key=reuse_key, deployments=active, processes=identities, readback=actual)
                    progress('Reusing verified switch deployment for the next AI workload')
                    return
                progress('Switch readback changed; restoring the requested deployment')
        reuse.clear()
    deployments = []
    for name, switch in switches.switches.items():
        with stage(f'Switch source synchronization: {name}'):
            helper = RemoteTofinoHelper(switch.get('user', settings.get('user')),
                                        switch.get('management', name), settings.cwd,
                                        switch['arch'], switch_id=name)
            helper.sync_repo(str(resolve_repo_path(conf.root_path)), settings.sync_ingore_dirs)
        program = switch['program']
        build_key = (helper.remote.target, program['path'], settings.cmd.build)
        if do_build and (built is None or build_key not in built):
            with stage(f'P4 build: {name} / {program["name"]}'):
                helper.remote_build(settings.cmd.build, program['path'])
            if built is not None:
                built.add(build_key)
        elif do_build:
            progress(f'SKIP P4 build: {name} / {program["name"]} (already built in this run)')
        remote_configs = {}
        config_dir = helper.remote_cwd + '/runtime/configs/' + helper.run_id
        with stage(f'Switch configuration upload: {name}'):
            helper.remote.ssh('mkdir -p ' + shlex.quote(config_dir))
            with tempfile.TemporaryDirectory(prefix='switch-config-') as folder:
                sources = []
                for key in ('topo', 'switches', 'hosts'):
                    source = Path(folder) / (key + '.yaml')
                    shutil.copyfile(conf.config.get(key), source)
                    sources.append(str(source))
                    remote_configs[key] = config_dir + '/' + key + '.yaml'
                logged_run(['scp', *SSH_OPTIONS, *sources,
                            helper.remote.target + ':' + shlex.quote(config_dir + '/')], 60)
        deployments.append((helper, program, remote_configs))
    if do_run:
        for helper, program, _ in deployments:
            with stage(f'Switch deployment: {helper.switch_id} / {program["name"]}'):
                helper.remote_deploy(settings.cmd.deploy, program['name'])
    if do_config:
        for helper, program, paths in deployments:
            with stage(f'Switch BFRT configuration: {helper.switch_id}'):
                helper.remote_config(settings.cmd.config, program['cp_script_path'], settings.grpc_listen_port, **paths)
        readback = verify_deployments(deployments, settings, require_identity=reuse_key is not None)
    if reuse_key is not None:
        identities = [switch_process_identity(helper) for helper, _, _ in deployments]
        if not all(identities):
            raise RuntimeError('Switch process disappeared after configuration')
        reuse.update(key=reuse_key, deployments=deployments, processes=identities, readback=readback)


@click.command()
def sw(test_conf_parser):
    run_switch_config(test_conf_parser, do_build=True, do_run=True, do_config=True)


@click.command()
def sw_build(test_conf_parser):
    run_switch_config(test_conf_parser, do_build=True)


@click.command()
def sw_run(test_conf_parser):
    run_switch_config(test_conf_parser, do_run=True)


@click.command()
def sw_config(test_conf_parser):
    run_switch_config(test_conf_parser, do_config=True)
