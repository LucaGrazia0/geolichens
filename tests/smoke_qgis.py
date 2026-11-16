"""Run with QGIS Python, e.g. QT_QPA_PLATFORM=offscreen python -B tests/smoke_qgis.py.

Uses an isolated temporary QGIS profile and a local HTTP server; no API keys or
external services are needed. This checks loading, not scientific accuracy.
"""

import importlib
import importlib.util
import configparser
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from qgis.PyQt.QtCore import QObject, QSettings, QUrl, pyqtSignal
from qgis.PyQt.QtWidgets import QMainWindow
from qgis.core import Qgis, QgsApplication, QgsVectorLayer
from qgis.gui import QgsMapCanvas


ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        Handler.last_get_agent = self.headers.get('User-Agent', '')
        if self.path.startswith("/slow"):
            time.sleep(0.4)
        status = 403 if self.path.startswith("/error") else 200
        self.send_response(status)
        self.end_headers()
        try:
            self.wfile.write(json.dumps({"message": "caffè"}).encode("utf-8"))
        except BrokenPipeError:
            pass

    def do_POST(self):
        if self.path.startswith('/slow-overpass'):
            time.sleep(3)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"elements":[]}')
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        Handler.last_post = (body, self.headers.get('User-Agent', ''))
        valid = body.startswith(b'data=') and self.headers.get('User-Agent', '').startswith('GeoLichen/')
        status = 429 if self.path.startswith('/rate-limit') else (200 if valid else 400)
        self.send_response(status)
        self.end_headers()
        elements = []
        if self.path.startswith('/trails'):
            elements = [{'type': 'way', 'id': 123, 'tags': {'highway': 'path'},
                         'geometry': [{'lon': 10.198, 'lat': 46.05}, {'lon': 10.202, 'lat': 46.05}]}]
        self.wfile.write(json.dumps({'elements': elements}).encode())


class Iface(QObject):
    currentLayerChanged = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.window = QMainWindow()
        self.canvas = QgsMapCanvas(self.window)
        self.actions = []
        self.toolbar_actions = []

    def mainWindow(self):
        return self.window

    def mapCanvas(self):
        return self.canvas

    def activeLayer(self):
        return None

    def addPluginToMenu(self, menu, action):
        self.actions.append(action)

    def removePluginMenu(self, menu, action):
        self.actions.remove(action)

    def addToolBarIcon(self, action):
        self.toolbar_actions.append(action)

    def removeToolBarIcon(self, action):
        self.toolbar_actions.remove(action)

    def addDockWidget(self, area, widget):
        self.window.addDockWidget(area, widget)

    def removeDockWidget(self, widget):
        self.window.removeDockWidget(widget)


