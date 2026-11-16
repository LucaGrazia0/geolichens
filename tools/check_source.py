"""Validate distributable sources without importing QGIS or reading datasets."""
import ast
from pathlib import Path
import re
import sys

from build_release import ROOT, source_files, validate


def main():
    files = source_files()
    meta = validate(files)
    errors = []
    for path in files:
        text = path.read_text(encoding='utf-8') if path.suffix in {'.py', '.md', '.txt'} else ''
        if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', text):
            errors.append(f'Private key in {path.relative_to(ROOT)}')
        if path.suffix != '.py':
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == 'ignoreSslErrors':
                    errors.append(f'TLS bypass in {path.relative_to(ROOT)}:{node.lineno}')
    manual = (ROOT / 'docs/MANUALE_UTENTE.md').read_text(encoding='utf-8')
    if f'**Versione del plugin:** {meta["version"]}' not in manual:
        errors.append('User manual version does not match metadata')
    if errors:
        sys.exit('\n'.join(errors))
    print(f'PASS: {len(files)} allowed source files, metadata, syntax, manual version and TLS guard')


if __name__ == '__main__':
    main()
