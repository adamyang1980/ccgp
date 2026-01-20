import subprocess
import sys


def main() -> int:
    steps = [
        ([sys.executable, "-m", "compileall", "-q", "."], "compileall"),
        ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], "unittest"),
    ]
    for cmd, name in steps:
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