def main():
    with tempfile.TemporaryDirectory(prefix="geolichen_smoke_") as temporary:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, temporary)
        app = QgsApplication([], True, temporary)
        app.initQgis()
        spec = importlib.util.spec_from_file_location(
            "geolichen", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules["geolichen"] = package
        spec.loader.exec_module(package)
        # Some desktop QGIS Python launchers restore their default profile
        # during initQgis. Override only the path accessor in this test process.
        profile_path = patch.object(QgsApplication, "qgisSettingsDirPath",
                                    return_value=temporary)
        profile_path.start()
        modules = []
        for folder in ("core", "controllers", "models", "gui", "services"):
            for path in sorted((ROOT / folder).rglob("*.py")):
                if path.name == "__init__.py":
                    continue
                name = "geolichen." + ".".join(path.relative_to(ROOT).with_suffix("").parts)
                importlib.import_module(name)
                modules.append(name)
        print(f"PASS: {len(modules)} modules imported on QGIS {Qgis.QGIS_VERSION}")

        iface = Iface()
        plugin = package.classFactory(iface)
        plugin.initGui()
        assert len(iface.actions) == 5
        plugin.run()
        assert plugin.controller is not None and plugin.dock is not None
        # Open the other entry points to catch deferred import/widget failures.
        plugin.open_validation()
        plugin.open_benchmark()
        plugin.open_performance()
        plugin.open_release_readiness()
        plugin.unload()
        app.processEvents()
        assert not iface.actions and not iface.toolbar_actions
        print("PASS: enable, main dock, four auxiliary dialogs and unload")

        from geolichen.services.italic_service import ItalicService
        from geolichen.services.italic_snapshot_service import ItalicSnapshotService
        italic = ItalicService()
        snapshot = ItalicSnapshotService()
        assert Path(italic.cache_path).is_relative_to(Path(temporary))
        assert Path(snapshot.snapshot_path).is_relative_to(Path(temporary))
        assert "snapshot_save_error" not in snapshot.save_snapshot({"scientific_name": "Demo"})
        assert Path(snapshot.snapshot_path).exists()
        print("PASS: cache and snapshots use isolated writable profile")

        from geolichen.services.field_mapper_service import FieldMapperService
        # Generate disposable test input; no dataset is bundled or published.
        sample = Path(temporary) / "sample.csv"
        sample.write_text(
            "record_id,municipality,locality,scientific_name\n"
            "TEST-1,Test municipality,Test locality,Test species\n",
            encoding="utf-8",
        )
        uri = QUrl.fromLocalFile(str(sample))
        uri.setQuery("type=csv&geomType=none&detectTypes=yes")
        table = QgsVectorLayer(uri.toString(), "Synthetic GeoLichen records", "delimitedtext")
        assert table.isValid() and table.featureCount() == 1
        mapping = FieldMapperService().suggest_mapping(table.fields().names())
        assert mapping.is_valid() and mapping.scientific_name == "scientific_name"
        print("PASS: temporary CSV loads in QGIS and input fields map correctly")

        from geolichen.services.knowledge_base import GeoLichenKnowledgeBase
        from geolichen.services.italic_index_service import ItalicIndexService
        missing = Path(temporary) / "no_datasets"
        knowledge = GeoLichenKnowledgeBase(base_path=missing)
        assert knowledge.locality_aliases() == {}
        assert knowledge.observed_substrate_terms() == {}
        assert knowledge.soil_ph() == {}
        assert ItalicIndexService(index_path=str(missing / "index.json")).lookup("Test species") is None
        print("PASS: missing optional dictionaries and taxon index use fallbacks")

        from geolichen.services.network_service import fetch_text
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            assert json.loads(fetch_text(base, timeout=2))["message"] == "caffè"
            fetch_text(base, timeout=2, headers={'User-Agent': 'GeoLichen/test'})
            assert Handler.last_get_agent == 'GeoLichen/test'
            fetch_text(base, timeout=2)
            assert not Handler.last_get_agent.startswith('GeoLichen/')
            assert italic._fetch_json(base)["message"] == "caffè"
            try:
                fetch_text(base + "/error?key=DO_NOT_EXPOSE", timeout=2)
            except OSError as exc:
                assert "403" in str(exc) and "DO_NOT_EXPOSE" not in str(exc)
            else:
                raise AssertionError("HTTP failure was not propagated")
            start = time.monotonic()
            try:
                fetch_text(base + "/slow", timeout=0.05)
            except TimeoutError:
                assert time.monotonic() - start < 0.35
            else:
                raise AssertionError("Timeout did not cancel the request")
            from geolichen.services.overpass_transport import download_overpass, _cooldown_until
            payload, error, endpoint = download_overpass('query', (base + '/overpass',), 3)
            assert payload == {'elements': []} and error is None, (error, Handler.last_post)
            payload, error, endpoint = download_overpass('query', (base + '/rate-limit',), 3)
            assert payload is None and '429' in error, error
            _cooldown_until.clear()
            print('PASS: real QGIS Overpass POST, application identification and HTTP 429 handling')
            started = time.monotonic()
            payload, error, _ = download_overpass('query', (base + '/slow-overpass',), 0.05)
            assert payload is None and 'Tempo limite' in error, error
            assert time.monotonic() - started < 2.8, 'Overpass total deadline was not enforced'
            print('PASS: stalled Overpass POST aborted at total deadline without caching a response')
            # A queued response arriving after the old total deadline must now
            # succeed when given an independent network-wait budget.
            payload, error, _ = download_overpass('query', (base + '/slow-overpass',),
                                                  0.05, wait_timeout_s=4)
            assert payload == {'elements': []} and error is None, error
            print('PASS: queued Overpass response accepted beyond the query-runtime margin')
            from geolichen.services.osm_trail_service import OsmTrailService
            from qgis.core import QgsGeometry, QgsPointXY
            buffer = QgsGeometry.fromPointXY(QgsPointXY(10.2, 46.05)).buffer(.001, 48)
            trails = OsmTrailService(endpoint=base + '/trails', query_margin_m=0)
            trails.endpoints = (base + '/trails',)
            result = trails.fetch(buffer)
            assert result.success and result.feature_count == 1, result.error
            geometry = next(result.layer.getFeatures()).geometry()
            assert geometry.difference(buffer).isEmpty()
            assert trails.fetch(buffer).from_cache
            print('PASS: actual local HTTP trail download, exact buffer clipping, layer creation and cached reuse')
        finally:
            server.shutdown()
            server.server_close()
        print("PASS: QGIS HTTP success, ITALIC JSON, HTTP errors and timeout")

        from geolichen.services.geocoding_service import GeocodingService
        service = GeocodingService()
        with patch("geolichen.services.osm_geocoding_service.fetch_text",
                   return_value='{"features": []}') as fetch:
            assert service._call("Edolo")["features"] == []
            assert "photon.komoot.io" in fetch.call_args.args[0]
            assert "key=" not in fetch.call_args.args[0]
        with patch("geolichen.services.osm_geocoding_service.fetch_text",
                   side_effect=OSError("HTTP 403 from remote service.")):
            result = service.geocode_ranked("Breno")
            assert not result.ok and "403" in result.error
        print("PASS: Photon/OSM request without API key and failure handling")

        from geolichen.services.release_readiness_service import ReleaseReadinessService
        report = ReleaseReadinessService(ROOT).run()
        metadata = configparser.ConfigParser(interpolation=None)
        metadata.read(ROOT / "metadata.txt", encoding="utf-8")
        assert report["metadata"]["version"] == metadata["general"]["version"]
        assert all(check["ok"] for check in report["checks"]
                   if check["name"].startswith("File richiesto:"))
        print(f"Release readiness: {report['blocking_failures']} outstanding checks (public URLs may be pending)")
        iface.window.close()
        app.processEvents()
        profile_path.stop()
        # QGIS/PyQt owns widgets until interpreter teardown; do not manually
        # exitQgis while Python wrappers for canvas/layers are still alive.


if __name__ == "__main__":
    main()
