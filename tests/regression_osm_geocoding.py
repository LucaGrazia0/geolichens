"""QGIS tests for OSM locality normalization, caching, limits and request failures."""
import copy
import importlib.util
import json
import os
import time
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('geolichen', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules['geolichen'] = package
spec.loader.exec_module(package)
from geolichen.services.osm_geocoding_service import PhotonGeocoder
from geolichen.services.geocoding_service import GeocodingService
from geolichen.services.osm_trail_service import OsmTrailService
from geolichen.services.osm_search_geometry_service import OsmSearchGeometryService
from geolichen.services.initial_boundary_service import InitialBoundaryService
from geolichen.services._shared_geo_utils import local_metric_crs
from geolichen.core.locality_parser import SemanticLocalityParser
from geolichen.services import overpass_transport
from qgis.core import (QgsApplication, QgsGeometry, QgsRectangle, QgsPointXY,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject)
from unittest.mock import MagicMock
from qgis.PyQt.QtNetwork import QNetworkReply

PAYLOAD = {'features': [{'type': 'Feature', 'geometry': {
    'type': 'Point', 'coordinates': [10.2, 46.05]}, 'properties': {
    'name': 'Passo di prova', 'city': 'Comune di prova', 'state': 'Lombardia',
    'country': 'Italia', 'countrycode': 'IT', 'osm_key': 'mountain_pass',
    'osm_value': 'yes', 'osm_type': 'N', 'osm_id': 123,
    'extent': [10.19, 46.06, 10.21, 46.04]}}]}
FETCH = 'geolichen.services.osm_geocoding_service.fetch_text'


class OsmGeocodingRegression(unittest.TestCase):
    def setUp(self):
        OsmTrailService._recent_failures.clear()
        self.addCleanup(OsmTrailService._recent_failures.clear)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = GeocodingService(cache_dir=self.temp.name)
        self.service.client.MIN_INTERVAL_S = 0

    def test_normalize_coordinates_extent_identity_and_source(self):
        f = PhotonGeocoder.normalize(PAYLOAD)['features'][0]
        self.assertEqual(f['center'], [10.2, 46.05])
        self.assertEqual(f['bbox'], [10.19, 46.04, 10.21, 46.06])
        self.assertEqual(f['id'], 'osm:N:123')
        self.assertEqual(f['provider'], 'Photon / OpenStreetMap')
        self.assertIn('Comune di prova', f['place_name'])
        self.assertIn('OpenStreetMap', f['attribution'])

    def test_no_key_and_strict_bbox_sent_to_photon(self):
        with patch(FETCH, return_value=json.dumps(PAYLOAD)) as fetch:
            result = self.service.geocode_ranked('Passo di prova')
        self.assertTrue(result.ok)
        params = parse_qs(urlsplit(fetch.call_args.args[0]).query)
        self.assertNotIn('key', params)
        self.assertEqual(params['bbox'], ['8.45,44.7,11.45,46.7'])
        self.assertNotIn('lang', params)  # Public Photon rejects lang=it.

    def test_cache_persists_and_returned_candidates_cannot_mutate_it(self):
        with patch(FETCH, return_value=json.dumps(PAYLOAD)) as fetch:
            first = self.service.geocode_ranked('Passo di prova')
            first.feature['center'][0] = 99
            other = GeocodingService(cache_dir=self.temp.name)
            again = other.geocode_ranked('Passo di prova')
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(again.center, [10.2, 46.05])
        self.assertTrue(other.client.last_from_cache)

    def test_cache_key_includes_endpoint_and_search_area(self):
        with patch(FETCH, return_value=json.dumps(PAYLOAD)) as fetch:
            self.service._call('Passo di prova')
            self.service.set_bbox((9, 45, 11, 47))
            self.service._call('Passo di prova')
            self.service.set_endpoint('http://localhost:2322/api/')
            self.service._call('Passo di prova')
        self.assertEqual(fetch.call_count, 3)

    def test_disable_area_and_reject_invalid_coordinates(self):
        self.service.set_bbox(None)
        with patch(FETCH, return_value=json.dumps(PAYLOAD)) as fetch:
            self.assertTrue(self.service.geocode_ranked('Passo di prova').ok)
        self.assertNotIn('bbox', parse_qs(urlsplit(fetch.call_args.args[0]).query))
        bad = copy.deepcopy(PAYLOAD)
        bad['features'][0]['geometry']['coordinates'] = [float('nan'), 46]
        self.assertEqual(PhotonGeocoder.normalize(bad)['features'], [])
        self.assertEqual(PhotonGeocoder.normalize(PAYLOAD, (0, 0, 1, 1))['features'], [])

    def test_optional_area_expansion_only_after_empty_local_response(self):
        self.service.auto_expand = True
        with patch(FETCH, side_effect=['{"features":[]}', json.dumps(PAYLOAD)]) as fetch:
            result = self.service.geocode_ranked('Passo di prova')
        self.assertTrue(result.ok)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('bbox', parse_qs(urlsplit(fetch.call_args_list[0].args[0]).query))
        self.assertNotIn('bbox', parse_qs(urlsplit(fetch.call_args_list[1].args[0]).query))
        self.assertTrue(result.feature['_geolichen_area_expanded'])

    def test_corrupt_and_empty_responses(self):
        for response in ('{not json', '{"error":"server error"}'):
            with patch(FETCH, return_value=response):
                self.assertFalse(self.service.geocode_ranked('Bad response').ok)
        with patch(FETCH, return_value='{"features":[]}'):
            self.assertFalse(self.service.geocode_ranked('Unknown name').ok)

    def test_network_error_stops_variant_storm_and_preserves_manual_fallback(self):
        with patch(FETCH, side_effect=TimeoutError('Network request timed out.')) as fetch:
            result = self.service.geocode_prefer_municipality('Comune di prova', 'Passo di prova')
        self.assertFalse(result.ok)
        self.assertIn('timed out', result.error)
        self.assertEqual(fetch.call_count, 1)

    def test_rate_limit_and_request_budget(self):
        self.service.client.MIN_INTERVAL_S = 1.1
        with patch(FETCH, return_value='{"features":[]}'), \
             patch('geolichen.services.osm_geocoding_service.time.monotonic', return_value=100), \
             patch('geolichen.services.osm_geocoding_service.time.sleep') as sleep:
            PhotonGeocoder._last_request = 100
            self.service._call('First query')
            sleep.assert_called_once()
        self.service.client.MIN_INTERVAL_S = 0
        self.service.client.network_requests = 0
        self.service.client.max_requests = 2
        with patch(FETCH, return_value='{"features":[]}') as fetch:
            result = self.service.geocode_prefer_municipality('Missing town', 'Missing locality')
        self.assertFalse(result.ok)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('Limite', result.error)

    def test_slow_photon_has_larger_request_wait_but_shared_action_deadline(self):
        self.assertEqual(self.service.timeout, 35)
        self.service.client.begin_search()
        with patch(FETCH, return_value=json.dumps(PAYLOAD)) as fetch:
            self.assertTrue(self.service.geocode_ranked('Passo di prova').ok)
        self.assertGreater(fetch.call_args.kwargs['timeout'], 12)
        self.assertLessEqual(fetch.call_args.kwargs['timeout'], 35)
        self.service.client._deadline = 99
        with patch(FETCH) as fetch, patch('geolichen.services.osm_geocoding_service.time.monotonic', return_value=100):
            with self.assertRaises(TimeoutError):self.service.client.search('Uncached query')
        fetch.assert_not_called()

    def test_failed_town_request_does_not_hide_cached_locality(self):
        with patch(FETCH, return_value=json.dumps(PAYLOAD)):
            self.service.client.search('Passo di prova', self.service.bbox)
        with patch(FETCH, side_effect=TimeoutError('timed out')) as fetch:
            result = self.service.geocode_prefer_municipality('Missing town', 'Passo di prova')
        self.assertTrue(result.ok)
        self.assertEqual(result.feature['text'], 'Passo di prova')
        self.assertIn('cache locale', result.feature['_geolichen_score_reason'])
        self.assertIn('online Photon non disponibile', result.error)
        self.assertEqual(fetch.call_count, 1)

    def test_deeper_search_can_use_cached_variants_after_network_error(self):
        with patch(FETCH, return_value=json.dumps(PAYLOAD)):
            self.service.client.search('Passo prova', self.service.bbox)
        with patch(FETCH, side_effect=TimeoutError('timed out')) as fetch:
            result = self.service.search_more('Passo di prova', 'Missing town')
        self.assertTrue(result.ok)
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(result.feature['_geolichen_cached_response'])

    def test_cache_only_recovery_keeps_endpoint_bbox_and_ttl_isolation(self):
        with patch(FETCH, return_value=json.dumps(PAYLOAD)) as initial:
            self.service.client.search('Passo di prova', self.service.bbox)
        cached_path = self.service.client._cache_path(initial.call_args.args[0])
        self.service._lookup_error = 'offline'
        self.service.set_bbox((9,45,11,47))
        with patch(FETCH) as fetch:
            self.assertFalse(self.service.geocode_ranked('Passo di prova').ok)
        fetch.assert_not_called()

        self.service.set_bbox(self.service.DEFAULT_BBOX)
        self.service.set_endpoint('http://localhost:2322/api/')
        with patch(FETCH) as fetch:
            self.assertFalse(self.service.geocode_ranked('Passo di prova').ok)
        fetch.assert_not_called()
        self.service.set_endpoint(PhotonGeocoder.DEFAULT_ENDPOINT)
        cached = json.loads(cached_path.read_text())
        cached['created'] = 0
        cached_path.write_text(json.dumps(cached))
        with patch(FETCH) as fetch:
            self.assertFalse(self.service.geocode_ranked('Passo di prova').ok)
        fetch.assert_not_called()

    def test_expired_search_budget_still_allows_fresh_cached_response(self):
        with patch(FETCH, return_value=json.dumps(PAYLOAD)):
            self.service.client.search('Passo di prova', self.service.bbox)
        self.service.client._deadline = 0
        with patch(FETCH) as fetch:
            result = self.service.client.search('Passo di prova', self.service.bbox)
        self.assertEqual(len(result['features']), 1)
        fetch.assert_not_called()

    def test_configurable_photon_only_endpoint(self):
        for endpoint in ('', 'ftp://example.org/api/', 'https://nominatim.openstreetmap.org/search',
                         'https://api.maptiler.com/geocoding', 'https://example.org/api/?key=secret'):
            with self.assertRaises(ValueError):
                PhotonGeocoder.validate_endpoint(endpoint)
        self.service.set_endpoint('http://localhost:2322/api/')
        self.assertEqual(self.service.client.endpoint, 'http://localhost:2322/api/')

    def test_trails_remain_actual_osm_ways_not_basemap_tiles(self):
        query = OsmTrailService().build_query((45.9, 10.3, 46.0, 10.5))
        self.assertIn('way["highway"="path"]', query)
        self.assertIn('out tags geom;', query)
        self.assertNotIn('maptiler', query.lower())

    def test_pass_search_does_not_choose_a_road_named_after_the_pass(self):
        payload = copy.deepcopy(PAYLOAD)
        road = copy.deepcopy(payload['features'][0])
        road['properties'].update(osm_key='highway', osm_value='primary', osm_id=456)
        payload['features'].insert(0, road)
        with patch(FETCH, return_value=json.dumps(payload)):
            result = self.service.geocode_ranked('Passo di prova')
        self.assertEqual(result.feature['osm_id'], 123)
        self.assertEqual(len(result.candidates), 1)

    @staticmethod
    def blocking_reply(status=200, payload=None):
        blocking = MagicMock()
        blocking.post.return_value = 0
        blocking.reply.return_value.attribute.return_value = status
        blocking.reply.return_value.error.return_value = QNetworkReply.NetworkError.NoError
        blocking.reply.return_value.content.return_value = json.dumps(
            payload if payload is not None else {'elements': []}).encode()
        return blocking

    def test_overpass_post_identification_and_json_contract(self):
        blocking = self.blocking_reply()
        with patch.object(overpass_transport, 'QgsBlockingNetworkRequest', return_value=blocking):
            payload, error, endpoint = OsmTrailService()._download('[out:json];out;')
        self.assertIsNone(error)
        self.assertEqual(payload, {'elements': []})
        request, body = blocking.post.call_args.args
        self.assertIn(b'GeoLichen', bytes(request.rawHeader(b'User-Agent')))
        self.assertIn(b'data=', bytes(body))
        self.assertIn('overpass', endpoint)

    def test_trail_network_wait_allows_queue_without_raising_server_query_budget(self):
        service = OsmTrailService()
        query = service.build_query((46.198, 10.473, 46.202, 10.476))
        self.assertIn('[timeout:25]', query)
        blocking = self.blocking_reply()
        with patch.object(overpass_transport, 'QgsBlockingNetworkRequest', return_value=blocking), \
             patch.object(overpass_transport, 'Timer') as timer:
            payload, error, _ = service._download(query)
        self.assertIsNone(error)
        self.assertEqual(payload, {'elements': []})
        self.assertEqual(timer.call_args.args[0], 60)
        request = blocking.post.call_args.args[0]
        self.assertEqual(request.transferTimeout(), 61_000)
        # Short locality lookups retain the earlier bounded budget.
        with patch.object(overpass_transport, 'QgsBlockingNetworkRequest', return_value=blocking), \
             patch.object(overpass_transport, 'Timer') as timer:
            OsmSearchGeometryService()._download('query')
        self.assertEqual(timer.call_args.args[0], 7)

    def test_explicit_network_wait_is_reported_on_cancellation(self):
        blocking = self.blocking_reply()
        blocking.post.side_effect = lambda *a, **kw: kw['feedback'].cancel()
        with patch.object(overpass_transport, 'QgsBlockingNetworkRequest', return_value=blocking), \
             patch.object(overpass_transport, 'Timer') as timer:
            payload, error, _ = overpass_transport.download_overpass(
                'query', ('http://localhost/slow',), 25, wait_timeout_s=60)
        self.assertIsNone(payload)
        self.assertIn('(60 s)', error)
        timer.return_value.cancel.assert_called_once()

    def test_laghetto_and_laghetti_are_lakes(self):
        parser = SemanticLocalityParser()
        for name in ("Laghetto d’Avio", "Laghetto d'Avio", 'Laghetti di prova', 'Lago di prova'):
            with self.subTest(name=name):
                self.assertEqual(parser.parse(name).feature_type, 'lake')

    def test_lake_search_is_circle_on_selected_point_even_with_bbox_or_osm_polygon(self):
        service = InitialBoundaryService()
        feature = {'text': "Laghetto d'Avio", 'center': [10.474471, 46.1997007],
                   'bbox': [10.473444, 46.1980992, 10.4756785, 46.201472]}
        original = copy.deepcopy(feature)
        with patch.object(service.osm_search_geometry_service, 'resolve') as lookup:
            extents = service.build_extents(feature, ref_type='hydro')
        lookup.assert_not_called()
        self.assertEqual(feature, original)
        resolved = extents['resolved_locality']
        # Preserve the independently resolved documentary rectangle.
        self.assertTrue(extents['documented_extent'].equals(service._bbox_geometry(feature)))
        search = QgsGeometry(extents['search_extent'])
        center = QgsGeometry.fromPointXY(QgsPointXY(*feature['center']))
        wgs = QgsCoordinateReferenceSystem('EPSG:4326')
        metric = local_metric_crs(center.asPoint())
        transform = QgsCoordinateTransform(wgs, metric, QgsProject.instance())
        search.transform(transform)
        center.transform(transform)
        self.assertLess(search.centroid().distance(center), 0.001)
        for vertex in search.vertices():
            self.assertAlmostEqual(QgsGeometry.fromPointXY(QgsPointXY(vertex)).distance(center), 300, places=3)
        self.assertFalse(resolved.provenance['osm_search_geometry_used'])
        self.assertEqual(resolved.search_geometry.metadata['resolution_order'], 'circular_locality_policy')

    def test_lake_without_bbox_uses_same_circle_policy(self):
        service = InitialBoundaryService()
        feature = {'text': 'Lago di prova', 'center': [10.474471, 46.1997007]}
        with patch.object(service.osm_search_geometry_service, 'resolve') as lookup:
            extents = service.build_extents(feature, ref_type='hydro')
        lookup.assert_not_called()
        self.assertIn('point_buffer', extents['search_extent_strategy'])
        self.assertTrue(extents['search_extent'].isGeosValid())

    def test_all_locality_types_use_semantic_circles_and_preserve_documentary_extent(self):
        service = InitialBoundaryService()
        for name, ref_type, radius in (
                ('Bosco di prova', 'forest_area', 1000), ('Valle di prova', 'valley', 1500),
                ('Passo di prova', 'pass', 250), ('Cima di prova', 'summit_peak', 150),
                ('Monte di prova', 'mountain_area', 1000), ('Torrente di prova', 'hydro', 300),
                ('Comune di prova', 'municipality', 2000), ('Rifugio di prova', 'refuge_malga', 150),
                ('Sentiero di prova', 'trail', 150), ('Luogo di prova', 'locality', 500)):
            with self.subTest(name=name):
                feature = {'text': name, 'center': [10.475, 46.195],
                           'bbox': [10.47, 46.19, 10.48, 46.20]}
                with patch.object(service.osm_search_geometry_service, 'resolve') as lookup:
                    extents = service.build_extents(feature, ref_type=ref_type)
                lookup.assert_not_called()
                search = QgsGeometry(extents['search_extent'])
                center = QgsGeometry.fromPointXY(QgsPointXY(*feature['center']))
                transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'),
                                                   local_metric_crs(center.asPoint()), QgsProject.instance())
                search.transform(transform); center.transform(transform)
                self.assertLess(search.centroid().distance(center), .001)
                for vertex in search.vertices():
                    self.assertAlmostEqual(QgsGeometry.fromPointXY(QgsPointXY(vertex)).distance(center), radius, places=3)
                self.assertEqual(extents['resolved_locality'].search_geometry.metadata['resolution_order'],
                                 'circular_locality_policy')
                if ref_type == 'municipality':
                    self.assertTrue(extents['documented_extent'].equals(service._bbox_geometry(feature)))
                    diagnostic = extents['resolved_locality'].provenance['administrative_geometry_diagnostics']
                    self.assertFalse(diagnostic['osm_lookup_attempted'])

    def test_underlying_reply_timeout_cannot_be_mistaken_for_empty_success(self):
        blocking = self.blocking_reply()
        blocking.reply.return_value.error.return_value = QNetworkReply.NetworkError.TimeoutError
        with patch.object(overpass_transport, 'QgsBlockingNetworkRequest', return_value=blocking):
            payload, error, _ = overpass_transport.download_overpass('query', ('http://localhost/slow',), 25,
                                                                     wait_timeout_s=60)
        self.assertIsNone(payload)
        self.assertIn('Tempo limite', error)

    def test_overpass_refusal_stops_fallback_and_shares_cooldown(self):
        overpass_transport._cooldown_until.clear()
        self.addCleanup(overpass_transport._cooldown_until.clear)
        blocking = self.blocking_reply(status=429)
        with patch.object(overpass_transport, 'QgsBlockingNetworkRequest', return_value=blocking):
            first = OsmTrailService()._download('query')
            second = OsmSearchGeometryService()._download('query')
        self.assertIsNone(first[0])
        self.assertIn('429', first[1])
        self.assertIn('sospeso', second[1])
        self.assertEqual(blocking.post.call_count, 1)

    def test_overpass_partial_timeout_response_is_not_a_success(self):
        blocking = self.blocking_reply(payload={'elements': [], 'remark': 'runtime error: Query timed out'})
        with patch.object(overpass_transport, 'QgsBlockingNetworkRequest', return_value=blocking):
            payload, error, endpoint = OsmTrailService()._download('query')
        self.assertIsNone(payload)
        self.assertIn('Query timed out', error)

    def test_overpass_busy_status_is_reported_and_uses_existing_fallback(self):
        busy, available = self.blocking_reply(status=502), self.blocking_reply()
        with patch.object(overpass_transport, 'QgsBlockingNetworkRequest', side_effect=[busy, available]):
            payload, error, endpoint = OsmTrailService()._download('query')
        self.assertEqual(payload, {'elements': []})
        self.assertIsNone(error)
        self.assertIn('private.coffee', endpoint)
        with patch.object(overpass_transport, 'QgsBlockingNetworkRequest', return_value=busy):
            payload, error, _ = overpass_transport.download_overpass('query', ('http://localhost/busy',), 5)
        self.assertIsNone(payload)
        self.assertIn('502', error)
        self.assertIn('server occupato', error)

    def test_overpass_deadline_cancellation_is_reported_and_timer_is_cleaned(self):
        blocking = self.blocking_reply()
        def canceled(*args, **kwargs):
            kwargs['feedback'].cancel()
            return 0
        blocking.post.side_effect = canceled
        with patch.object(overpass_transport, 'QgsBlockingNetworkRequest', return_value=blocking), \
             patch.object(overpass_transport, 'Timer') as timer:
            payload, error, _ = overpass_transport.download_overpass('query', ('http://localhost/slow',), 5)
        self.assertIsNone(payload)
        self.assertIn('Tempo limite', error)
        timer.return_value.start.assert_called_once()
        timer.return_value.cancel.assert_called_once()

    def test_valid_trails_cache_kept_but_partial_cache_ignored(self):
        service = OsmTrailService()
        path = Path(self.temp.name) / 'response.json'
        for value in ({'elements': [], 'remark': 'runtime error'}, {'error': 'bad response'}, []):
            path.write_text(json.dumps(value))
            self.assertIsNone(service._read_cache(str(path)))
        path.write_text('{"elements":[]}')
        self.assertEqual(service._read_cache(str(path)), {'elements': []})

    def test_trail_legend_and_summary_distinguish_paths_tracks_and_roads(self):
        payload = self.trail_payload([
            [(10.199, 46.05), (10.201, 46.05)],
            [(10.199, 46.0501), (10.201, 46.0501)],
            [(10.199, 46.0502), (10.201, 46.0502)]])
        payload['elements'][1]['tags']['highway'] = 'track'
        payload['elements'][2]['tags']['highway'] = 'service'
        layer, count, _ = OsmTrailService()._parse_to_layer(payload)
        self.assertEqual(count, 3)
        renderer = layer.renderer()
        self.assertEqual(renderer.type(), 'categorizedSymbol')
        self.assertEqual(renderer.classAttribute(), 'highway')
        self.assertEqual({cat.value() for cat in renderer.categories()}, {'path', 'track', 'service'})
        self.assertEqual(len({cat.symbol().color().name() for cat in renderer.categories()}), 3)
        summary = OsmTrailService.layer_summary(layer)
        self.assertIn('pedonali/equestri: 1', summary)
        self.assertIn('piste: 1', summary)
        self.assertIn('strade di accesso: 1', summary)

    def test_access_roads_alone_do_not_claim_pedestrian_paths(self):
        payload = self.trail_payload([[(10.199, 46.05), (10.201, 46.05)]])
        payload['elements'][0]['tags']['highway'] = 'service'
        layer, _, _ = OsmTrailService()._parse_to_layer(payload)
        summary = OsmTrailService.layer_summary(layer)
        self.assertIn('pedonali/equestri: 0', summary)
        self.assertIn('Nessun sentiero pedonale', summary)

    def test_expired_identical_trail_cache_recovers_after_502_without_refreshing_age(self):
        geometry = QgsGeometry.fromRect(QgsRectangle(10.199, 46.049, 10.202, 46.052))
        service = OsmTrailService(query_margin_m=0)
        payload = self.trail_payload([[(10.198, 46.05), (10.203, 46.05)]])
        path = Path(self.temp.name) / 'archive.json'
        path.write_text(json.dumps(payload))
        old_time = time.time() - 2 * 86400
        os.utime(path, (old_time, old_time))
        original = path.read_bytes()
        with patch.object(service, '_cache_path', return_value=str(path)), \
             patch.object(service, '_download', return_value=(None, 'Overpass HTTP 502: server occupato', service.endpoint)) as download:
            first = service.fetch(geometry)
            second = service.fetch(geometry)
        self.assertTrue(first.success, first.error)
        self.assertTrue(first.from_cache)
        self.assertIn('2.0 giorni', first.warning)
        self.assertIn('502', first.warning)
        self.assertTrue(second.success)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(path.stat().st_mtime, old_time)
        self.assertTrue(first.layer.customProperty('geolichen/osm_archive_fallback'))
        feature = next(first.layer.getFeatures())
        self.assertLessEqual(feature.geometry().difference(geometry).length(), 1e-10)

    def test_partial_too_old_and_disabled_archives_are_not_recovered(self):
        service = OsmTrailService()
        path = Path(self.temp.name) / 'old.json'
        cases = [({'elements': [], 'remark': 'partial'}, 2), ({'elements': []}, 31)]
        for payload, days in cases:
            path.write_text(json.dumps(payload))
            stamp = time.time() - days * 86400
            os.utime(path, (stamp, stamp))
            self.assertIsNone(service._read_cache(str(path), allow_expired=True))
        path.write_text('{"elements":[]}')
        service.cache_ttl_hours = 0
        self.assertIsNone(service._read_cache(str(path), allow_expired=True))

    def test_failed_query_cooldown_expires_and_does_not_block_other_areas(self):
        service = OsmTrailService(query_margin_m=0)
        geometry = QgsGeometry.fromRect(QgsRectangle(10.199, 46.049, 10.202, 46.052))
        other = QgsGeometry.fromRect(QgsRectangle(10.299, 46.049, 10.302, 46.052))
        with patch.object(QgsApplication, 'qgisSettingsDirPath', return_value=self.temp.name), \
             patch.object(service, '_download', return_value=(None, 'Overpass HTTP 502', service.endpoint)) as download:
            with patch('geolichen.services.osm_trail_service.time.monotonic', return_value=100):
                self.assertFalse(service.fetch(geometry).success)
                repeated = service.fetch(geometry)
                self.assertIn('tra 60 s', repeated.error)
                self.assertEqual(download.call_count, 1)
                self.assertFalse(service.fetch(other).success)
                self.assertEqual(download.call_count, 2)
            with patch('geolichen.services.osm_trail_service.time.monotonic', return_value=161):
                self.assertFalse(service.fetch(geometry).success)
                self.assertEqual(download.call_count, 3)

    def test_fresh_cache_wins_over_previous_failure_cooldown(self):
        service = OsmTrailService(query_margin_m=0)
        geometry = QgsGeometry.fromRect(QgsRectangle(10.199, 46.049, 10.202, 46.052))
        path = Path(self.temp.name) / 'new.json'
        payload = self.trail_payload([[(10.2, 46.05), (10.201, 46.05)]])
        with patch.object(service, '_cache_path', return_value=str(path)), \
             patch.object(service, '_download', return_value=(None, 'HTTP 502', service.endpoint)) as download:
            self.assertFalse(service.fetch(geometry).success)
            path.write_text(json.dumps(payload))
            result = service.fetch(geometry)
        self.assertTrue(result.success)
        self.assertTrue(result.from_cache)
        self.assertNotIn('non aggiornato', result.warning or '')
        self.assertEqual(download.call_count, 1)

    def test_trails_fetch_builds_real_line_attributes_and_reuses_cache(self):
        payload = {'elements': [{'type': 'way', 'id': 12345, 'tags': {
            'highway': 'path', 'name': 'Synthetic test trail', 'sac_scale': 'hiking'},
            'geometry': [{'lon': 10.2, 'lat': 46.05}, {'lon': 10.201, 'lat': 46.051}]}]}
        geometry = QgsGeometry.fromRect(QgsRectangle(10.199, 46.049, 10.202, 46.052))
        service = OsmTrailService(query_margin_m=0)
        with patch.object(QgsApplication, 'qgisSettingsDirPath', return_value=self.temp.name), \
             patch.object(service, '_download', return_value=(payload, None, service.endpoint)) as download:
            result = service.fetch(geometry)
            cached = service.fetch(geometry)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.feature_count, 1)
        feature = next(result.layer.getFeatures())
        self.assertEqual(feature['osm_id'], 12345)
        self.assertEqual(feature['sac_scale'], 'hiking')
        self.assertGreater(feature.geometry().length(), 0)
        self.assertTrue(cached.from_cache)
        self.assertEqual(download.call_count, 1)

    def test_locality_resolver_preserves_osm_polygon_geometry_and_cache(self):
        payload = {'elements': [{'type': 'way', 'id': 6789, 'tags': {
            'natural': 'water', 'name': 'Lago di prova'}, 'geometry': [
                {'lon': 10.199, 'lat': 46.049}, {'lon': 10.201, 'lat': 46.049},
                {'lon': 10.201, 'lat': 46.051}, {'lon': 10.199, 'lat': 46.051},
                {'lon': 10.199, 'lat': 46.049}]}]}
        anchor = QgsGeometry.fromPointXY(QgsPointXY(10.2, 46.05))
        service = OsmSearchGeometryService()
        with patch.object(QgsApplication, 'qgisSettingsDirPath', return_value=self.temp.name), \
             patch.object(service, '_download', return_value=(payload, None, service.endpoint)) as download:
            result = service.resolve('Lago di prova', 'lake', anchor)
            cached = service.resolve('Lago di prova', 'lake', anchor)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.osm_id, 6789)
        self.assertEqual(result.geometry_type.upper(), 'POLYGON')
        self.assertTrue(result.geometry.contains(anchor))
        self.assertTrue(cached.from_cache)
        self.assertEqual(download.call_count, 1)

    @staticmethod
    def trail_payload(lines):
        return {'elements': [{'type': 'way', 'id': index + 1,
                'tags': {'highway': 'path', 'name': f'Test trail {index}'},
                'geometry': [{'lon': x, 'lat': y} for x, y in coords]}
                for index, coords in enumerate(lines)]}

    def test_trails_are_clipped_to_circle_not_its_bounding_rectangle(self):
        buffer = QgsGeometry.fromPointXY(QgsPointXY(10.2, 46.05)).buffer(.001, 48)
        payload = self.trail_payload([
            [(10.198, 46.05), (10.202, 46.05)],
            [(10.2009, 46.0509), (10.20095, 46.05095)],
            [(10.21, 46.06), (10.22, 46.07)]])
        layer, count, warning = OsmTrailService()._parse_to_layer(payload, buffer)
        self.assertEqual(count, 1)
        trail = next(layer.getFeatures())
        self.assertEqual(trail['osm_id'], 1)
        self.assertAlmostEqual(trail.geometry().length(), .002, places=7)
        self.assertTrue(trail.geometry().difference(buffer).isEmpty())

    def test_clip_respects_holes_and_keeps_osm_identity_on_split_segments(self):
        buffer = QgsGeometry.fromWkt('POLYGON ((10.199 46.049,10.201 46.049,10.201 46.051,10.199 46.051,10.199 46.049),'
            '(10.1995 46.0495,10.2005 46.0495,10.2005 46.0505,10.1995 46.0505,10.1995 46.0495))')
        payload = self.trail_payload([[(10.198, 46.05), (10.202, 46.05)]])
        layer, count, warning = OsmTrailService()._parse_to_layer(payload, buffer)
        self.assertEqual(count, 2)
        self.assertEqual({f['osm_id'] for f in layer.getFeatures()}, {1})
        self.assertAlmostEqual(sum(f.geometry().length() for f in layer.getFeatures()), .001, places=7)

    def test_cached_response_is_reclipped_for_different_buffer_shape(self):
        polygon = QgsGeometry.fromRect(QgsRectangle(10.199, 46.049, 10.201, 46.051))
        circle = QgsGeometry.fromPointXY(QgsPointXY(10.2, 46.05)).buffer(.001, 48)
        payload = self.trail_payload([[(10.2009, 46.0509), (10.20095, 46.05095)]])
        service = OsmTrailService(query_margin_m=0)
        with patch.object(service, '_cache_path', return_value=str(Path(self.temp.name) / 'shared.json')), \
             patch.object(service, '_download', return_value=(payload, None, service.endpoint)) as download:
            first = service.fetch(polygon)
            second = service.fetch(circle)
        self.assertTrue(first.success, first.error)
        self.assertEqual(first.feature_count, 1)
        self.assertTrue(second.from_cache)
        self.assertEqual(second.feature_count, 0)
        self.assertEqual(download.call_count, 1)

    def test_corrupt_way_is_not_joined_across_missing_or_nonfinite_coordinates(self):
        payload = self.trail_payload([[(10.199, 46.05), (float('nan'), 46.05), (10.201, 46.05)]])
        layer, count, warning = OsmTrailService()._parse_to_layer(payload)
        self.assertEqual(count, 0)
        self.assertIn('1 way', warning)


if __name__ == '__main__':
    app = QgsApplication([], False)
    app.initQgis()
    unittest.main(verbosity=2)
