"""Run all QGIS regression suites in separate processes with a JSON report.

Run with the Python supplied by QGIS (OSGeo4W Shell on Windows).
No public online service or user dataset is used by these suites.
"""
import argparse
import configparser
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    'regression_release_tools.py',
    'regression_scoring.py', 'regression_analysis.py',
    'regression_osm_geocoding.py', 'regression_locality_search.py',
    'regression_interface.py', 'regression_diagnostics.py', 'smoke_qgis.py',
)


def run(report, expect_qgis=None, timeout=300):
    from qgis.core import Qgis
    from qgis.PyQt.QtCore import QT_VERSION_STR
    actual = Qgis.QGIS_VERSION
    if expect_qgis and not (actual == expect_qgis or actual.startswith(expect_qgis + '.')):
        raise ValueError(f'Expected QGIS {expect_qgis}, got {actual}')
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(ROOT / 'metadata.txt', encoding='utf-8')
    result = {'version': metadata['general']['version'], 'qgis': actual,
              'qt': QT_VERSION_STR, 'python': platform.python_version(),
              'platform': platform.platform(), 'suites': [], 'passed': False}
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get('QT_QPA_PLATFORM', 'offscreen'),
               PYTHONDONTWRITEBYTECODE='1')
    target = Path(report)
    target.parent.mkdir(parents=True, exist_ok=True)
    for suite in SUITES:
        print(f'Running {suite}', flush=True)
        start = time.monotonic()
        try:
            process = subprocess.run([sys.executable, '-B', str(ROOT / 'tests' / suite)],
                                     cwd=ROOT, env=env, capture_output=True, text=True,
                                     encoding='utf-8', errors='replace', timeout=timeout)
            code, output = process.returncode, process.stdout + process.stderr
        except subprocess.TimeoutExpired:
            code, output = 124, f'Suite exceeded {timeout} seconds'
        log_path = target.parent / (target.stem + '-' + suite + '.log')
        log_path.write_text(output, encoding='utf-8')
        result['suites'].append({'suite': suite, 'exit_code': code,
                                'seconds': round(time.monotonic() - start, 3),
                                'log': log_path.name})
        print(f'{suite}: {"PASS" if code == 0 else "FAIL"}', flush=True)
        if code:
            print(output[-5000:], flush=True)
        target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    result['passed'] = all(row['exit_code'] == 0 for row in result['suites'])
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result['passed']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', default='dist/checks.json')
    parser.add_argument('--expect-qgis')
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    try:
        passed = run(args.report, args.expect_qgis, args.timeout)
    except (ImportError, ValueError, OSError) as exc:
        parser.exit(1, f'Checks failed: {exc}\nUse the Python supplied by QGIS.\n')
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
