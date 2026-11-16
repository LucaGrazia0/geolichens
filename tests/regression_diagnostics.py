"""Diagnostics preserve failures, avoid sensitive URLs and scope preferences."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtNetwork import QNetworkReply
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('geolichen', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules['geolichen'] = package
spec.loader.exec_module(package)
from geolichen.services import diagnostics_service as diagnostics
from geolichen.services.network_service import fetch_text
from geolichen.services.italic_service import ItalicService
from geolichen.gui.performance_dialog import PerformanceDialog
from geolichen.services.performance_service import PerformanceService


class Diagnostics(unittest.TestCase):
    def test_url_secrets_and_taxon_paths_are_not_logged(self):
        # Synthetic credentials for redaction only; never transmitted.
        # pragma: allowlist nextline secret
        raw = 'https://user:password@italic.units.it/api/v2/match/PrivateTaxon?key=SECRET token=HIDDEN'
        cleaned = diagnostics.safe_message(raw + ' Authorization: Bearer TOPSECRET')
        for value in ('password@', 'PrivateTaxon', 'SECRET', 'HIDDEN', 'TOPSECRET'):
            self.assertNotIn(value, cleaned)
        self.assertIn('italic.units.it', cleaned)

    def test_debug_is_opt_in_and_warnings_remain_available(self):
        with patch.object(diagnostics, 'enabled', return_value=False), patch.object(diagnostics.QgsMessageLog, 'logMessage') as logged:
            diagnostics.log('Photon', 'Detail', 'debug')
            logged.assert_not_called()
            diagnostics.log('Photon', 'Timeout')
            self.assertEqual(logged.call_count, 1)
        with patch.object(diagnostics, 'enabled', return_value=True), patch.object(diagnostics.QgsMessageLog, 'logMessage') as logged:
            diagnostics.log('Photon', 'Detail', 'debug')
            self.assertEqual(logged.call_count, 1)

    def test_ssl_failure_is_explained_without_bypass(self):
        reply = MagicMock()
        reply.attribute.return_value = None
        reply.error.return_value = QNetworkReply.NetworkError.SslHandshakeFailedError
        with patch('geolichen.services.network_service.QgsNetworkAccessManager.blockingGet', return_value=reply):
            with self.assertRaisesRegex(OSError, 'ITALIC.*Certificato HTTPS non verificato'):
                fetch_text('https://italic.units.it/api/v2/match/PrivateTaxon?key=SECRET')
        reply.ignoreSslErrors.assert_not_called()

    def test_http_error_preserves_status_and_redacts_query(self):
        reply = MagicMock()
        reply.attribute.return_value = 503
        with patch('geolichen.services.network_service.QgsNetworkAccessManager.blockingGet', return_value=reply):
            with self.assertRaisesRegex(OSError, 'HTTP 503') as caught:
                fetch_text('https://photon.komoot.io/api/?q=PRIVATE')
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_italic_fresh_and_expired_cache_preserve_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ItalicService(cache_path=str(Path(directory) / 'cache.json'))
            profile = service._empty_profile('Test species')
            profile.update(source='ITALIC_API', substrata='rock', rock_type='acidic', engine_version=service.ENGINE_VERSION)
            service._save_cache('Test species', profile)
            with patch.object(service, '_fetch_text', side_effect=OSError('offline')) as fetch:
                fresh = service.fetch_profile('Test species')
                fetch.assert_not_called()
                self.assertEqual(fresh['rock_type'], 'acidic')
            with patch.object(service, 'CACHE_TTL_SECONDS', -1), patch.object(service, '_fetch_text', side_effect=OSError('offline')):
                stale = service.fetch_profile('Test species')
                self.assertEqual(stale['cache_status'], 'expired_used_as_fallback')
                self.assertEqual(stale['rock_type'], fresh['rock_type'])

    def test_phase_measurement_records_failure_and_releases_active_token(self):
        service = PerformanceService()
        with service.measure('download_sentieri_osm') as details:
            details.update(success=False, from_cache=False)
        self.assertEqual(service.records[-1]['status'], 'error')
        with self.assertRaisesRegex(ValueError, 'original error'):
            with service.measure('calcolo_ecologico'):
                raise ValueError('original error')
        self.assertFalse(service._active)
        self.assertEqual(service.records[-1]['status'], 'error')
        self.assertGreaterEqual(service.records[-1]['duration_s'], 0)

    def test_dialog_updates_only_scoped_diagnostic_setting(self):
        from qgis.PyQt.QtWidgets import QMainWindow
        from types import SimpleNamespace
        window = QMainWindow()
        iface = SimpleNamespace(mainWindow=lambda: window)
        with patch.object(diagnostics, 'enabled', return_value=False), patch.object(diagnostics, 'set_enabled') as setter:
            dialog = PerformanceDialog(iface, PerformanceService())
            setter.assert_not_called()
            dialog.chkDiagnostics.setChecked(True)
            setter.assert_called_once_with(True)
            self.assertIn('qgis', dialog._environment())
            dialog.close()
        window.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, directory)
        app = QgsApplication([], True, directory)
        app.initQgis()
        unittest.main()
