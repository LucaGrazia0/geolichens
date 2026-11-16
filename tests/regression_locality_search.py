"""Local synthetic tests for deeper lookup, municipal evidence and saved anchors."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer)
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('geolichen', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules['geolichen'] = package; spec.loader.exec_module(package)
from geolichen.services.geocoding_service import GeocodingService, GeocodingResult
from geolichen.services.osm_geocoding_service import PhotonGeocoder
from geolichen.services.confirmed_localities_service import ConfirmedLocalitiesService
from geolichen.services.municipality_boundary_service import MunicipalityBoundaryService
from geolichen.core.locality_names import name_variants, plausible_name, search_variants, name_evidence
from geolichen.core.locality_parser import SemanticLocalityParser
from geolichen.core.qgis_compat import FieldType
from geolichen.gui.candidate_selector_dialog import CandidateSelectorDialog
from geolichen.gui.confirmed_localities_dialog import ConfirmedLocalitiesDialog

FETCH = 'geolichen.services.osm_geocoding_service.fetch_text'


def payload(name='Monte di prova', identifier=100, lon=10.2, lat=46.05, key='natural', value='peak'):
    return {'features': [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
                         'properties': {'name': name, 'osm_id': identifier, 'osm_type': 'N',
                                        'osm_key': key, 'osm_value': value, 'country': 'Italy'}}]}


def feature(**kwargs):
    return PhotonGeocoder.normalize(payload(**kwargs))['features'][0]


class LocalitySearch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.service = GeocodingService(cache_dir=self.temp.name)
        self.service.client.MIN_INTERVAL_S = 0

    def test_variants_are_conservative_and_preserve_original(self):
        for old, expanded in [('M.te Blèis', 'Monte Blèis'), ('Rif. Test', 'Rifugio Test'),
                              ('P.so Test', 'Passo Test'), ('L.to d’Avio', "Laghetto d'Avio")]:
            values = name_variants(old)
            self.assertIn(expanded, values)
        self.assertEqual(name_variants('S. Maria'), ['S. Maria'])
        self.assertEqual(name_variants('Monte Bello'), ['Monte Bello'])

    def test_abbreviations_also_preserve_semantic_type_and_original_record_text(self):
        from geolichen.services.initial_boundary_service import InitialBoundaryService
        original = 'M.te di prova'
        interpreted = SemanticLocalityParser().parse(original)
        self.assertEqual(interpreted.feature_type, 'mountain')
        self.assertEqual(interpreted.original_text, original)
        extents = InitialBoundaryService().build_extents({'text': original, 'center': [10.2,46.05]})
        self.assertIn('mountain_point_buffer_1000m', extents['search_extent_strategy'])

    def test_deeper_search_keeps_searching_after_first_success_and_deduplicates_ids(self):
        def response(url, **kwargs):
            q = parse_qs(urlsplit(url).query)['q'][0]
            identifier = 101 if 'Italia' in q else 100
            return json.dumps(payload(identifier=identifier))
        with patch(FETCH, side_effect=response) as fetch:
            result = self.service.search_more('M.te di prova')
        self.assertTrue(result.ok)
        self.assertGreater(fetch.call_count, 1)
        self.assertEqual(len(result.candidates), 2)
        self.assertTrue(any(len(f['_geolichen_queries']) > 1 for f in result.candidates))
        self.assertLessEqual(fetch.call_count, 6)

    def test_deeper_search_respects_global_request_budget_including_municipality(self):
        self.service.client.max_requests = 2
        with patch(FETCH, return_value=json.dumps(payload())) as fetch:
            result = self.service.search_more('M.te di prova', 'Comune di prova')
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(result.ok)
        self.assertIn('limite', result.error.lower())

    def test_network_failure_keeps_previous_candidates_and_stops_requests(self):
        previous = feature()
        with patch(FETCH, side_effect=TimeoutError('timed out')) as fetch:
            result = self.service.search_more('Monte di prova', previous_candidates=[previous])
        self.assertTrue(result.ok)
        self.assertIn(previous, result.candidates)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('timed out', result.error)

    def test_moved_osm_anchor_does_not_silently_replace_confirmed_position(self):
        saved = feature(); saved['_geolichen_confirmed_locality'] = True
        refreshed = feature(lon=10.21)
        candidates = self.service._dedupe_features([saved, refreshed, copy.deepcopy(refreshed)])
        self.assertEqual(len(candidates), 2)
        self.assertEqual({tuple(f['center']) for f in candidates}, {(10.2,46.05), (10.21,46.05)})

    def test_archive_is_offline_scoped_and_contains_no_ecological_outputs(self):
        selected = feature()
        selected.update(rank=1, GSS=99, model_r_m=10, _geolichen_score=444)
        self.service.archive.remember('Nome storico', 'Comune di prova', selected, ['M.te antico'])
        new_service = GeocodingService(cache_dir=self.temp.name)
        with patch(FETCH) as fetch:
            result = new_service.geocode_prefer_municipality('Comune di prova', 'Nome storico')
        fetch.assert_not_called()
        self.assertTrue(result.ok)
        self.assertEqual(result.center, selected['center'])
        self.assertTrue(result.feature['_geolichen_confirmed_locality'])
        raw = json.loads(self.service.archive.path.read_text())
        self.assertNotIn('GSS', raw['entries'][0]['feature'])
        self.assertNotIn('rank', raw['entries'][0]['feature'])
        self.assertEqual(self.service.archive.lookup('Nome storico', 'Altro comune'), [])
        self.assertEqual(self.service.archive.lookup('Nome storico', 'Comune di prova', (0, 0, 1, 1)), [])
        self.assertEqual(len(self.service.archive.lookup('M.te antico', 'Comune di prova')), 1)

    def test_archive_updates_removes_and_preserves_aliases(self):
        archive = self.service.archive
        archive.remember('Storico', 'Comune', feature(), ['Antico'])
        archive.remember('Storico', 'Comune', feature(lon=10.21), ['Alternativo'])
        self.assertEqual(len(archive.entries()), 1)
        self.assertEqual(archive.lookup('Antico', 'Comune')[0]['center'][0], 10.21)
        archive.remove('Storico', 'Comune')
        self.assertEqual(archive.entries(), [])

    def test_corrupt_archive_never_overwritten_and_invalid_coordinates_not_loaded(self):
        path = self.service.archive.path
        path.write_text('{broken')
        self.assertEqual(self.service.archive.entries(), [])
        with self.assertRaises(ValueError):
            self.service.archive.remember('Test', 'Comune', feature())
        self.assertEqual(path.read_text(), '{broken')
        path.write_text(json.dumps({'version': 1, 'entries': [{'aliases': ['Test'], 'feature': {'center': [999, 46]}}]}))
        self.assertEqual(self.service.archive.entries(), [])

    def test_archive_disable_forces_online_lookup_and_retains_saved_file(self):
        self.service.archive.remember('Monte di prova', '', feature())
        self.service.use_archive = False
        with patch(FETCH, return_value=json.dumps(payload())) as fetch:
            result = self.service.geocode_prefer_municipality('', 'Monte di prova')
        self.assertTrue(result.ok)
        self.assertTrue(fetch.called)
        self.assertEqual(len(self.service.archive.entries()), 1)

    def test_osm_type_disambiguates_same_name(self):
        data = payload('Laghetto di prova', key='natural', value='water')
        road = copy.deepcopy(data['features'][0]); road['properties'].update(osm_id=200, osm_key='highway', osm_value='service')
        data['features'].insert(0, road)
        with patch(FETCH, return_value=json.dumps(data)):
            result = self.service.geocode_ranked('Laghetto di prova')
        self.assertEqual(len(result.candidates), 1)
        self.assertIn('tipo OSM coerente', result.feature['_geolichen_score_reason'])

    def test_deeper_search_filters_unrelated_fuzzy_hits_but_keeps_typo_and_alias_candidates(self):
        for name in ('Monte Pornina', 'Corno Pornina', 'Baite Pornina', 'Monte Porrina'):
            self.assertTrue(plausible_name('M.te Pornina', name))
        for name in ('Palazzo Te', 'Vigneto Basso Scraleca', 'Viona (nucleo)'):
            self.assertFalse(plausible_name('M.te Pornina', name))
        data = payload(name='Monte Pornina')
        data['features'] += payload(name='Palazzo Te', identifier=2, key='tourism', value='museum')['features']
        with patch(FETCH, return_value=json.dumps(data)):
            result = self.service.search_more('M.te Pornina')
        self.assertEqual([f['text'] for f in result.candidates], ['Monte Pornina'])

    def test_generic_name_cannot_match_only_its_municipality(self):
        for name in ('Municipio di Braone', 'Torrente Valle di Cobello', 'Somals di Braone'):
            self.assertFalse(plausible_name('Foppe di Braone', name, 'Braone'))
        for name in ('Foppe', 'Malga Foppe di Sotto', 'Foppe di Braone', 'Foppa'):
            self.assertTrue(plausible_name('Foppe di Braone', name, 'Comune di Braone'))
        self.assertTrue(plausible_name('Braone', 'Braone', 'Braone'))

    def test_generic_lookup_filters_town_hits_and_warns_for_partial_names(self):
        data = payload(name='Municipio di Braone', identifier=1, key='amenity', value='townhall')
        data['features'] += payload(name='Foppe', identifier=2, key='place', value='locality')['features']
        data['features'] += payload(name='Somals di Braone', identifier=3)['features']
        with patch(FETCH, return_value=json.dumps(data)):
            result = self.service.geocode_ranked('Foppe di Braone', municipality_hint='Braone')
        self.assertEqual([f['text'] for f in result.candidates], ['Foppe'])
        self.assertIn('Nessuna corrispondenza esatta', result.warning)
        self.assertIsNone(result.error)
        dialog = CandidateSelectorDialog(result.candidates)
        self.assertEqual(dialog.table.item(0, 0).text(), '')
        self.assertIn('Nome parziale', dialog.table.item(0, 5).text())
        dialog.close()

    def test_exact_name_does_not_raise_partial_name_warning(self):
        with patch(FETCH, return_value=json.dumps(payload(name='Foppe di Braone'))):
            result = self.service.geocode_ranked('Foppe di Braone', municipality_hint='Braone')
        self.assertTrue(result.ok)
        self.assertIsNone(result.warning)

    def test_rejected_provider_hits_cannot_reappear_through_raw_candidates(self):
        with patch(FETCH, return_value=json.dumps(payload(name='Municipio di Braone'))):
            result = self.service.geocode_ranked('Foppe di Braone', municipality_hint='Braone')
        self.assertFalse(result.ok)
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.raw['features'], [])

    def test_town_is_not_silently_used_for_missing_distinct_locality(self):
        town = GeocodingResult(ok=True, feature=feature(name='Braone'), query='Braone')
        with patch.object(self.service, '_geocode_municipality', return_value=town), \
                patch.object(self.service, 'geocode_ranked', return_value=GeocodingResult(ok=False)):
            result = self.service.geocode_prefer_municipality('Braone', 'Foppe di Braone')
        self.assertFalse(result.ok)
        self.assertEqual(result.candidates, [])
        self.assertIsNone(result.feature)
        self.assertIn('Comune trovato', result.error)

    def test_town_only_search_still_works(self):
        town = GeocodingResult(ok=True, feature=feature(name='Braone'), query='Braone')
        with patch.object(self.service, '_geocode_municipality', return_value=town), \
                patch.object(self.service, 'geocode_ranked', return_value=GeocodingResult(ok=False)):
            self.assertIs(self.service.geocode_prefer_municipality('Braone', ''), town)
            self.assertIs(self.service.geocode_prefer_municipality('Braone', 'Braone'), town)

    def test_partial_warning_reaches_deeper_dialog_without_becoming_network_error(self):
        chosen = feature(name='Foppe')
        result = GeocodingResult(ok=True, candidates=[chosen], warning='Corrispondenza parziale: verifica in mappa.')
        dialog = CandidateSelectorDialog([], query='Foppe di Braone', search_callback=lambda *a: result)
        dialog.search_button.click()
        self.assertIn('Corrispondenza parziale', dialog.search_status.text())
        dialog.close()

    def test_search_only_variants_drop_town_suffix_without_rewriting_record(self):
        plan = search_variants('Foppe di Braone', 'Braone')
        self.assertEqual(plan[:3], ['Foppe di Braone', 'Foppe Braone', 'foppe'])
        self.assertEqual(sum(q.lower().replace(',', '') == 'foppe braone' for q in plan), 1)
        self.assertEqual(len(plan), len(set(q.lower() for q in plan)))
        self.assertEqual(name_variants('Foppe di Braone'), ['Foppe di Braone'])
        self.assertNotIn('foppe', search_variants('Foppe di Braoneto', 'Braone'))
        self.assertNotIn('braone', search_variants('Braone', 'Braone')[1:])

    def test_initial_partial_hit_does_not_stop_before_better_name_variant(self):
        def response(url, **kwargs):
            q = parse_qs(urlsplit(url).query)['q'][0]
            return json.dumps(payload(name='Foppe di Braone' if q=='Foppe Braone' else 'Malga Foppe di Sotto'))
        with patch(FETCH, side_effect=response) as fetch:
            result = self.service.geocode_prefer_municipality(locality_text='Foppe di Braone', municipality_value='Braone')
        self.assertEqual(result.feature['text'], 'Foppe di Braone')
        self.assertIsNone(result.warning)
        self.assertEqual(fetch.call_count, 3)  # Town, original, simplified name.

    def test_initial_exact_name_keeps_fast_single_query_path(self):
        with patch(FETCH, return_value=json.dumps(payload(name='Foppe di Braone'))) as fetch:
            result = self.service.geocode_prefer_municipality(locality_text='Foppe di Braone')
        self.assertTrue(result.ok)
        self.assertEqual(fetch.call_count, 1)

    def test_duplicate_semantic_and_record_query_work_is_shared(self):
        attempted, tried = {}, []
        with patch.object(self.service, 'geocode_ranked', return_value=GeocodingResult(ok=False)) as lookup:
            self.service._search_reference('Foppe di Braone', 'generic_toponym', 'Braone', None, tried, attempted)
            self.service._search_reference('foppe di braone', 'locality', 'Braone', None, tried, attempted)
        self.assertEqual(lookup.call_count, 3)

    def test_distinctive_name_coverage_precedes_municipality_proximity(self):
        full = feature(name='Foppe Alte', lon=10.7)
        partial = feature(name='Foppe', identifier=2)
        for f in (full, partial):
            f['_geolichen_score'] = self.service._feature_score(f, 'Foppe Alte di Braone', 'locality', 'Braone', [10.2,46.05])
        self.assertGreater(name_evidence('Foppe Alte di Braone', full['text'], 'Braone')[0],
                           name_evidence('Foppe Alte di Braone', partial['text'], 'Braone')[0])
        best, _ = self.service._choose_best_from_candidates([partial,full])
        self.assertIs(best, full)

    def test_municipality_in_own_name_is_not_source_municipality_evidence(self):
        wrong = feature(name='Somals di Braone'); wrong['properties']['city'] = 'Ceto'
        correct = copy.deepcopy(wrong); correct['properties']['city'] = 'Braone'
        a = self.service._feature_score(correct, 'Somals di Braone', 'locality', 'Braone')
        b = self.service._feature_score(wrong, 'Somals di Braone', 'locality', 'Braone')
        self.assertGreater(a, b)
        reason = self.service._score_reason(wrong, 'Somals di Braone', municipality_hint='Braone')
        self.assertIn('Ceto', reason)
        self.assertNotIn('comune coerente', reason)

    def test_map_area_intersects_configuration_and_does_not_change_service(self):
        original = self.service.bbox
        data = payload(name='Foppe', lon=10.2, lat=46.05)
        data['features'] += payload(name='Foppe', identifier=2, lon=10.8, lat=46.3)['features']
        self.service.auto_expand = True
        with patch(FETCH, return_value=json.dumps(data)) as fetch:
            result = self.service.search_in_area('Foppe', 'Braone', (10.1,46,10.3,46.1))
        self.assertEqual(self.service.bbox, original)
        self.assertEqual([f['center'] for f in result.candidates], [[10.2,46.05]])
        for call in fetch.call_args_list:
            params = parse_qs(urlsplit(call.args[0]).query)
            self.assertEqual(params['bbox'], ['10.1,46.0,10.3,46.1'])
        self.assertLessEqual(fetch.call_count, 6)

    def test_map_area_rejects_disjoint_or_invalid_rectangle_without_requests(self):
        with patch(FETCH) as fetch:
            for bbox in ((0,0,1,1), (10,46,10,47), (10,46,float('nan'),47)):
                with self.assertRaises(ValueError):self.service.search_in_area('Foppe','Braone',bbox)
        fetch.assert_not_called()

    def test_map_area_empty_lookup_never_expands_outside_rectangle(self):
        self.service.auto_expand = True
        with patch(FETCH, return_value='{"features":[]}') as fetch:
            result = self.service.search_in_area('Foppe','Braone',(10.1,46,10.3,46.1))
        self.assertFalse(result.ok)
        self.assertTrue(all('bbox' in parse_qs(urlsplit(c.args[0]).query) for c in fetch.call_args_list))

    def test_map_area_button_retains_previous_choices_when_no_new_results(self):
        previous = feature(name='Foppe')
        callback = lambda *a: GeocodingResult(ok=False, error='Nessuna corrispondenza nella zona.')
        dialog = CandidateSelectorDialog([previous], query='Foppe', area_search_callback=callback)
        dialog.area_search_button.click()
        self.assertEqual(dialog.candidates, [previous])
        self.assertIn('precedenti conservate', dialog.search_status.text())
        self.assertTrue(dialog.area_search_button.isEnabled())
        dialog.close()

    def test_polygon_hole_and_edge_are_not_rectangle_membership(self):
        boundary = QgsGeometry.fromWkt('POLYGON((10 46,10.4 46,10.4 46.4,10 46.4,10 46),'
                                       '(10.1 46.1,10.2 46.1,10.2 46.2,10.1 46.2,10.1 46.1))')
        self.service.municipality_boundary = boundary
        inside = feature(lon=10.35, lat=46.35)
        hole = feature(identifier=2, lon=10.15, lat=46.15)
        edge = feature(identifier=3, lon=10, lat=46.2)
        for f in (inside, hole, edge): self.service._boundary_match(f)
        self.assertEqual(inside['_geolichen_municipality_match'], 'inside')
        self.assertNotEqual(hole['_geolichen_municipality_match'], 'inside')
        self.assertEqual(edge['_geolichen_municipality_match'], 'inside')

    def test_actual_boundary_replaces_center_proximity_bonus_without_hiding_alternatives(self):
        self.service.municipality_boundary = QgsGeometry.fromWkt('POLYGON((10.5 46,10.6 46,10.6 46.1,10.5 46.1,10.5 46))')
        inside = feature(lon=10.55)
        outside = feature(identifier=2, lon=10.2)
        a = self.service._feature_score(inside, 'Monte di prova', 'mountain_area', municipality_center=[10.2,46.05])
        b = self.service._feature_score(outside, 'Monte di prova', 'mountain_area', municipality_center=[10.2,46.05])
        self.assertGreater(a, b)
        inside['_geolichen_score'], outside['_geolichen_score'] = a, b
        best, ranked = self.service._choose_best_from_candidates([outside,inside], [10.2,46.05])
        self.assertIs(best, inside); self.assertEqual(len(ranked), 2)

    def test_municipality_lookup_transforms_crs_and_reads_current_edited_geometry(self):
        layer = QgsVectorLayer('Polygon?crs=EPSG:3857', 'Municipal fixture', 'memory')
        layer.dataProvider().addAttributes([QgsField('name', FieldType.String)])
        layer.updateFields()
        geometry = QgsGeometry.fromWkt('POLYGON((10.1 46,10.3 46,10.3 46.1,10.1 46.1,10.1 46))')
        geometry.transform(QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'), layer.crs(), QgsProject.instance()))
        f = QgsFeature(layer.fields()); f.setGeometry(geometry); f['name'] = 'Comune di Pròva'
        layer.dataProvider().addFeatures([f])
        result = MunicipalityBoundaryService.resolve(layer, 'name', 'Prova')
        self.assertTrue(result.intersects(QgsGeometry.fromPointXY(QgsPointXY(10.2,46.05))))
        self.assertIsNone(MunicipalityBoundaryService.resolve(layer, 'name', 'Altro'))
        layer.startEditing(); layer.changeGeometry(next(layer.getFeatures()).id(), QgsGeometry())
        self.assertIsNone(MunicipalityBoundaryService.resolve(layer, 'name', 'Prova'))

    def test_empty_dialog_can_search_and_confirm_a_new_candidate(self):
        chosen = feature()
        seen = []
        def search(query, old):
            seen.append(query)
            return GeocodingResult(ok=True, candidates=[chosen])
        dialog = CandidateSelectorDialog([], search_callback=search, query='Monte di prova')
        confirm = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(confirm.isEnabled())
        dialog.search_button.click()
        self.assertEqual(seen, ['Monte di prova'])
        self.assertTrue(confirm.isEnabled())
        confirm.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIs(dialog.selected(), chosen)
        dialog.close()

    def test_dialog_search_failure_preserves_selection_and_cancel_has_no_side_effects(self):
        chosen = feature()
        dialog = CandidateSelectorDialog([chosen], query='Test', search_callback=lambda *a: (_ for _ in ()).throw(OSError('offline')))
        dialog.search_button.click()
        self.assertEqual(dialog.candidates, [chosen])
        self.assertIn('conservati', dialog.search_status.text())
        dialog.reject(); self.assertIsNone(dialog.selected())
        self.assertEqual(self.service.archive.entries(), [])

    def test_archive_dialog_removes_only_selected_entry(self):
        archive = self.service.archive
        archive.remember('Uno', 'Comune', feature())
        archive.remember('Due', 'Comune', feature(identifier=2))
        dialog = ConfirmedLocalitiesDialog(archive)
        dialog.table.selectRow(1); dialog._remove()
        self.assertEqual([e['query'] for e in archive.entries()], ['Uno'])
        dialog.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='geolichen_locality_') as temporary:
        app = QgsApplication([], True, temporary); app.initQgis()
        with patch.object(QgsApplication, 'qgisSettingsDirPath', return_value=temporary):
            unittest.main(verbosity=2)
