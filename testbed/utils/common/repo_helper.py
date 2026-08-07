import getpass
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def get_repo_root():
    return REPO_ROOT


def resolve_repo_path(path):
    path = Path(path).expanduser()
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def get_remote_user(configured_user=None):
    """Return an explicitly configured user or the current shell user."""
    return (
        configured_user
        or os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or getpass.getuser()
    )


def get_test_conf_path():
    return os.getenv("TEST_CONF_PATH", "")
