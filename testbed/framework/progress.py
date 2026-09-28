"""Coarse, immediately flushed progress for long artifact stages."""
from contextlib import contextmanager
import time


def progress(message):
    print(f'[{time.strftime("%H:%M:%S")}] [progress] {message}', flush=True)


@contextmanager
def stage(label):
    started = time.monotonic()
    progress(f'RUN {label}')
    try:
        yield
    except BaseException as exc:
        progress(f'FAIL {label} ({time.monotonic() - started:.1f}s): {exc or type(exc).__name__}')
        raise
    else:
        progress(f'DONE {label} ({time.monotonic() - started:.1f}s)')
