"""Run the portable regression suite without changing live app data."""

import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root / "src"), PYTHONDONTWRITEBYTECODE="1")
    commands = [
        ([sys.executable, "-B", "tools/sync_contract.py", "--check"], root),
        ([sys.executable, "-B", "-m", "unittest", "-v", "test_editor_units"], root),
        ([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"], root),
    ]
    # Contract regression tests live with the app source as well as at the
    # old standalone entry point. They always run in an independent checkout.
    for command, directory in commands:
        result = subprocess.run(command, cwd=directory, env=env)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
