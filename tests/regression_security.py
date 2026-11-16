"""Security boundary tests; no network request or real credential is used."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_italic_index import fetch_json, _ItalicHttpsRedirects
from security_audit import blocked, report_finding
from prepare_release import security_environment


class SecurityBoundaries(unittest.TestCase):
    def test_optional_index_builder_rejects_non_api_and_non_https_urls(self):
        for url in ('file:///tmp/local', 'http://italic.units.it/api/v2/checklist/',
                    'https://example.invalid/api/v2/checklist/',
                    'https://italic.units.it/not-api/',
                    'https://italic.units.it:444/api/v2/checklist/',
                    'https://user@italic.units.it/api/v2/checklist/'):
            with self.subTest(url=url), patch('build_italic_index.urllib.request.build_opener') as opener:
                with self.assertRaises(ValueError):
                    fetch_json(url)
                opener.assert_not_called()

    def test_redirect_cannot_downgrade_or_leave_the_official_api(self):
        handler = _ItalicHttpsRedirects()
        for target in ('http://italic.units.it/api/v2/checklist/',
                       'https://example.invalid/api/v2/checklist/', 'file:///tmp/local'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                handler.redirect_request(None, None, 302, 'Found', {}, target)

    def test_official_api_fetch_preserves_json_and_timeout(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps({'checklist': []}).encode()
        with patch('build_italic_index.urllib.request.build_opener', return_value=opener):
            self.assertEqual(fetch_json('https://italic.units.it/api/v2/checklist/', timeout=3), {'checklist': []})
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 3)

    def test_security_python_does_not_inherit_qgis_installation_paths(self):
        values = {'PYTHONHOME': 'qgis-python', 'PYTHONPATH': 'qgis-modules',
                  'PYTHONEXECUTABLE': 'qgis-python', '__PYVENV_LAUNCHER__': 'qgis-launcher',
                  'HTTP_PROXY': 'keep-proxy'}
        with patch.dict(os.environ, values):
            environment = security_environment()
            for key in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONEXECUTABLE', '__PYVENV_LAUNCHER__'):
                self.assertNotIn(key, environment)
                self.assertIn(key, os.environ)
            self.assertEqual(environment['HTTP_PROXY'], 'keep-proxy')

    def test_saved_finding_omits_bandit_password_text_and_source_snippet(self):
        value = 'REDACTION' + 'FIXTURE'
        staging = Path('/temporary/source')
        issue = {'filename': str(staging / 'example.py'), 'line_number': 1,
                 'test_id': 'B105', 'issue_severity': 'MEDIUM', 'issue_confidence': 'MEDIUM',
                 'test_name': 'hardcoded_password_string',
                 'issue_text': f'Possible hardcoded password: {value}', 'code': value}
        finding = report_finding(issue, staging)
        self.assertNotIn(value, json.dumps(finding))
        self.assertNotIn('code', finding)
        self.assertEqual(finding['path'], 'example.py')
        self.assertEqual(finding['test'], 'B105')

    def test_medium_high_secrets_and_scanner_errors_fail_the_gate(self):
        clean = {'results': [], 'errors': []}
        secrets = {'results': {}}
        self.assertFalse(blocked(clean, secrets))
        self.assertFalse(blocked({'results': [{'issue_severity': 'LOW'}]}, secrets))
        for severity in ('MEDIUM', 'HIGH'):
            self.assertTrue(blocked({'results': [{'issue_severity': severity}]}, secrets))
        self.assertTrue(blocked({'results': [], 'errors': ['scan incomplete']}, secrets))
        self.assertTrue(blocked(clean, {'results': {'sample': [{'type': 'fixture'}]}}))


if __name__ == '__main__':
    unittest.main()
