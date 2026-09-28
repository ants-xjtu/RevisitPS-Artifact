"""Deploy all switches before configuring/validating inter-switch physical links."""
import shlex
import click
from framework.conf_parser.yaml_parser import SwitchConfParser
from switches.remote import RemoteTofinoHelper
from framework.remote import logged_run, SSH_OPTIONS
from framework.paths import resolve_repo_path
from framework.progress import progress, stage


def run_switch_config(test_conf_parser, do_build=False, do_run=False, do_config=False, built=None):
    conf = test_conf_parser.get()
    settings = conf.applications.remote_tofino
    switches = SwitchConfParser(conf.config.switches)
    switches.load_conf_file()
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
            for key in ('topo', 'switches', 'hosts'):
                destination = config_dir + '/' + key + '.yaml'
                logged_run(['scp', *SSH_OPTIONS, conf.config.get(key), helper.remote.target + ':' + destination], 60)
                remote_configs[key] = destination
        deployments.append((helper, program, remote_configs))
    if do_run:
        for helper, program, _ in deployments:
            with stage(f'Switch deployment: {helper.switch_id} / {program["name"]}'):
                helper.remote_deploy(settings.cmd.deploy, program['name'])
    if do_config:
        for helper, program, paths in deployments:
            with stage(f'Switch BFRT configuration: {helper.switch_id}'):
                helper.remote_config(settings.cmd.config, program['cp_script_path'], settings.grpc_listen_port, **paths)
        for helper, _, paths in deployments:
            verify = settings.cmd.config.replace('{{cp_script_path}}', 'switches/scripts/verify.py')
            verify = verify.replace(' --topo {{topo}}', '').replace(' --hosts {{hosts}}', '')
            with stage(f'Switch readback verification: {helper.switch_id}'):
                helper.remote_config(verify, 'switches/scripts/verify.py', settings.grpc_listen_port, **paths)


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
