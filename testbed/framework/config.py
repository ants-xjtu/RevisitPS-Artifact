"""Deployment paths are always relative to testbed, never to the caller's cwd."""
import copy
from pathlib import Path
import yaml
from framework.paths import REPO_ROOT as ROOT, resolve_repo_path


def merge(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def load_deployment(path):
    base = yaml.safe_load((ROOT / 'deployment/deployment.yaml').read_text())
    return merge(base, yaml.safe_load(resolve_repo_path(path).read_text()))
