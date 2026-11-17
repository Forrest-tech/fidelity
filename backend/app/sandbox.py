"""Run untrusted-file parsing in an isolated child process with a hard timeout.

Usage: run_isolated([sys.executable, "-I", "-m", "some.parser", path], timeout=60)
The child gets a scrubbed environment (no credentials) and is killed on timeout.
"""
import os
import subprocess

SAFE_ENV_KEYS = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "PYTHONUTF8")


class IsolatedTimeout(Exception):
    pass


def run_isolated(cmd, timeout=60, max_output=10_000_000, cwd=None):
    env = {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS}
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise IsolatedTimeout("child exceeded %ss and was killed" % timeout)
    return r.returncode, r.stdout[:max_output], r.stderr[:max_output]
