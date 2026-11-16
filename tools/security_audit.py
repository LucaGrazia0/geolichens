"""Offline security scan of exactly the distributable and public-source files.

Never scans private data/history, verifies credentials online, or changes QGIS.
Reports retain low-severity findings; medium/high issues or potential secrets
block the check. This is a local policy, not QGIS catalogue approval.
"""
import argparse
from collections import Counter
import configparser
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from build_release import ROOT, REPOSITORY_FILES, source_files


def blocked(bandit_report, secrets_report):
    return (bool(bandit_report.get('errors'))
            or any(issue['issue_severity'] in ('MEDIUM', 'HIGH')
                   for issue in bandit_report['results'])
            or any(secrets_report['results'].values()))


def report_finding(issue, staging):
    """Bandit issue_text can contain a detected password: never export it."""
    return {
        'path': Path(issue['filename']).relative_to(staging).as_posix(),
        'line': issue['line_number'], 'test': issue['test_id'],
        'severity': issue['issue_severity'], 'confidence': issue['issue_confidence'],
        'description': issue['test_name'],
    }


def audit(report_path):
    versions = {name: importlib.metadata.version(name) for name in ('bandit', 'detect-secrets')}
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(ROOT / 'metadata.txt', encoding='utf-8')
    # A clean allowlisted tree avoids unrelated caches, personal records and
    # previous scan reports. Include development workflow configuration too.
    paths = source_files() + [ROOT / name for name in sorted(REPOSITORY_FILES)]
    hashes = {}
    with tempfile.TemporaryDirectory(prefix='geolichen_security_') as directory:
        temporary = Path(directory)
        staging = temporary / 'source'
        for source in paths:
            if not source.is_file() or source.is_symlink():
                raise ValueError('Missing or unsafe source: ' + str(source.relative_to(ROOT)))
            name = source.relative_to(ROOT).as_posix()
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        bandit_path = temporary / 'bandit.json'
        process = subprocess.run(
            [sys.executable, '-B', '-m', 'bandit', '-r', str(staging),
             '-f', 'json', '-o', str(bandit_path)],
            capture_output=True, text=True, timeout=180, check=False)
        if process.returncode not in (0, 1) or not bandit_path.is_file():
            raise RuntimeError('Bandit failed to complete; no successful audit')
        bandit = json.loads(bandit_path.read_text(encoding='utf-8'))
        process = subprocess.run(
            [sys.executable, '-B', '-m', 'detect_secrets', 'scan', '--all-files',
             '--no-verify', str(staging)],
            capture_output=True, text=True, timeout=180, check=True)
        secrets = json.loads(process.stdout)
        # No source snippets, raw credential values or temporary paths in the
        # saved report/log. Inspect flagged lines locally before sharing.
        findings = [report_finding(issue, staging) for issue in bandit['results']]
        secret_findings = [
            {'path': Path(path).relative_to(staging).as_posix(),
             'line': item['line_number'], 'type': item['type']}
            for path, items in secrets['results'].items() for item in items
        ]
        passed = not blocked(bandit, secrets)
        report = {
            'version': metadata['general']['version'], 'scanner_versions': versions,
            'scope': 'allowlisted release plus public development configuration; current source only',
            'credential_network_verification': False,
            'passed': passed, 'files': hashes,
            'bandit_counts': dict(Counter(item['severity'] for item in findings)),
            'bandit_errors': [{'scanner_error': True} for _ in bandit.get('errors', [])],
            'bandit_findings': findings,
            'potential_secrets': secret_findings,
            'limits': ['Not a penetration test or dependency/OS audit',
                       'Not a scan of private datasets or Git history',
                       'Low-severity findings remain visible',
                       'Does not replace QGIS catalogue scanning or approval'],
        }
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'version': report['version'], 'passed': passed,
                          'files': len(hashes), 'bandit': report['bandit_counts'],
                          'potential_secrets': len(secret_findings)}, indent=2))
        return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', default='dist/security-audit.json')
    args = parser.parse_args()
    try:
        passed = audit(args.report)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError,
            importlib.metadata.PackageNotFoundError) as exc:
        parser.exit(2, f'Security audit did not complete: {type(exc).__name__}.\n')
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
