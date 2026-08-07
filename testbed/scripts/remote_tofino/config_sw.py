#!/usr/bin/python3
import os
import sys
import yaml
import click

from conf_parser.yaml_parser import SwitchConfParser, TestConfParser
from conf_parser.ini_parser import GenericConfParser
from common.remote_tofino_helper import RemoteTofinoHelper
from common.repo_helper import get_remote_user, resolve_repo_path

@click.group()
def cli():
    """Switch configuration tool with build/run/config commands"""
    pass


def run_switch_config(test_conf_parser: TestConfParser, do_build=False, do_run=False, do_config=False):
    test_conf = test_conf_parser.get()
    grpc_listen_port = test_conf.applications.remote_tofino.grpc_listen_port
    remote_user = get_remote_user(
        test_conf.get("applications.remote_tofino.user")
    )
    root_path = resolve_repo_path(test_conf.get("root_path", "."))
    # ---------- Experiment Config Paths ----------
    switch_conf_path = test_conf.config.switches
    topo_conf_path = test_conf.config.topo
    host_conf_path = test_conf.config.hosts

    build_cmd = test_conf.applications.remote_tofino.cmd.build
    deploy_cmd = test_conf.applications.remote_tofino.cmd.deploy
    config_cmd = test_conf.applications.remote_tofino.cmd.config
    try:
        # ---------- Load Switch Config ----------
        switch_conf_parser = SwitchConfParser(switch_conf_path)
        switch_conf_parser.load_conf_file()

        ignored_files = test_conf.applications.remote_tofino.sync_ingore_dirs


        # ---------- Pre-resolve constant target_path ----------
        # target_path depends only on remote_user + repo name → compute once.
        remote_cwd = test_conf.applications.remote_tofino.cwd
        
        # ---------- Iterate through switches ----------
        for switch_hostname, cfg in switch_conf_parser.switches.items():
            arch = cfg["arch"]
            program = cfg["program"]
            program_name = program['name']
            program_path = program['path']
            cp_script_path = program['cp_script_path']
            
            helper = RemoteTofinoHelper(
                remote_user=remote_user,
                switch_hostname=switch_hostname,
                remote_cwd=remote_cwd,
                arch=arch,
            )

            # ---- Sync repo (one-time logic) ----
            helper.sync_repo(
                repo_path=str(root_path),
                exclude_paths=ignored_files,
            )

            # ---- Build ----
            if do_build:
                click.echo(f"[{switch_hostname}] Building program {program}")
                helper.remote_build(
                    build_cmd=build_cmd,
                    p4program_path=program_path,
                )

            # ---- Run ----
            if do_run:
                click.echo(f"[{switch_hostname}] Running bf_switchd for {program}")
                helper.remote_deploy(deploy_cmd=deploy_cmd, p4program_name=program_name)

            # ---- Configure ----
            if do_config:
                click.echo(f"[{switch_hostname}] Configuring control plane")
                helper.remote_config(
                    config_cmd=config_cmd,
                    cp_script_path=cp_script_path,
                    port=grpc_listen_port,
                    topo=topo_conf_path,
                    switches=switch_conf_path,
                    hosts=host_conf_path
                )

    except Exception as e:
        click.echo(f"Error: {e}")
        sys.exit(1)
   

@cli.command()
def sw(test_conf_parser):
    """Do build, run, and config (all in one)"""
    run_switch_config(test_conf_parser, do_build=True, do_run=True, do_config=True)


@cli.command()
def sw_build(test_conf_parser):
    """Build the switch program"""
    run_switch_config(test_conf_parser, do_build=True)


@cli.command()
def sw_run(test_conf_parser):
    """Run bf_switchd"""
    run_switch_config(test_conf_parser, do_run=True)


@cli.command()
def sw_config(test_conf_parser):
    """Configure control plane"""
    run_switch_config(test_conf_parser, do_config=True)


if __name__ == '__main__':
    cli()
