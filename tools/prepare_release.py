"""Build a release only after source checks and all local QGIS suites pass."""
import argparse
import configparser
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def security_environment():
    """Do not pass QGIS's Python installation paths to a separate Python."""
    environment = dict(os.environ)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONEXECUTABLE', '__PYVENV_LAUNCHER__'):
        environment.pop(key, None)
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--security-python', default=sys.executable,
                        help='Developer Python with bandit/detect-secrets; keep separate from QGIS')
    parser.add_argument('--source-dir', help='New clean public source folder inside dist/')
    args = parser.parse_args()
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(ROOT / 'metadata.txt', encoding='utf-8')
    version = metadata['general']['version']
    commands = [
        [sys.executable, '-B', 'tools/check_source.py'],
        [args.security_python, '-B', 'tools/security_audit.py', '--report', f'dist/security-{version}.json'],
        [sys.executable, '-B', 'tools/run_checks.py', '--report', f'dist/checks-{version}.json'],
        [sys.executable, '-B', 'tools/build_release.py'],
    ]
    if args.source_dir:
        commands[-1] += ['--source-dir', args.source_dir]
    try:
        for command in commands:
            environment = security_environment() if 'tools/security_audit.py' in command else None
            subprocess.run(command, cwd=ROOT, check=True, env=environment)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f'Release stopped: check exited {exc.returncode}.\n')


if __name__ == '__main__':
    main()
