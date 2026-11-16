"""Release safety checks use disposable source trees, never user datasets."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_release as builder
import prepare_release


class ReleaseSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in builder.ROOT_FILES | builder.ASSET_FILES | builder.REPOSITORY_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# sample\n', encoding='utf-8')
        (self.root / 'gui/icons/locality_centroid.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        (self.root / 'metadata.txt').write_text('''[general]
name=Fixture
version=1.0
qgisMinimumVersion=3.40
author=Test
email=test@example.invalid
description=Test
about=Test
license=GPL-2.0-or-later
homepage=https://example.invalid/home
repository=https://example.invalid/code
tracker=https://example.invalid/issues
''', encoding='utf-8')
        for name in ('data/private.csv', 'knowledge/private.json', 'dist/old/plugin.py',
                     'services/private.json', 'services/__pycache__/old.py'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('DO_NOT_DISTRIBUTE', encoding='utf-8')

    def test_zip_excludes_data_cache_and_old_exports_and_is_reproducible(self):
        with patch.object(builder, 'ROOT', self.root):
            builder.build(source_dir=self.root / 'dist/public-source')
            archive = self.root / 'dist/geolichen-1.0.zip'
            first = hashlib.sha256(archive.read_bytes()).hexdigest()
            builder.build()
            self.assertEqual(first, hashlib.sha256(archive.read_bytes()).hexdigest())
            with ZipFile(archive) as package:
                for name in package.namelist():
                    self.assertNotIn(b'DO_NOT_DISTRIBUTE', package.read(name))
                self.assertNotIn('geolichen/.github/workflows/checks.yml', package.namelist())
            self.assertTrue((self.root / 'dist/public-source/.github/workflows/checks.yml').is_file())
            manifest = json.loads(archive.with_suffix('.manifest.json').read_text())
            self.assertEqual(manifest['zip_sha256'], first)

    def test_symlink_source_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / 'core').symlink_to(outside, target_is_directory=True)
            with patch.object(builder, 'ROOT', self.root), self.assertRaisesRegex(ValueError, 'symlink'):
                builder.source_files()

    def test_failed_checks_stop_before_package_build(self):
        import subprocess
        with patch.object(sys, 'argv', ['prepare_release.py']), patch.object(prepare_release, 'ROOT', self.root), \
                patch.object(prepare_release.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'checks')) as run:
            with self.assertRaises(SystemExit) as error:
                prepare_release.main()
            self.assertEqual(error.exception.code, 1)
            self.assertEqual(run.call_count, 1)
            self.assertIn('check_source.py', ' '.join(run.call_args.args[0]))


if __name__ == '__main__':
    unittest.main()
