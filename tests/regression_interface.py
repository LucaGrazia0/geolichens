"""QGIS regression checks for the collapsible UI, grid policy and centroid exit.

Run with the QGIS Python interpreter; fixtures are generated in a temporary folder.
No live geocoder, ITALIC service or specimen dataset is used.
"""

import copy
import importlib.util
import math
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QSettings, Qt, QTimer
from qgis.PyQt.QtWidgets import QDialog, QLabel
from qgis.core import (
    NULL, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsRasterLayer,
    QgsVectorLayer,
)
from osgeo import gdal
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from smoke_qgis import Iface

ROOT = Path(__file__).resolve().parents[1]
TEMP = None
APP = None
PROFILE = {
    'scientific_name': 'Test species', 'substrata': ['rocks'],
    'rock_type': 'siliceo', 'ecology_traits': 'siliceous rocks',
    'source': 'temporary test fixture', 'ecology_raw': {},
}


def metric_buffer(radius, center=None):
    from geolichen.services._shared_geo_utils import local_metric_crs
    wgs = QgsCoordinateReferenceSystem('EPSG:4326')
    center = center or QgsPointXY(10.2, 46.05)
    metric = local_metric_crs(center)
    point = QgsGeometry.fromPointXY(center)
    point.transform(QgsCoordinateTransform(wgs, metric, QgsProject.instance()))
    geometry = point.buffer(radius, 48)
    geometry.transform(QgsCoordinateTransform(metric, wgs, QgsProject.instance()))
    return geometry


class InterfaceRegression(unittest.TestCase):
    def setUp(self):
        import geolichen
        from geolichen.models.input_mapping_model import InputMappingModel
        self.iface = Iface()
        self.records = QgsVectorLayer('None', 'Temporary records', 'memory')
        provider = self.records.dataProvider()
        provider.addAttributes([QgsField(n, FieldType.String) for n in
                                ('record_id', 'municipality', 'locality', 'scientific_name')]
                               + [QgsField(n, FieldType.Double) for n in ('longitude', 'latitude', 'quota_dem')])
        self.records.updateFields()
        row = QgsFeature(self.records.fields())
        row.setAttributes(['TEST-1', 'Test town', 'Test locality', 'Test species', None, None, None])
        provider.addFeatures([row])
        QgsProject.instance().addMapLayer(self.records)
        self.feature = next(self.records.getFeatures())
        self.records.selectByIds([self.feature.id()])
        self.iface.activeLayer = lambda: self.records
        self.iface.canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
        self.plugin = geolichen.classFactory(self.iface)
        self.plugin.initGui()
        self.plugin.run()
        self.c = self.plugin.controller
        from geolichen.services.confirmed_localities_service import ConfirmedLocalitiesService
        self.c.geocoding_service.archive = ConfirmedLocalitiesService(Path(TEMP) / (self._testMethodName + '-localities.json'))
        self.dock = self.plugin.dock
        self.c.mapping = InputMappingModel(record_id='record_id', municipality='municipality',
                                           locality='locality', scientific_name='scientific_name')
        self.c.input_layer = self.records
        self.c.active_layer = self.records
        self.dock.chkUseOsmTrails.setChecked(False)
        self.errors = []
        self.c._warn = self.errors.append

    def tearDown(self):
        self.plugin.unload()
        self.iface.window.close()
        APP.processEvents()
        QgsProject.instance().removeAllMapLayers()
        APP.processEvents()

    def bind_geometry(self, geometry, mode='automatic', radius=None):
        self.c.current_feature = self.feature
        self.c._analysis_record_key = (self.records.id(), self.feature.id())
        self.c.search_geometry_mode = mode
        self.c.manual_search_radius_m = radius
        self.c.search_extent = QgsGeometry(geometry)
        self.c.current_boundary = QgsGeometry(geometry)
        self.c._create_locality_context('Test town', 'Test locality')
        self.c._sync_locality_extents(search_extent=self.c.search_extent)

    def automatic_analysis(self, radius):
        from geolichen.services.geocoding_service import GeocodingResult
        boundary = metric_buffer(radius)
        result = GeocodingResult(ok=True, feature={
            'center': [10.2, 46.05], 'text': 'Test locality',
            'place_name': 'Test locality', 'place_type': ['locality'],
        }, matched_source='locality')
        with patch.object(self.c.geocoding_service, 'geocode_prefer_municipality', return_value=result), \
             patch.object(self.c, '_select_geocoding_candidate_if_needed', side_effect=lambda candidate: candidate), \
             patch.object(self.c.initial_boundary_service, 'build_extents', return_value={
                 'search_extent': boundary, 'documented_extent': QgsGeometry(boundary),
             }), patch.object(self.c.italic_service, 'fetch_profile', side_effect=lambda *a: copy.deepcopy(PROFILE)):
            self.c.analyze_selected_record()
        self.assertFalse(self.errors, self.errors)
        self.assertIsNotNone(self.c.current_environment_result)
        return boundary

    def test_ui_sections_and_existing_bindings(self):
        self.assertFalse(hasattr(self.dock, 'btnConfirmPoint'))
        self.assertTrue(self.dock.configurationSection.content.isHidden())
        self.assertTrue(self.dock.italicSection.content.isHidden())
        self.assertTrue(self.dock.manualGeometrySection.content.isHidden())
        self.assertTrue(self.dock.resultGroup.isHidden())
        self.assertTrue(self.dock.inputSummaryGroup.isHidden())
        self.assertTrue(self.dock.txtSuitabilityGridStep.isHidden())
        self.assertEqual(self.dock.georeferencingGroup.title(), 'Georeferenziazione Località')
        self.dock.configurationSection.header.click()
        self.assertFalse(self.dock.configurationSection.content.isHidden())
        for widget, box in [
            (self.dock.cmbGeologyLayer, self.dock.geologyBox),
            (self.dock.cmbSoilLayer, self.dock.soilBox),
            (self.dock.cmbTreesLayer, self.dock.treesBox),
            (self.dock.lstAccessibilityLayers, self.dock.accessibilityBox),
            (self.dock.cmbVegetationBeltLayer, self.dock.vegetationBox),
            (self.dock.lstDemLayers, self.dock.demBox),
        ]:
            self.assertTrue(box.isAncestorOf(widget))
        self.dock.manualGeometrySection.header.click()
        self.assertFalse(self.dock.btnManualPoint.isHidden())
        self.dock.set_status('Test message')
        self.assertEqual(self.dock.lblOperationalStatus.text(), 'Test message')

    def test_long_layer_names_do_not_force_horizontal_scrolling(self):
        from qgis.PyQt.QtWidgets import QComboBox

        long_name = 'Carta forestale del territorio — layer ambientale con un nome molto lungo ' * 3
        for combo in self.dock.findChildren(QComboBox):
            combo.addItem(long_name)
            combo.setCurrentIndex(combo.count() - 1)
            self.assertIn(combo.currentText(), combo.toolTip())
        self.dock.lblItalicTaxon.setText('Species with a long scientific name and author ' * 4)
        self.dock.lblItalicUrl.setText('https://example.org/' + 'long_taxon_identifier_' * 12)
        self.dock.set_status('Tabella: ' + long_name + ' • 1 riga selezionata — pronto per l’analisi')
        self.dock.setFloating(True)
        self.dock.show()
        for expanded in (False, True):
            self.dock.configurationSection.setExpanded(expanded)
            self.dock.manualGeometrySection.setExpanded(expanded)
            self.dock.italicSection.setExpanded(expanded)
            for width in (420, 520, 800):
                with self.subTest(expanded=expanded, width=width):
                    self.dock.resize(width, 820)
                    APP.processEvents()
                    APP.processEvents()
                    scroll = self.dock.widget()
                    self.assertEqual(self.dock.width(), width)
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                    self.assertLessEqual(scroll.widget().width(), scroll.viewport().width())

    def prepare_map_choice(self):
        from qgis.gui import QgsMapToolPan
        self.automatic_analysis(80)
        previous = QgsMapToolPan(self.iface.canvas)
        self.iface.canvas.setMapTool(previous)
        with patch('geolichen.controllers.plugin_controller.EcologicalPointChoiceDialog.exec',
                   return_value=QDialog.DialogCode.Accepted):
            self.dock.btnHabitatSuitability.click()
        self.assertFalse(self.errors, self.errors)
        self.assertIsNotNone(self.c.confirm_point_tool)
        return previous, self.c.current_suitability_result['selected_candidate']

    def test_ecological_choice_dialog_labels_and_actions(self):
        from geolichen.gui.ecological_point_choice_dialog import EcologicalPointChoiceDialog, CandidateUseDialog
        first = EcologicalPointChoiceDialog(12)
        self.assertEqual(first.windowTitle(), 'Scelta del punto ecologico')
        self.assertEqual(first.next_button.text(), 'Avanti')
        self.assertEqual(first.cancel_button.text(), 'Cancel')
        first.next_button.click()
        self.assertEqual(first.result(), QDialog.DialogCode.Accepted)
        first.cancel_button.click()
        self.assertEqual(first.result(), QDialog.DialogCode.Rejected)
        for button, decision, result in [('use_button', 'use', QDialog.DialogCode.Accepted),
                                          ('retry_button', 'retry', QDialog.DialogCode.Accepted),
                                          ('exit_button', 'exit', QDialog.DialogCode.Rejected)]:
            dialog = CandidateUseDialog(7, 80.5, 1.2)
            self.assertTrue(any('rank 7' in label.text() for label in dialog.findChildren(QLabel)))
            getattr(dialog, button).click()
            self.assertEqual(dialog.decision, decision)
            self.assertEqual(dialog.result(), result)
            dialog.deleteLater()
        first.deleteLater()

    def test_manual_choice_cancel_keeps_grid_without_starting_capture(self):
        self.automatic_analysis(80)
        previous = self.iface.canvas.mapTool()
        with patch('geolichen.controllers.plugin_controller.EcologicalPointChoiceDialog.exec',
                   return_value=QDialog.DialogCode.Rejected):
            self.dock.btnHabitatSuitability.click()
        self.assertFalse(self.errors, self.errors)
        self.assertIsNotNone(self.c.current_suitability_result)
        self.assertIsNone(self.c.confirm_point_tool)
        self.assertIs(self.iface.canvas.mapTool(), previous)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)
        self.assertIsNone(self.c.confirmed_results_layer_id)
        self.assertTrue(self.dock.btnAutomaticPoint.isEnabled())

    def test_manual_choice_next_starts_indexed_capture(self):
        previous, selected = self.prepare_map_choice()
        self.assertIs(self.c.confirm_previous_tool, previous)
        self.assertIs(self.iface.canvas.mapTool(), self.c.confirm_point_tool)
        cache = self.c._candidate_snap_cache
        self.assertIsNotNone(cache)
        self.assertTrue(cache['indexed_rows'])
        count = len((self.c.current_suitability_result['display_features']))
        distance = self.c.habitat_suitability_service.uncertainty_service._distance_m
        with patch.object(self.c.habitat_suitability_service.uncertainty_service, '_distance_m', wraps=distance) as measure:
            nearest, meters, _ = self.c._nearest_confirm_candidate(selected['point'])
        self.assertIs(nearest, selected)
        self.assertLess(meters, 0.01)
        self.assertLessEqual(measure.call_count, 8)
        self.assertGreater(count, measure.call_count)
        self.assertIs(self.c._candidate_snap_cache, cache)

    def test_manual_choice_retry_reuses_same_grid_without_recalculation(self):
        _, selected = self.prepare_map_choice()
        tool = self.c.confirm_point_tool
        result = self.c.current_suitability_result
        ranks = [(row['rank'], row['score']) for row in result['display_features']]
        with patch.object(self.c, '_prompt_candidate_use', return_value='retry'), \
             patch.object(self.c.habitat_suitability_service, 'find_best_point') as ranking, \
             patch.object(self.c, '_candidate_confirmation_data') as uncertainty, \
             patch('geolichen.controllers.plugin_controller.ConfirmPointDialog') as editor:
            tool.canvasClicked.emit(selected['point'], Qt.MouseButton.LeftButton)
        ranking.assert_not_called()
        uncertainty.assert_not_called()
        editor.assert_not_called()
        self.assertIs(self.c.confirm_point_tool, tool)
        self.assertIs(self.c.current_suitability_result, result)
        self.assertEqual(ranks, [(row['rank'], row['score']) for row in result['display_features']])
        self.assertIsNone(self.c.current_selected_candidate)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)

    def test_live_preview_uses_selected_coordinates_and_confirmation_model_radius(self):
        self.prepare_map_choice()
        result = self.c.current_suitability_result
        selected = result['display_features'][-1]
        self.c._queue_candidate_preview(selected)
        self.assertIn(f"Lat {selected['point'].y():.6f}", self.dock.lblCandidatePreview.text())
        self.c._finish_candidate_preview()
        _, uncertainty = self.c._candidate_confirmation_data(self.records, selected, result['display_features'], 'test_preview')
        self.assertIn(f"{float(uncertainty['model_radius_m']):.1f} m", self.dock.lblCandidatePreview.text())
        self.assertIn('R55–S65', self.dock.lblCandidatePreview.text())
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)

    def test_preview_caches_model_without_recalculating_ranking_or_full_uncertainty(self):
        _, selected = self.prepare_map_choice()
        uncertainty = self.c.habitat_suitability_service.uncertainty_service
        with patch.object(uncertainty.model_service, 'estimate', wraps=uncertainty.model_service.estimate) as model, \
             patch.object(uncertainty, 'estimate') as full, \
             patch.object(self.c.habitat_suitability_service, 'find_best_point') as ranking:
            self.c._queue_candidate_preview(selected)
            self.assertTrue(self.c._candidate_preview_timer.isActive())
            model.assert_not_called()
            self.c._finish_candidate_preview()
            self.c._queue_candidate_preview(selected)
            self.assertEqual(model.call_count, 1)
            full.assert_not_called(); ranking.assert_not_called()
            self.assertFalse(self.c._candidate_preview_timer.isActive())

    def test_preview_is_cleared_on_cancel_and_record_deselection(self):
        _, selected = self.prepare_map_choice()
        self.c._queue_candidate_preview(selected)
        self.records.removeSelection()
        self.c._finish_candidate_preview()
        self.assertEqual(self.dock.lblCandidatePreview.text(), '')
        self.assertFalse(self.c._candidate_preview_timer.isActive())
        self.records.selectByIds([self.feature.id()])
        self.c._queue_candidate_preview(selected)
        self.c.stop_confirm_point_capture()
        self.assertEqual(self.dock.lblCandidatePreview.text(), '')
        self.assertIsNone(self.c._candidate_preview_pending)

    def test_failed_analysis_clears_previous_candidates_and_explains_compatibility(self):
        self.prepare_map_choice()
        previous = self.c.current_suitability_result
        previous_layer_id = previous['layer'].id()
        with patch('geolichen.services.habitat_suitability_service.HabitatSuitabilityService.find_best_point',
                          side_effect=ValueError('Nessun punto candidato compatibile dopo i pre-filtri. Punti esclusi per quota: 100')):
            result = self.c.find_habitat_suitability_point()
        self.assertTrue(result is None)
        self.assertIsNone(self.c.current_suitability_result)
        self.assertIsNone(self.c.current_selected_candidate)
        self.assertIn('Controlla località e buffer', self.errors[-1])
        self.assertIn('quota: 100', self.errors[-1])
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)
        self.assertIsNone(QgsProject.instance().mapLayer(previous_layer_id))

    def test_empty_service_result_cannot_start_candidate_selection_or_save_old_point(self):
        self.prepare_map_choice()
        with patch('geolichen.services.habitat_suitability_service.HabitatSuitabilityService.find_best_point', return_value={'features': [], 'best_point': None}), \
             patch('geolichen.controllers.plugin_controller.EcologicalPointChoiceDialog.exec') as dialog:
            self.dock.btnHabitatSuitability.click()
        dialog.assert_not_called()
        self.assertIn('nessun punto compatibile', self.errors[-1])
        self.assertIsNone(self.c.confirm_point_tool)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)

    def test_manual_choice_exit_restores_previous_map_tool(self):
        previous, selected = self.prepare_map_choice()
        with patch.object(self.c, '_prompt_candidate_use', return_value='exit'), \
             patch('geolichen.controllers.plugin_controller.ConfirmPointDialog') as editor:
            self.c.confirm_point_tool.canvasClicked.emit(selected['point'], Qt.MouseButton.LeftButton)
        editor.assert_not_called()
        self.assertIsNone(self.c.confirm_point_tool)
        self.assertIs(self.iface.canvas.mapTool(), previous)
        self.assertIsNone(self.c.confirm_snap_marker)
        self.assertIsNone(self.c.confirmed_results_layer_id)

    def test_manual_choice_escape_and_right_click_stop_without_writing(self):
        from qgis.PyQt.QtCore import QEvent
        from qgis.PyQt.QtGui import QKeyEvent
        for escape in (True, False):
            previous, selected = self.prepare_map_choice()
            if escape:
                self.c.confirm_point_tool.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
            else:
                self.c.confirm_point_tool.canvasClicked.emit(selected['point'], Qt.MouseButton.RightButton)
            self.assertIsNone(self.c.confirm_point_tool)
            self.assertIs(self.iface.canvas.mapTool(), previous)
            self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)

    def test_changing_map_tool_ends_candidate_capture_without_overriding_new_tool(self):
        from qgis.gui import QgsMapToolPan
        self.prepare_map_choice()
        new_tool = QgsMapToolPan(self.iface.canvas)
        self.iface.canvas.setMapTool(new_tool)
        self.assertIsNone(self.c.confirm_point_tool)
        self.assertIs(self.iface.canvas.mapTool(), new_tool)

    def test_manual_choice_yes_opens_existing_editor_and_cancel_does_not_save(self):
        from geolichen.gui.confirm_point_dialog import ConfirmPointDialog
        previous, selected = self.prepare_map_choice()
        seen = []
        def reject_editor(dialog):
            seen.append(dialog)
            self.assertEqual(dialog.candidate_rank, selected['rank'])
            QTimer.singleShot(0, dialog.reject)
        with patch.object(self.c, '_prompt_candidate_use', return_value='use'), \
             patch.object(ConfirmPointDialog, 'show', reject_editor), \
             patch.object(self.c.habitat_suitability_service, 'find_best_point') as ranking:
            self.c.confirm_point_tool.canvasClicked.emit(selected['point'], Qt.MouseButton.LeftButton)
        self.assertFalse(self.errors, self.errors)
        ranking.assert_not_called()
        self.assertEqual(len(seen), 1)
        self.assertIsNone(self.c.confirm_point_tool)
        self.assertIs(self.iface.canvas.mapTool(), previous)
        self.assertIsNone(self.c.current_selected_candidate)
        self.assertIsNone(self.c.confirmed_results_layer_id)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)

    def test_manual_choice_record_switch_during_rank_prompt_blocks_editor(self):
        _, selected = self.prepare_map_choice()
        other, row = self.add_other_table()
        def switch(*args):
            other.selectByIds([row.id()])
            return 'use'
        with patch.object(self.c, '_prompt_candidate_use', side_effect=switch), \
             patch('geolichen.controllers.plugin_controller.ConfirmPointDialog') as editor:
            self.c.confirm_point_tool.canvasClicked.emit(selected['point'], Qt.MouseButton.LeftButton)
        editor.assert_not_called()
        self.assertTrue(self.errors)
        self.assertIsNone(self.c.confirm_point_tool)
        self.assertEqual(other.getFeature(row.id())['longitude'], NULL)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)

    def test_manual_choice_heatmap_mode_also_displays_pickable_points(self):
        self.dock.cmbSuitabilityView.setCurrentText('Suitability Surface')
        self.prepare_map_choice()
        result = self.c.current_suitability_result
        self.assertIsNotNone(result['heatmap_layer'])
        self.assertIsNotNone(result['layer'])
        node = QgsProject.instance().layerTreeRoot().findLayer(result['layer'].id())
        self.assertTrue(node.isVisible())
        self.assertEqual(self.dock.cmbSuitabilityView.currentText(), 'Suitability Surface')

    def test_photon_search_feeds_ecological_grid_without_api_key(self):
        import json
        from urllib.parse import parse_qs, urlsplit
        boundary = metric_buffer(80)
        def response(url, **kwargs):
            query = parse_qs(urlsplit(url).query)['q'][0]
            name = 'Test town' if query.startswith('Test town') else 'Test locality'
            return json.dumps({'features': [{'geometry': {'type': 'Point',
                'coordinates': [10.2, 46.05]}, 'properties': {'name': name,
                'city': 'Test town', 'country': 'Italia', 'osm_key': 'place',
                'osm_value': 'town' if name == 'Test town' else 'locality',
                'osm_type': 'N', 'osm_id': 101 if name == 'Test town' else 102}}]})
        with patch('geolichen.services.osm_geocoding_service.fetch_text', side_effect=response), \
             patch.object(self.c.geocoding_service.client, 'MIN_INTERVAL_S', 0), \
             patch.object(self.c.initial_boundary_service, 'build_extents', return_value={
                 'search_extent': boundary, 'documented_extent': QgsGeometry(boundary)}), \
             patch.object(self.c.italic_service, 'fetch_profile', side_effect=lambda *a: copy.deepcopy(PROFILE)), \
             patch.object(self.c, '_select_geocoding_candidate_if_needed', side_effect=lambda result: result):
            self.c.analyze_selected_record()
        self.assertFalse(self.errors, self.errors)
        self.assertFalse(hasattr(self.dock, 'txtApiKey'))
        self.assertEqual(self.c.current_geocoding_result.feature['provider'], 'Photon / OpenStreetMap')
        self.assertEqual(self.c.current_geocoding_result.center, [10.2, 46.05])
        self.c.find_habitat_suitability_point()
        self.assertFalse(self.errors, self.errors)
        self.assertEqual(self.c.current_suitability_result['selected_candidate']['rank'], 1)

    def run_locality_choice(self, result, selector):
        from geolichen.gui.candidate_selector_dialog import CandidateSelectorDialog
        boundary = metric_buffer(80)
        with patch.object(self.c.geocoding_service, 'geocode_prefer_municipality', return_value=result), \
             patch.object(self.c.initial_boundary_service, 'build_extents', return_value={
                 'search_extent': boundary, 'documented_extent': QgsGeometry(boundary)}) as build, \
             patch.object(self.c.italic_service, 'fetch_profile', side_effect=lambda *a: copy.deepcopy(PROFILE)):
            def choose(dialog):
                build.assert_not_called()
                self.assertIsNone(self.c.search_extent)
                return selector(dialog)
            with patch.object(CandidateSelectorDialog, 'exec', choose):
                self.c.analyze_selected_record()
        self.assertIsNone(self.c.candidate_preview_band)
        self.assertIsNone(self.c.candidate_preview_center_band)
        self.assertFalse(self.errors, self.errors)
        return build

    def test_single_locality_requires_confirmation_before_buffer(self):
        from geolichen.services.geocoding_service import GeocodingResult
        from qgis.PyQt.QtWidgets import QDialogButtonBox
        feature = {'center': [10.2, 46.05], 'text': 'Test locality', 'place_type': ['locality']}
        result = GeocodingResult(ok=True, feature=feature)
        seen = []
        def choose(dialog):
            seen.append(dialog.table.rowCount())
            box = dialog.findChild(QDialogButtonBox)
            self.assertEqual(box.button(QDialogButtonBox.StandardButton.Ok).text(), 'Crea buffer')
            dialog._accept_selection()
            return QDialog.DialogCode.Accepted
        build = self.run_locality_choice(result, choose)
        self.assertEqual(seen, [1])
        build.assert_called_once()
        self.assertIs(build.call_args.args[0], feature)
        self.assertIsNotNone(self.c.search_extent)

    def test_empty_locality_lookup_can_be_refined_before_buffer_creation(self):
        from geolichen.services.geocoding_service import GeocodingResult
        selected = {'text': 'Corrected locality', 'center': [10.201, 46.051],
                    '_geolichen_original_query': 'Corrected locality'}
        def choose(dialog):
            self.assertEqual(dialog.table.rowCount(), 0)
            dialog.query_edit.setText('Corrected locality')
            dialog.search_button.click()
            self.assertEqual(dialog.table.rowCount(), 1)
            dialog._accept_selection()
            return QDialog.DialogCode.Accepted
        with patch.object(self.c.geocoding_service, 'search_more',
                          return_value=GeocodingResult(ok=True, candidates=[selected])):
            build = self.run_locality_choice(GeocodingResult(ok=False, error='No results'), choose)
        self.assertIs(build.call_args.args[0], selected)
        saved = self.c.geocoding_service.archive.lookup('Test locality', 'Test town')
        self.assertEqual(saved[0]['center'], selected['center'])
        self.assertNotIn('GSS', saved[0])

    def test_canceling_locality_choice_does_not_save_anchor(self):
        from geolichen.services.geocoding_service import GeocodingResult
        result = GeocodingResult(ok=True, feature={'text': 'Test locality', 'center': [10.2,46.05]})
        self.run_locality_choice(result, lambda dialog: QDialog.DialogCode.Rejected)
        self.assertEqual(self.c.geocoding_service.archive.entries(), [])

    def test_initial_partial_name_warning_is_shown_before_locality_confirmation(self):
        from geolichen.services.geocoding_service import GeocodingResult
        feature = {'text': 'Foppe', 'center': [10.2,46.05], '_geolichen_partial_name': True}
        result = GeocodingResult(ok=True, feature=feature, warning='Nessuna corrispondenza esatta: verifica in mappa.')
        def cancel(dialog):
            self.assertIn('Nessuna corrispondenza esatta', dialog.search_status.text())
            self.assertEqual(dialog.table.item(0, 0).text(), '')
            return QDialog.DialogCode.Rejected
        build = self.run_locality_choice(result, cancel)
        build.assert_not_called()

    def test_map_lookup_uses_extent_captured_before_candidate_previews(self):
        from geolichen.services.geocoding_service import GeocodingResult
        initial = (10.1,46,10.3,46.1)
        feature = {'text': 'Foppe', 'center': [10.2,46.05]}
        result = GeocodingResult(ok=True, feature=feature)
        def cancel(dialog):
            dialog.area_search_button.click()
            search.assert_called_once_with('Test locality', 'Test town', initial)
            return QDialog.DialogCode.Rejected
        with patch.object(self.c, '_geocoding_map_bbox', return_value=initial), \
             patch.object(self.c.geocoding_service, 'search_in_area', return_value=result) as search:
            build = self.run_locality_choice(result, cancel)
        build.assert_not_called()

    def test_map_extent_failure_does_not_block_normal_locality_selection(self):
        from geolichen.services.geocoding_service import GeocodingResult
        result = GeocodingResult(ok=True, feature={'text': 'Test locality', 'center': [10.2,46.05]})
        def cancel(dialog):
            self.assertIsNone(dialog.area_search_callback)
            return QDialog.DialogCode.Rejected
        with patch.object(self.c, '_geocoding_map_bbox', side_effect=ValueError('invalid canvas CRS')):
            build = self.run_locality_choice(result, cancel)
        build.assert_not_called()

    def test_municipality_controls_use_polygon_layer_identity_and_name_field(self):
        layer = QgsVectorLayer('Polygon?crs=EPSG:4326', 'Municipal fixture', 'memory')
        layer.dataProvider().addAttributes([QgsField('town_name', FieldType.String)])
        layer.updateFields()
        f = QgsFeature(layer.fields()); f['town_name'] = 'Test town'
        f.setGeometry(QgsGeometry.fromWkt('POLYGON((10.1 46,10.3 46,10.3 46.1,10.1 46.1,10.1 46))'))
        layer.dataProvider().addFeatures([f]); QgsProject.instance().addMapLayer(layer)
        combo = self.dock.cmbMunicipalityBoundaryLayer
        self.assertEqual(combo.findData(self.records.id()), -1)
        combo.setCurrentIndex(combo.findData(layer.id()))
        self.dock.cmbMunicipalityBoundaryField.setCurrentText('town_name')
        self.c._configure_geocoding_evidence('Test town')
        self.assertIsNotNone(self.c.geocoding_service.municipality_boundary)
        self.assertEqual(QgsProject.instance().readEntry('GeoLichen', 'municipality_boundary_layer', '')[0], layer.id())
        QgsProject.instance().removeMapLayer(layer.id())
        self.c._configure_geocoding_evidence('Test town')
        self.assertIsNone(self.c.geocoding_service.municipality_boundary)

    def test_multiple_localities_build_buffer_from_selected_nonfirst_candidate(self):
        result, boundary = self._automatic_flow_fixture()
        selected = result.candidates[1]
        def choose(dialog):
            dialog.table.selectRow(1)
            dialog._accept_selection()
            return QDialog.DialogCode.Accepted
        build = self.run_locality_choice(result, choose)
        self.assertIs(build.call_args.args[0], selected)
        self.assertEqual(self.c.current_geocoding_result.center, [10.2, 46.05])

    def test_cancelling_single_locality_creates_no_buffer(self):
        from geolichen.services.geocoding_service import GeocodingResult
        feature = {'center': [10.2, 46.05], 'text': 'Test locality', 'place_type': ['locality']}
        result = GeocodingResult(ok=True, feature=feature)
        build = self.run_locality_choice(result, lambda dialog: QDialog.DialogCode.Rejected)
        build.assert_not_called()
        self.assertIsNone(self.c.current_geocoding_result)
        self.assertIsNone(self.c.search_extent)
        self.assertIsNone(self.c.current_boundary)

    def test_accepted_dialog_without_selected_locality_cannot_build_buffer(self):
        from geolichen.services.geocoding_service import GeocodingResult
        result = GeocodingResult(ok=True, feature={'center': [10.2, 46.05], 'text': 'Test locality'})
        build = self.run_locality_choice(result, lambda dialog: QDialog.DialogCode.Accepted)
        build.assert_not_called()
        self.assertIsNone(self.c.search_extent)

    def test_accessibility_only_lists_usable_line_layers(self):
        line = QgsVectorLayer('LineString?crs=EPSG:4326', 'Usable trails', 'memory')
        polygon = QgsVectorLayer('Polygon?crs=EPSG:4326', 'Soil polygons', 'memory')
        QgsProject.instance().addMapLayer(line)
        QgsProject.instance().addMapLayer(polygon)
        items = self.c._accessibility_layer_items()
        self.assertIn(line.name(), items)
        self.assertNotIn(polygon.name(), items)
        self.assertNotIn(self.records.name(), items)
        self.dock.populate_accessibility_layer_list([(line.name(), True)])
        self.assertEqual(self.c._selected_accessibility_layers(), [line])

    def test_osm_trail_geometry_is_used_by_actual_accessibility_distance_engine(self):
        from geolichen.services.osm_trail_service import OsmTrailResult
        self.automatic_analysis(80)
        payload = {'elements': [{'type': 'way', 'id': 12345, 'tags': {
            'highway': 'path', 'name': 'Synthetic trail'}, 'geometry': [
                {'lon': 10.199, 'lat': 46.05}, {'lon': 10.201, 'lat': 46.05}]}]}
        layer, count, warning = self.c.osm_trail_service._parse_to_layer(payload)
        self.dock.chkUseOsmTrails.setChecked(True)
        with patch.object(self.c.osm_trail_service, 'fetch', return_value=OsmTrailResult(
                success=True, layer=layer, feature_count=count)):
            self.c.find_habitat_suitability_point()
        self.assertFalse(self.errors, self.errors)
        self.assertIs(self.c.current_osm_trail_layer, layer)
        engine = self.c.habitat_suitability_service
        contexts = engine._prepare_accessibility_contexts_v293([layer], self.c.search_extent)
        nearest = engine._nearest_accessibility_v293(QgsPointXY(10.2, 46.05), contexts)
        self.assertIsNotNone(nearest)
        self.assertLess(nearest['distance_m'], 1)
        self.assertEqual(nearest['osm_id'], 12345)
        self.assertEqual(self.c.current_suitability_result['osm_trails_notice'], '')
        self.assertIn('pedonali/equestri: 1', self.dock.lblOsmTrailsInfo.text())
        self.dock.set_status('Snap → candidato di prova')
        self.assertIn('pedonali/equestri: 1', self.dock.lblOsmTrailsInfo.text())
        self.c._clear_osm_trails()
        self.assertEqual(self.dock.lblOsmTrailsInfo.text(), '')

    def test_osm_failure_does_not_leave_previous_trails_or_hide_warning(self):
        from geolichen.services.osm_trail_service import OsmTrailResult
        self.automatic_analysis(80)
        self.dock.chkUseOsmTrails.setChecked(True)
        old = QgsVectorLayer('LineString?crs=EPSG:4326', 'Previous OSM trails', 'memory')
        QgsProject.instance().addMapLayer(old)
        old_id = old.id()
        self.c.current_osm_trail_layer = old
        with patch.object(self.c.osm_trail_service, 'fetch', return_value=OsmTrailResult(
                success=False, error='Test timeout')):
            self.c.find_habitat_suitability_point()
        self.assertFalse(self.errors, self.errors)
        self.assertIsNone(self.c.current_osm_trail_layer)
        self.assertIsNone(QgsProject.instance().mapLayer(old_id))
        self.assertIn('Test timeout', self.c.current_suitability_result['osm_trails_notice'])
        self.assertIn('Test timeout', self.dock.lblOsmTrailsInfo.text())
        self.dock.set_status('Pronto per la scelta del candidato')
        self.assertIn('Test timeout', self.dock.lblOsmTrailsInfo.text())

    def test_new_buffer_removes_only_temporary_osm_trails(self):
        self.bind_geometry(metric_buffer(80))
        old = QgsVectorLayer('LineString?crs=EPSG:4326', 'Previous OSM trails', 'memory')
        own = QgsVectorLayer('LineString?crs=EPSG:4326', 'User trails', 'memory')
        QgsProject.instance().addMapLayer(old)
        QgsProject.instance().addMapLayer(own)
        old_id, own_id = old.id(), own.id()
        self.c.current_osm_trail_layer = old
        self.c._invalidate_candidate_results()
        self.assertIsNone(self.c.current_osm_trail_layer)
        self.assertIsNone(QgsProject.instance().mapLayer(old_id))
        self.assertIsNotNone(QgsProject.instance().mapLayer(own_id))

    def test_disabling_osm_does_not_reuse_previously_checked_temporary_layer(self):
        self.automatic_analysis(80)
        old = QgsVectorLayer('LineString?crs=EPSG:4326', 'Previous OSM trails', 'memory')
        QgsProject.instance().addMapLayer(old)
        old_id = old.id()
        self.c.current_osm_trail_layer = old
        self.dock.populate_accessibility_layer_list([(old.name(), True)])
        self.dock.chkUseOsmTrails.setChecked(False)
        with patch.object(self.c.osm_trail_service, 'fetch') as fetch:
            self.c.find_habitat_suitability_point()
        fetch.assert_not_called()
        self.assertFalse(self.errors, self.errors)
        self.assertIsNone(self.c.current_osm_trail_layer)
        self.assertIsNone(QgsProject.instance().mapLayer(old_id))

    def test_manual_corridor_queries_the_current_buffer_for_osm_trails(self):
        from geolichen.services.osm_trail_service import OsmTrailResult
        self.automatic_analysis(80)
        line = QgsGeometry.fromPolylineXY([QgsPointXY(10.199, 46.05), QgsPointXY(10.201, 46.05)])
        corridor = line.buffer(.0001, 12)
        self.bind_geometry(corridor, 'manual_line', 10)
        self.dock.chkUseOsmTrails.setChecked(True)
        with patch.object(self.c.osm_trail_service, 'fetch', return_value=OsmTrailResult(
                success=True, feature_count=0)) as fetch:
            self.c.find_habitat_suitability_point()
        self.assertFalse(self.errors, self.errors)
        self.assertTrue(fetch.call_args.args[0].equals(corridor))
        self.assertEqual(fetch.call_args.args[1].authid(), 'EPSG:4326')

    def test_automatic_point_never_opens_manual_choice_prompts(self):
        with patch('geolichen.controllers.plugin_controller.EcologicalPointChoiceDialog') as intro, \
             patch('geolichen.controllers.plugin_controller.CandidateUseDialog') as rank_prompt:
            self._run_automatic_flow()
        self.assertFalse(self.errors, self.errors)
        intro.assert_not_called()
        rank_prompt.assert_not_called()
        self.assertNotEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)

    def test_grid_policy_thresholds_and_hidden_override(self):
        from geolichen.services.grid_resolution_service import grid_step_for_radius
        for radius, step in [(0, 10), (250, 10), (250.5, 30), (251, 30), (1000, 30),
                             (1001, 50), (3000, 50), (3001, 100), (50000, 100)]:
            with self.subTest(radius=radius):
                self.assertEqual(grid_step_for_radius(radius), step)
                self.bind_geometry(metric_buffer(max(radius, 1)), 'manual', radius)
                self.dock.txtSuitabilityGridStep.setText('999')
                self.assertEqual(self.c._get_suitability_grid_step(), step)
        for invalid in [-1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                grid_step_for_radius(invalid)

    def test_automatic_radius_uses_actual_search_extent(self):
        for radius, step in [(250, 10), (250.001, 30), (251, 30), (1000, 30), (1001, 50), (3000, 50), (3001, 100)]:
            self.bind_geometry(metric_buffer(radius))
            self.assertEqual(self.c._get_suitability_grid_step(), step)

    def test_buffer_summary_tracks_geometry_and_reset(self):
        self.bind_geometry(metric_buffer(200), 'manual', 200)
        summary = self.dock.lblBufferGridInfo.text()
        self.assertIn('12.56 ha', summary)
        self.assertIn('Raggio buffer: 200 m', summary)
        self.assertIn('Passo griglia: 10 m', summary)
        self.bind_geometry(metric_buffer(1100))
        summary = self.dock.lblBufferGridInfo.text()
        self.assertIn('3.80 km²', summary)
        self.assertIn('Raggio di riferimento: 1100 m', summary)
        self.assertIn('Passo griglia: 50 m', summary)
        self.c.search_extent = None
        self.c._get_suitability_grid_step()
        self.assertIn('nessuna area definita', self.dock.lblBufferGridInfo.text())

    def configure_source(self):
        from geolichen.gui.field_mapping_dialog import FieldMappingDialog
        with patch.object(FieldMappingDialog, 'exec', return_value=QDialog.DialogCode.Accepted):
            self.assertTrue(self.c.configure_fields(self.records))

    def add_other_table(self, name='Other records'):
        layer = QgsVectorLayer('None', name, 'memory')
        layer.dataProvider().addAttributes(list(self.records.fields()))
        layer.updateFields()
        row = QgsFeature(layer.fields())
        row.setAttributes(['OTHER-1', 'Other town', 'Other locality', 'Other species', None, None, None])
        layer.dataProvider().addFeatures([row])
        QgsProject.instance().addMapLayer(layer)
        return layer, next(layer.getFeatures())

    def test_selected_other_table_overrides_cached_unselected_source(self):
        self.configure_source()
        self.records.removeSelection()
        other, row = self.add_other_table()
        other.selectByIds([row.id()])
        self.assertIs(self.iface.activeLayer(), self.records)
        self.assertTrue(self.c._ensure_input_mapping())
        self.automatic_analysis(80)
        self.assertIs(self.c.input_layer, other)
        self.assertEqual(self.c._analysis_record_key, (other.id(), row.id()))
        self.assertEqual(self.dock.cmbRecordLayer.currentData(), other.id())

    def test_detached_table_selection_wins_even_when_old_row_still_selected(self):
        self.configure_source()
        other, row = self.add_other_table()
        other.selectByIds([row.id()])
        self.assertEqual(self.records.selectedFeatureCount(), 1)
        self.assertEqual(self.c._selected_feature()['record_id'], 'OTHER-1')
        self.assertIs(self.c.input_layer, other)
        self.assertIs(self.c._selection_layer, other)
        self.assertIn('Other records', self.dock.lblOperationalStatus.text())

    def test_source_combo_uses_ids_for_duplicate_names(self):
        self.configure_source()
        other, row = self.add_other_table(self.records.name())
        other.selectByIds([row.id()])
        self.dock.cmbRecordLayer.setCurrentIndex(self.dock.cmbRecordLayer.findData(self.records.id()))
        self.assertIs(self.c._valid_input_or_active_layer(), self.records)
        self.assertEqual(self.c._selected_feature()['record_id'], 'TEST-1')
        self.dock.cmbRecordLayer.setCurrentIndex(self.dock.cmbRecordLayer.findData(other.id()))
        self.assertIs(self.c._valid_input_or_active_layer(), other)

    def test_new_table_with_different_fields_requests_its_own_mapping(self):
        self.configure_source()
        other = QgsVectorLayer('None?field=taxon:string&field=localita:string', 'Different fields', 'memory')
        row = QgsFeature(other.fields())
        row.setAttributes(['Other species', 'Other locality'])
        other.dataProvider().addFeatures([row])
        QgsProject.instance().addMapLayer(other)
        other.selectByIds([next(other.getFeatures()).id()])
        self.assertIsNone(self.c.mapping)
        from geolichen.gui.field_mapping_dialog import FieldMappingDialog
        with patch.object(FieldMappingDialog, 'exec', return_value=QDialog.DialogCode.Accepted):
            self.assertTrue(self.c._ensure_input_mapping())
        self.assertEqual(self.c.mapping.scientific_name, 'taxon')
        self.assertEqual(self.c.mapping.locality, 'localita')

    def test_removing_new_source_recovers_remaining_selected_table(self):
        self.configure_source()
        other, row = self.add_other_table()
        other.selectByIds([row.id()])
        self.assertTrue(self.c._ensure_input_mapping())
        QgsProject.instance().removeMapLayer(other.id())
        self.assertIs(self.c._valid_input_or_active_layer(), self.records)
        self.assertEqual(self.c._selected_feature()['record_id'], 'TEST-1')

    def test_stale_analysis_cannot_rank_or_confirm_other_table_with_same_fid(self):
        self.automatic_analysis(80)
        self.c.find_habitat_suitability_point()
        selected = self.c.current_suitability_result['selected_candidate']
        other, row = self.add_other_table()
        self.assertEqual(row.id(), self.feature.id())
        other.selectByIds([row.id()])
        with patch.object(self.c.habitat_suitability_service, 'find_best_point') as ranking, \
             patch('geolichen.controllers.plugin_controller.ConfirmPointDialog') as dialog:
            self.c.find_habitat_suitability_point()
            with patch.object(self.c, '_prompt_candidate_use', return_value='use'):
                self.c._on_confirm_point_clicked(selected['point'], Qt.MouseButton.LeftButton)
        ranking.assert_not_called()
        dialog.assert_not_called()
        self.assertTrue(all('selezionata è cambiata' in error for error in self.errors))
        self.assertIsNone(self.c.confirmed_results_layer_id)

    def test_switching_record_cancels_pending_manual_capture(self):
        self.configure_source()
        self.c.start_manual_point_capture()
        self.assertEqual(self.c.active_manual_capture_mode, 'point')
        other, row = self.add_other_table()
        other.selectByIds([row.id()])
        self.assertIsNone(self.c.active_manual_capture_mode)
        self.assertIsNone(self.c.manual_point_tool)
        self.assertIs(self.c._valid_input_or_active_layer(), other)

    def test_preselected_table_added_after_configuration_is_detected(self):
        self.configure_source()
        self.records.removeSelection()
        other = QgsVectorLayer('None?field=taxon:string&field=localita:string', 'Preselected', 'memory')
        row = QgsFeature(other.fields())
        row.setAttributes(['Other species', 'Other locality'])
        other.dataProvider().addFeatures([row])
        other.selectByIds([next(other.getFeatures()).id()])
        QgsProject.instance().addMapLayer(other)
        self.assertIs(self.c._valid_input_or_active_layer(), other)

    def test_explicit_source_choice_with_zero_selection_is_honoured(self):
        self.configure_source()
        other, row = self.add_other_table()
        self.dock.cmbRecordLayer.setCurrentIndex(self.dock.cmbRecordLayer.findData(other.id()))
        self.assertIsNone(self.c._selected_feature())
        self.assertIs(self.c.input_layer, other)
        self.c._warn_record_selection()
        self.assertIn('Other records', self.errors[-1])
        self.assertIn('0 righe selezionate', self.errors[-1])
        self.assertEqual(self.records.selectedFeatureCount(), 1)

    def test_selection_switch_during_confirmation_does_not_write_any_record(self):
        from geolichen.gui.confirm_point_dialog import ConfirmPointDialog
        self.automatic_analysis(80)
        self.c.find_habitat_suitability_point()
        selected = self.c.current_suitability_result['selected_candidate']
        other, row = self.add_other_table()

        def switch_then_accept(dialog):
            dialog.cmbXField.setCurrentText('longitude')
            dialog.cmbYField.setCurrentText('latitude')
            def finish():
                other.selectByIds([row.id()])
                dialog.accept()
            QTimer.singleShot(0, finish)

        with patch.object(ConfirmPointDialog, 'show', switch_then_accept), \
             patch.object(self.c, '_prompt_candidate_use', return_value='use'):
            self.c._on_confirm_point_clicked(selected['point'], Qt.MouseButton.LeftButton)
        self.assertIsNone(self.c.confirmed_results_layer_id)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)
        self.assertEqual(other.getFeature(row.id())['longitude'], NULL)
        self.assertTrue(any('selezionata è cambiata' in error for error in self.errors))

    def test_project_roundtrip_restores_csv_mapping_and_selection_after_reload(self):
        from qgis.PyQt.QtCore import QUrl
        path = Path(TEMP) / 'roundtrip-records.csv'
        path.write_text('record_id,municipality,locality,scientific_name\n'
                        'CSV-1,Town,Locality,Species\n', encoding='utf-8')
        uri = QUrl.fromLocalFile(str(path))
        uri.setQuery('type=csv&geomType=none&detectTypes=yes')
        source = QgsVectorLayer(uri.toString(), 'CSV records', 'delimitedtext')
        self.assertTrue(source.isValid())
        QgsProject.instance().addMapLayer(source)
        source.selectByIds([next(source.getFeatures()).id()])
        from geolichen.gui.field_mapping_dialog import FieldMappingDialog
        with patch.object(FieldMappingDialog, 'exec', return_value=QDialog.DialogCode.Accepted):
            self.assertTrue(self.c._ensure_input_mapping())
        source_id = source.id()
        expected = self.c.mapping.to_dict()
        project_path = str(Path(TEMP) / 'roundtrip.qgz')
        QgsProject.instance().removeMapLayer(self.records.id())
        self.assertTrue(QgsProject.instance().write(project_path))
        self.plugin.unload()
        QgsProject.instance().clear()
        self.assertTrue(QgsProject.instance().read(project_path))
        source = QgsProject.instance().mapLayer(source_id)
        source.selectByIds([next(source.getFeatures()).id()])
        self.iface.activeLayer = lambda: None
        self.plugin.run()
        self.c = self.plugin.controller
        self.dock = self.plugin.dock
        self.assertEqual(self.c.mapping.to_dict(), expected)
        self.assertIs(self.c.input_layer, source)
        self.assertEqual(self.c._selected_feature()['record_id'], 'CSV-1')

    def test_cleanup_disconnects_other_table_selection_observers(self):
        self.configure_source()
        other, row = self.add_other_table()
        old_controller = self.c
        old_source_id = old_controller._requested_input_layer_id
        self.plugin.unload()
        self.plugin.run()
        self.c = self.plugin.controller
        self.dock = self.plugin.dock
        other.selectByIds([row.id()])
        self.assertEqual(old_controller._requested_input_layer_id, old_source_id)
        self.assertFalse(old_controller._record_selection_slots)
        self.assertIs(self.c._valid_input_or_active_layer(), other)

    def test_activating_preselected_other_table_cancels_pending_capture(self):
        self.configure_source()
        other, row = self.add_other_table()
        other.selectByIds([row.id()])
        self.dock.cmbRecordLayer.setCurrentIndex(self.dock.cmbRecordLayer.findData(self.records.id()))
        self.c.start_manual_point_capture()
        self.assertEqual(self.c.active_manual_capture_mode, 'point')
        self.iface.activeLayer = lambda: other
        self.iface.currentLayerChanged.emit(other)
        self.assertIsNone(self.c.active_manual_capture_mode)
        self.assertIs(self.c._valid_input_or_active_layer(), other)

    def test_reload_keeps_session_controls_in_memory(self):
        self.configure_source()
        self.dock.txtGeocoderUrl.setText('http://localhost:2322/api/')
        self.dock.txtManualBuffer.setText('1100')
        self.dock.cmbSuitabilityView.setCurrentText('Entrambi')
        self.dock.chkUseOsmTrails.setChecked(False)
        dem = self.add_dem('Selected DEM', 1234)
        self.plugin.unload()
        APP.processEvents()
        import geolichen
        self.plugin = geolichen.classFactory(self.iface)
        self.plugin.initGui()
        self.plugin.run()
        self.c = self.plugin.controller
        self.dock = self.plugin.dock
        self.assertEqual(self.dock.txtGeocoderUrl.text(), 'http://localhost:2322/api/')
        self.assertEqual(self.dock.txtManualBuffer.text(), '1100')
        self.assertEqual(self.dock.cmbSuitabilityView.currentText(), 'Entrambi')
        self.assertFalse(self.dock.chkUseOsmTrails.isChecked())
        self.assertEqual(self.dock.lstDemLayers.item(0).text(), dem.name())
        self.assertEqual(self.dock.lstDemLayers.item(0).checkState(), Qt.CheckState.Checked)
        self.assertIs(self.c.input_layer, self.records)

    def test_upgrade_recovers_controls_from_pending_legacy_dock(self):
        self.dock.txtGeocoderUrl.setText('http://localhost:2323/api/')
        self.dock.txtManualLineOffset.setText('400')
        self.plugin.unload()
        # Emulate a previous release whose unload did not save UI controls.
        del self.iface.window._geolichen_session_state
        import geolichen
        self.plugin = geolichen.classFactory(self.iface)
        self.plugin.initGui()
        self.plugin.run()
        self.c = self.plugin.controller
        self.dock = self.plugin.dock
        self.assertEqual(self.dock.txtGeocoderUrl.text(), 'http://localhost:2323/api/')
        self.assertEqual(self.dock.txtManualLineOffset.text(), '400')

    def add_second_record(self):
        row = QgsFeature(self.records.fields())
        row.setAttributes(['TEST-2', 'Other town', 'Other locality', 'Other species', None, None, None])
        self.records.dataProvider().addFeatures([row])
        return next(row for row in self.records.getFeatures() if row['record_id'] == 'TEST-2')

    def test_source_selection_remains_connected_with_result_layer_active(self):
        self.configure_source()
        result = QgsVectorLayer('Point?crs=EPSG:4326', 'Candidate results', 'memory')
        QgsProject.instance().addMapLayer(result)
        self.iface.activeLayer = lambda: result
        self.iface.currentLayerChanged.emit(result)
        second = self.add_second_record()
        self.records.selectByIds([second.id()])
        self.assertEqual(self.c.last_feature.id(), second.id())
        self.assertEqual(self.c._selected_feature()['record_id'], 'TEST-2')
        self.assertIs(self.c._valid_input_or_active_layer(), self.records)
        self.assertIn('1 riga selezionata — pronto', self.dock.lblOperationalStatus.text())
        self.assertIn(self.records.name(), self.dock.lblOperationalStatus.text())

    def test_mapping_restored_after_reload_with_result_active(self):
        self.configure_source()
        expected = self.c.mapping.to_dict()
        result = self.c._confirmed_results_layer()
        self.iface.activeLayer = lambda: result
        self.plugin.unload()
        self.plugin.run()
        self.c = self.plugin.controller
        self.dock = self.plugin.dock
        self.assertIs(self.c.input_layer, self.records)
        self.assertEqual(self.c.mapping.to_dict(), expected)
        self.assertEqual(self.c._selected_feature().id(), self.feature.id())
        self.assertIs(self.c._selection_layer, self.records)

    def test_initial_analysis_recovers_selected_table_behind_result_layer(self):
        self.c.mapping = None
        self.c.input_layer = None
        result = self.c._confirmed_results_layer()
        self.iface.activeLayer = lambda: result
        self.iface.currentLayerChanged.emit(result)
        self.assertIs(self.c._valid_input_or_active_layer(), self.records)
        from geolichen.gui.field_mapping_dialog import FieldMappingDialog
        with patch.object(FieldMappingDialog, 'exec', return_value=QDialog.DialogCode.Accepted):
            self.automatic_analysis(150)
        self.assertIs(self.c.input_layer, self.records)
        self.assertEqual(self.c._analysis_record_key, (self.records.id(), self.feature.id()))

    def test_deselection_and_multiple_selection_do_not_reuse_old_row(self):
        self.configure_source()
        self.assertIsNotNone(self.c._selected_feature())
        self.records.removeSelection()
        self.assertIsNone(self.c._selected_feature())
        second = self.add_second_record()
        ids = [self.feature.id(), second.id()]
        self.records.selectByIds(ids)
        self.assertIsNone(self.c._selected_feature())
        self.assertEqual(set(self.records.selectedFeatureIds()), set(ids))
        self.assertIn('2 righe selezionate', self.dock.lblOperationalStatus.text())

    def test_cancelled_or_invalid_configuration_keeps_previous_mapping(self):
        self.configure_source()
        previous = self.c.mapping.to_dict()
        from geolichen.gui.field_mapping_dialog import FieldMappingDialog
        from geolichen.models.input_mapping_model import InputMappingModel
        with patch.object(FieldMappingDialog, 'exec', return_value=QDialog.DialogCode.Rejected):
            self.assertFalse(self.c.configure_fields(self.records))
        with patch.object(FieldMappingDialog, 'exec', return_value=QDialog.DialogCode.Accepted), \
             patch.object(FieldMappingDialog, 'get_mapping', return_value=InputMappingModel()):
            self.assertFalse(self.c.configure_fields(self.records))
        self.assertEqual(self.c.mapping.to_dict(), previous)
        self.assertIs(self.c.input_layer, self.records)

    def test_removed_source_does_not_reuse_mapping_on_another_layer(self):
        self.configure_source()
        QgsProject.instance().removeMapLayer(self.records.id())
        self.iface.activeLayer = lambda: None
        self.assertIsNone(self.c._valid_input_or_active_layer())
        self.assertIsNone(self.c.mapping)

    def test_confirmation_inputs_work_with_details_collapsed(self):
        from geolichen.gui.confirm_point_dialog import ConfirmPointDialog
        dialog = ConfirmPointDialog(
            ['x', 'y', 'quota', 'uncertainty_m', 'model_radius_m'], 10.2, 46.05, 1200,
            defaults={'uncertainty': 200}, uncertainty_info={'model_radius_m': 120.1},
            ecological_point_wgs84=QgsPointXY(10.2, 46.05),
        )
        dialog.show()
        APP.processEvents()
        self.assertTrue(dialog.detailsSection.content.isHidden())
        self.assertTrue(dialog.txtX.isVisible())
        self.assertTrue(dialog.cmbModelRadiusField.isVisible())
        self.assertTrue(dialog.txtModelRadius.isVisible())
        self.assertEqual(dialog.txtModelRadius.text(), '120.1 m')
        self.assertTrue(dialog.txtModelRadius.isReadOnly())
        dialog.txtX.setText('10.3')
        before = dialog.values()
        dialog.detailsSection.header.click()
        self.assertTrue(dialog.txtModelRadius.isVisible())
        dialog.detailsSection.header.click()
        self.assertEqual(before, dialog.values())
        self.assertTrue(dialog.txtModelRadius.isVisible())
        dialog._validate_and_accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.values()['x'], '10.3')
        self.assertEqual(dialog.values()['model_radius'], 120.1)
        dialog.show()
        APP.processEvents()
        dialog.grab().save(str(Path(TEMP) / 'previews/confirmation-compact.png'))
        dialog.close()

    def test_automatic_then_manual_point_reanalyzes_geometry(self):
        self.automatic_analysis(150)
        documentary = QgsGeometry(self.c.original_locality_extent)
        old = QgsVectorLayer('Point?crs=EPSG:4326', 'Old candidate result', 'memory')
        QgsProject.instance().addMapLayer(old)
        old_id = old.id()
        self.c.current_suitability_result = {'layer': old, 'grid_step_m': 10}
        self.dock.txtManualBuffer.setText('1100')
        self.c.manual_point_feature = self.feature
        with patch.object(self.c.italic_service, 'fetch_profile', side_effect=lambda *a: copy.deepcopy(PROFILE)):
            self.c._on_manual_map_point_clicked(QgsPointXY(10.205, 46.052), Qt.MouseButton.LeftButton)
        self.assertFalse(self.errors, self.errors)
        self.assertEqual(self.c.search_geometry_mode, 'manual')
        self.assertEqual(self.c._get_suitability_grid_step(), 50)
        self.assertIsNone(self.c.current_suitability_result)
        self.assertIsNone(QgsProject.instance().mapLayer(old_id))
        self.assertTrue(documentary.equals(self.c.original_locality_extent))
        self.assertTrue(self.c.search_extent.equals(self.c.manual_search_extent))
        self.assertGreater(self.c._estimate_current_boundary_radius_m(), 1099)

    def test_manual_line_keeps_capture_and_ecological_workflow(self):
        self.automatic_analysis(150)
        self.c.manual_line_feature = self.feature
        self.c.manual_line_vertices = [QgsPointXY(10.2, 46.05), QgsPointXY(10.205, 46.052)]
        self.dock.txtManualLineOffset.setText('300')
        with patch.object(self.c.italic_service, 'fetch_profile', side_effect=lambda *a: copy.deepcopy(PROFILE)), \
             patch.object(self.c, 'find_habitat_suitability_point') as find:
            self.c._finish_manual_line_capture()
        self.assertFalse(self.errors, self.errors)
        self.assertEqual(self.c.search_geometry_mode, 'manual_line')
        self.assertEqual(self.c._get_suitability_grid_step(), 30)
        self.assertIn('Offset linea: ±300 m', self.dock.lblBufferGridInfo.text())
        self.assertIn('Passo griglia: 30 m', self.dock.lblBufferGridInfo.text())
        self.assertGreater(self.c.manual_line_length_m, 300)
        self.assertTrue(self.c.search_extent.equals(self.c.manual_search_extent))
        find.assert_called_once()
        boundary = QgsGeometry(self.c.search_extent)
        self.c.start_manual_point_capture()
        self.assertEqual(self.c.active_manual_capture_mode, 'point')
        self.c.start_manual_point_capture()
        self.assertIsNone(self.c.active_manual_capture_mode)
        self.assertTrue(boundary.equals(self.c.search_extent))

    def test_dictionary_italian_english_and_soil_ph(self):
        from geolichen.services.lithology_classifier_service import LithologyClassifierService
        classifier = LithologyClassifierService()
        for text, expected in [('calcare', 'calcareo'), ('limestone', 'calcareo'),
                               ('granite', 'siliceo'), ('micascisto', 'siliceo'),
                               ('marble', 'calcareo'), ('quartzite', 'siliceo'),
                               ('acidic rocks', 'siliceo'), ('substrato basico', 'calcareo'),
                               ('limestone and sandstone', 'misto')]:
            self.assertEqual(classifier.classify(text), expected)
            self.assertEqual(self.c.habitat_suitability_service._normalize_rock_type(text), expected)
        self.assertEqual(self.c.soil_service.normalize_soil_ph('alkaline'), 'basic')
        self.assertEqual(self.c.soil_service.normalize_soil_ph('acidic'), 'acid')
        self.assertEqual(self.c.soil_service.normalize_soil_ph('neutral'), 'neutral')
        self.assertEqual(self.c.soil_service.parse_numeric_ph('pH 5,2'), 5.2)
        feature = QgsFeature()
        layer = QgsVectorLayer('Polygon?crs=EPSG:4326&field=PH_H2O:double', 'Soil fixture', 'memory')
        feature.setFields(layer.fields())
        feature.setAttributes([5.2])
        self.assertEqual(self.c.soil_service.extract_numeric_ph_from_feature(feature)[0], 5.2)

    def test_layer_fields_detected_in_english(self):
        geology = QgsVectorLayer('Polygon?crs=EPSG:4326&field=LITHOLOGY:string', 'Geology fixture', 'memory')
        soil = QgsVectorLayer('Polygon?crs=EPSG:4326&field=PH_H2O:double', 'Soil fixture', 'memory')
        QgsProject.instance().addMapLayers([geology, soil])
        self.dock.cmbGeologyLayer.setCurrentText(geology.name())
        self.dock.cmbSoilLayer.setCurrentText(soil.name())
        self.assertEqual(self.dock.cmbGeologyField.currentText(), 'LITHOLOGY')
        self.assertEqual(self.dock.cmbSoilField.currentText(), 'PH_H2O')
        for layer, value in ((geology, 'limestone'), (soil, 5.2)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([value])
            feature.setGeometry(metric_buffer(200))
            layer.dataProvider().addFeatures([feature])
            layer.updateExtents()
        environment = self.c.habitat_suitability_service._build_env_for_point(
            QgsPointXY(10.2, 46.05), geology_layer=geology, geology_field='LITHOLOGY',
            soil_layer=soil, soil_field='PH_H2O',
        )
        self.assertEqual(environment['rock_type'], 'calcareo')
        self.assertEqual(environment['soil_ph_num'], 5.2)
        self.assertEqual(environment['soil_ph_class'], 'acid')
        self.c.geology_group_service.ensure_group_field(geology)
        self.assertEqual(next(geology.getFeatures())['GRUPPO_LITO'], 'calcareo')

    def candidate_fixture(self, group, profile=None, **layers):
        service = self.c.habitat_suitability_service
        result = service.find_best_point(
            metric_buffer(80), dict(profile or {}, substrate_group=group),
            _candidate_points=[QgsPointXY(10.2, 46.05)],
            _adaptive_refinement=False, create_layer=True, **layers,
        )
        return result, result['features'][0]['env']

    def test_real_scoring_pipeline_preserves_missing_evidence_and_exports_coverage(self):
        result, env = self.candidate_fixture('rock', {'habitat': ['aperto', 'alpino', 'rupicolo']})
        self.assertIsNone(env['ph_score'])
        self.assertIsNone(env['environmental_ph_score'])
        self.assertIsNone(env['environmental_tree_score'])
        self.assertIsNone(env['environmental_habitat_score'])
        self.assertEqual(env['environmental_available_weight'], 0.0)
        self.assertEqual(env['environmental_score'], 50.0)
        feature = next(result['layer'].getFeatures())
        self.assertEqual(feature['env_cov'], 0.0)
        self.assertEqual(feature['env_neut'], 50.0)
        self.assertEqual(feature['env_macro'], env['environmental_score'])
        self.assertAlmostEqual(feature['final_score'], env['final_score'])

    def test_real_numeric_soil_ph_only_scores_ground_records(self):
        soil = QgsVectorLayer('Polygon?crs=EPSG:4326&field=PH_H2O:double', 'Soil evidence', 'memory')
        feature = QgsFeature(soil.fields())
        feature.setAttributes([5.2])
        feature.setGeometry(metric_buffer(200))
        soil.dataProvider().addFeatures([feature])
        soil.updateExtents()
        QgsProject.instance().addMapLayer(soil)
        profile = {'ecology_raw': {'ph_of_the_substrata_min': 1, 'ph_of_the_substrata_max': 2}}
        for group in ('soil', 'rock', 'epiphyte', 'lignicolous'):
            with self.subTest(group=group):
                result, env = self.candidate_fixture(group, profile, soil_layer=soil, soil_field='PH_H2O')
                self.assertEqual(env['soil_ph_num'], 5.2)
                if group == 'soil':
                    self.assertEqual(env['environmental_ph_score'], 85.0)
                    self.assertEqual(env['environmental_sources']['ph'], 'soil_ph_numeric')
                else:
                    self.assertIsNone(env['environmental_ph_score'])

    def test_real_forest_habitat_evidence_reaches_candidate_score(self):
        trees = QgsVectorLayer('Polygon?crs=EPSG:4326&field=forest:string', 'Forest evidence', 'memory')
        feature = QgsFeature(trees.fields())
        feature.setAttributes(['querceto'])
        feature.setGeometry(metric_buffer(200))
        trees.dataProvider().addFeatures([feature])
        trees.updateExtents()
        QgsProject.instance().addMapLayer(trees)
        _, env = self.candidate_fixture('soil', {'habitat': ['bosco']},
                                        trees_layer=trees, trees_field='forest')
        self.assertEqual(env['environmental_habitat_score'], 100.0)
        self.assertGreater(env['environmental_score'], 50.0)
        self.assertEqual(env['constraints']['habitat'], ['bosco'])
        self.assertEqual(env['ecological_evidence']['habitat']['source'], 'candidate_habitat')

    def test_official_scoring_error_cannot_fall_back_to_legacy_ranking(self):
        with patch.object(self.c.habitat_suitability_service.scoring_model, 'apply_to_env',
                          side_effect=ValueError('Synthetic scoring failure')):
            with self.assertRaisesRegex(RuntimeError, 'score ufficiale'):
                self.candidate_fixture('rock')

    def test_real_candidate_pipeline_uses_policy_and_global_heatmap(self):
        self.automatic_analysis(80)
        self.dock.cmbSuitabilityView.setCurrentText('Entrambi')
        self.c.find_habitat_suitability_point()
        self.assertFalse(self.errors, self.errors)
        result = self.c.current_suitability_result
        self.assertIsNotNone(result)
        self.assertEqual(result['initial_grid_step_m'], 10)
        self.assertGreater(result['points_count'], 0)
        self.assertIsInstance(result['heatmap_layer'], QgsRasterLayer)
        self.assertEqual(float(result['heatmap_layer'].customProperty('geolichen/base_grid_step_m')), 10)
        self.assertTrue(self.c.search_extent.equals(result['search_extent']))

    def test_manual_ranking_uses_new_center_not_previous_geocoder(self):
        from geolichen.services.habitat_suitability_service import HabitatSuitabilityService
        self.automatic_analysis(80)
        center = QgsPointXY(10.25, 46.08)
        self.c.manual_search_center_wgs84 = center
        with patch.object(self.c.italic_service, 'fetch_profile', side_effect=lambda *a: copy.deepcopy(PROFILE)):
            self.c._analyze_manual_boundary(self.feature, metric_buffer(120, center), 120)
        original_find = HabitatSuitabilityService.find_best_point
        with patch.object(HabitatSuitabilityService, 'find_best_point', autospec=True, side_effect=original_find) as find, \
             patch.object(self.c.context_engine, 'infer_context', wraps=self.c.context_engine.infer_context) as context:
            self.c.find_habitat_suitability_point()
        self.assertFalse(self.errors, self.errors)
        self.assertIsNone(context.call_args.kwargs['geocoding_result'])
        point = find.call_args_list[0].kwargs['context_point']
        self.assertAlmostEqual(point.x(), center.x())
        self.assertAlmostEqual(point.y(), center.y())
        self.assertEqual(find.call_args_list[0].kwargs['grid_step_m'], 10)

    def test_ecological_candidate_confirmation_still_writes_result(self):
        from geolichen.gui.confirm_point_dialog import ConfirmPointDialog
        self.records.dataProvider().addAttributes([
            QgsField('uncertainty_m', FieldType.Double),
            QgsField('model_radius_m', FieldType.Double),
        ])
        self.records.updateFields()
        self.feature = self.records.getFeature(self.feature.id())
        self.automatic_analysis(80)
        self.c.find_habitat_suitability_point()
        self.assertFalse(self.errors, self.errors)
        selected = self.c.current_suitability_result['selected_candidate']
        shown_radius = []

        def accept_dialog(dialog):
            self.assertIs(dialog.target_layer, self.records)
            dialog.cmbXField.setCurrentText('longitude')
            dialog.cmbYField.setCurrentText('latitude')
            dialog.cmbDemField.setCurrentText('quota_dem')
            dialog.cmbUncertaintyField.setCurrentText('uncertainty_m')
            dialog.cmbModelRadiusField.setCurrentText('model_radius_m')
            shown_radius.append(dialog.values()['model_radius'])
            self.assertEqual(dialog.txtModelRadius.text(), f'{shown_radius[-1]:.1f} m')
            QTimer.singleShot(0, dialog.accept)

        with patch.object(ConfirmPointDialog, 'show', accept_dialog), \
             patch.object(self.c, '_prompt_candidate_use', return_value='use'):
            self.c._on_confirm_point_clicked(selected['point'], Qt.MouseButton.LeftButton)
        self.assertFalse(self.errors, self.errors)
        result = self.c._confirmed_results_layer()
        self.assertEqual(result.featureCount(), 1)
        row = next(result.getFeatures())
        self.assertNotEqual(row['gss'], NULL)
        self.assertGreater(row['rank'], 0)
        saved = next(self.records.getFeatures())
        self.assertAlmostEqual(saved['longitude'], selected['point'].x(), places=5)
        self.assertAlmostEqual(saved['latitude'], selected['point'].y(), places=5)
        self.assertGreater(shown_radius[0], 0)
        self.assertAlmostEqual(saved['model_radius_m'], shown_radius[0])
        self.assertAlmostEqual(row['model_r_m'], shown_radius[0])

    def test_heatmap_spacing_and_clipping_for_all_steps(self):
        service = self.c.habitat_suitability_service
        for step in (10, 30, 50, 100):
            with self.subTest(step=step):
                boundary = metric_buffer(step * 3)
                points = service._generate_grid_points(boundary, step)
                features = [{'point': point, 'score': 40 + i % 50, 'env': {}}
                            for i, point in enumerate(points)]
                raster = service._create_heatmap_layer(features, grid_step_m=step, search_extent=boundary)
                self.assertIsInstance(raster, QgsRasterLayer)
                self.assertEqual(float(raster.customProperty('geolichen/base_grid_step_m')), step)
                self.assertGreaterEqual(float(raster.customProperty('geolichen/support_radius_m')), step * 3)
                dataset = gdal.Open(raster.source())
                array = dataset.ReadAsArray()
                self.assertGreater(np.count_nonzero(array != -9999), 0)
                self.assertGreater(np.count_nonzero(array == -9999), 0)
                geometry = QgsGeometry(boundary)
                geometry.transform(QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'), raster.crs(), QgsProject.instance()))
                transform = dataset.GetGeoTransform()
                for row in range(array.shape[0]):
                    for col in range(array.shape[1]):
                        point = QgsPointXY(transform[0] + (col + 0.5) * transform[1],
                                           transform[3] + (row + 0.5) * transform[5])
                        inside = geometry.contains(QgsGeometry.fromPointXY(point))
                        self.assertEqual(bool(array[row, col] != -9999), inside)
                dataset = None

    def test_heatmap_zoom_only_changes_rendering(self):
        from qgis.PyQt.QtCore import QSize
        from qgis.PyQt.QtGui import QColor
        from qgis.core import QgsMapSettings, QgsMapRendererParallelJob, QgsRectangle
        self.automatic_analysis(80)
        self.dock.cmbSuitabilityView.setCurrentText('Entrambi')
        self.c.find_habitat_suitability_point()
        result = self.c.current_suitability_result
        # Uniform ecological fixtures can render identically with either filter.
        # Use a non-uniform display fixture alongside the real ranking result.
        service = self.c.habitat_suitability_service
        boundary = metric_buffer(120)
        points = service._generate_grid_points(boundary, 30)
        samples = [{'point': point, 'score': 5 + (index % 7) * 15, 'env': {}}
                   for index, point in enumerate(points)]
        with patch('tempfile.gettempdir', return_value=TEMP):
            raster = service._create_heatmap_layer(samples, grid_step_m=30, search_extent=boundary)
        path = Path(raster.source())
        before_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        before_rank = [(row['rank'], row['score'], row['point'].x(), row['point'].y())
                       for row in result['features']]
        def uncertainty_values():
            return {key: value for key, value in result['uncertainty'].items()
                    if isinstance(value, (str, int, float, bool, type(None)))}
        before_uncertainty = uncertainty_values()
        before_step = self.dock.txtSuitabilityGridStep.text()
        pixels = (raster.width(), raster.height(), raster.rasterUnitsPerPixelX())
        resampling = raster.resampleFilter()
        self.assertEqual(resampling.zoomedInResampler().type(), 'bilinear')
        self.assertEqual(resampling.zoomedOutResampler().type(), 'bilinear')

        def render(factor):
            settings = QgsMapSettings()
            settings.setLayers([raster])
            settings.setDestinationCrs(raster.crs())
            extent = QgsRectangle(raster.extent())
            extent.scale(factor)
            settings.setExtent(extent)
            settings.setOutputSize(QSize(320, 320))
            settings.setBackgroundColor(QColor(255, 255, 255, 0))
            job = QgsMapRendererParallelJob(settings)
            job.start()
            job.waitForFinished()
            self.assertFalse(job.errors())
            image = job.renderedImage()
            self.assertFalse(image.isNull())
            return image

        # Compare the exact same close-up with and without display smoothing.
        resampling.setZoomedInResampler(None)
        nearest = render(0.20)
        self.c.habitat_suitability_service.configure_heatmap_display(raster)
        with patch.object(self.c.habitat_suitability_service, 'find_best_point') as ranking, \
             patch.object(self.c.ecology_engine, 'compute_score') as scoring, \
             patch.object(self.c.habitat_suitability_service, '_create_heatmap_layer') as rebuilding:
            smooth = render(0.20)
            render(1.0)
            render(20.0)
            for factor in (0.2, 1.0, 20.0):
                extent = QgsRectangle(self.iface.canvas.extent())
                extent.scale(factor)
                self.iface.canvas.setExtent(extent)
                APP.processEvents()
            ranking.assert_not_called()
            scoring.assert_not_called()
            rebuilding.assert_not_called()
        self.assertNotEqual(nearest, smooth)
        self.assertEqual(before_hash, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(pixels, (raster.width(), raster.height(), raster.rasterUnitsPerPixelX()))
        self.assertEqual(before_step, self.dock.txtSuitabilityGridStep.text())
        self.assertEqual(before_rank, [(row['rank'], row['score'], row['point'].x(), row['point'].y())
                                      for row in result['features']])
        self.assertEqual(before_uncertainty, uncertainty_values())
        output = Path(TEMP) / 'previews'
        output.mkdir(exist_ok=True)
        nearest.save(str(output / 'heatmap-zoom-before.png'))
        smooth.save(str(output / 'heatmap-zoom-after.png'))

    def test_existing_heatmap_gets_display_filter_without_changing_dem(self):
        self.automatic_analysis(80)
        self.dock.cmbSuitabilityView.setCurrentText('Entrambi')
        self.c.find_habitat_suitability_point()
        raster = self.c.current_suitability_result['heatmap_layer']
        raster.resampleFilter().setZoomedInResampler(None)
        dem = self.add_dem('Untouched DEM', 1200)
        self.assertIsNone(dem.resampleFilter().zoomedInResampler())
        self.c._refresh_layers()
        self.assertEqual(raster.resampleFilter().zoomedInResampler().type(), 'bilinear')
        self.assertIsNone(dem.resampleFilter().zoomedInResampler())

    def add_dem(self, name, value):
        from geolichen.services._shared_geo_utils import local_metric_crs
        wgs = QgsCoordinateReferenceSystem('EPSG:4326')
        metric = local_metric_crs(QgsPointXY(10.2, 46.05))
        center = QgsGeometry.fromPointXY(QgsPointXY(10.2, 46.05))
        center.transform(QgsCoordinateTransform(wgs, metric, QgsProject.instance()))
        point = center.asPoint()
        path = Path(TEMP) / (name + '.tif')
        dataset = gdal.GetDriverByName('GTiff').Create(str(path), 100, 100, 1, gdal.GDT_Float32)
        dataset.SetGeoTransform((point.x() - 1000, 20, 0, point.y() + 1000, 0, -20))
        dataset.SetProjection(metric.toWkt())
        dataset.GetRasterBand(1).SetNoDataValue(-9999)
        dataset.GetRasterBand(1).Fill(value)
        dataset = None
        raster = QgsRasterLayer(str(path), name)
        self.assertTrue(raster.isValid())
        QgsProject.instance().addMapLayer(raster)
        for i in range(self.dock.lstDemLayers.count()):
            self.dock.lstDemLayers.item(i).setCheckState(Qt.CheckState.Checked)
        return raster

    def test_centroid_finalizes_without_ecology_with_dem_fallback(self):
        self.bind_geometry(metric_buffer(250))
        self.add_dem('DEM_1_NoData', -9999)
        self.add_dem('DEM_2_Valid', 1234)
        with patch('geolichen.gui.centroid_result_dialog.CentroidResultDialog.exec', return_value=QDialog.DialogCode.Accepted), \
             patch.object(self.c.habitat_suitability_service, 'find_best_point') as ranking, \
             patch.object(self.c.ecology_engine, 'compute_score') as scoring, \
             patch.object(self.c.italic_service, 'fetch_profile') as italic:
            self.c.finish_with_locality_centroid()
        self.assertFalse(self.errors, self.errors)
        ranking.assert_not_called()
        scoring.assert_not_called()
        italic.assert_not_called()
        result = self.c.current_centroid_result
        self.assertAlmostEqual(result['longitude'], 10.2, places=7)
        self.assertAlmostEqual(result['latitude'], 46.05, places=7)
        self.assertEqual(result['altitude_m'], 1234)
        self.assertFalse(result['ecology_used'])
        stored = next(self.records.getFeatures())
        self.assertAlmostEqual(stored['longitude'], result['longitude'])
        self.assertAlmostEqual(stored['latitude'], result['latitude'])
        self.assertEqual(stored['quota_dem'], 1234)
        final = self.c._confirmed_results_layer()
        self.assertEqual(final.featureCount(), 1)
        row = next(final.getFeatures())
        self.assertEqual(row['pipeline'], 'locality_centroid')
        self.assertEqual(row['gss'], NULL)
        self.assertEqual(row['model_r_m'], NULL)
        self.assertEqual(row['uncert_m'], NULL)
        self.assertIn('Analisi conclusa al centroide', self.dock.lblOperationalStatus.text())

    def test_centroid_missing_dem_is_null_and_cancel_is_safe(self):
        self.bind_geometry(metric_buffer(150))
        with patch('geolichen.gui.centroid_result_dialog.CentroidResultDialog.exec', return_value=QDialog.DialogCode.Rejected):
            self.c.finish_with_locality_centroid()
        self.assertIsNone(self.c.current_centroid_result)
        self.assertIsNone(self.c.confirmed_results_layer_id)
        with patch('geolichen.gui.centroid_result_dialog.CentroidResultDialog.exec', return_value=QDialog.DialogCode.Accepted):
            self.c.finish_with_locality_centroid()
        self.assertFalse(self.errors, self.errors)
        self.assertIsNone(self.c.current_centroid_result['altitude_m'])
        final = next(self.c._confirmed_results_layer().getFeatures())
        self.assertEqual(final['altitude_m'], NULL)

    def test_centroid_rejects_area_from_another_record(self):
        self.bind_geometry(metric_buffer(150))
        self.c._analysis_record_key = (self.records.id(), self.feature.id() + 1)
        self.c.finish_with_locality_centroid()
        self.assertTrue(self.errors)
        self.assertIsNone(self.c.current_centroid_result)

    def test_confirmed_centroid_can_be_copied_without_reanalysis(self):
        self.bind_geometry(metric_buffer(150))
        with patch('geolichen.gui.centroid_result_dialog.CentroidResultDialog.exec', return_value=QDialog.DialogCode.Accepted):
            self.c.finish_with_locality_centroid()
        target = QgsFeature(self.records.fields())
        target.setAttributes(['TEST-2', 'Test town', 'Test locality', 'Test species', None, None, None])
        self.records.dataProvider().addFeatures([target])
        features = list(self.records.getFeatures())
        target = next(feature for feature in features if feature['record_id'] == 'TEST-2')
        self.records.selectByIds([target.id()])
        with patch('geolichen.controllers.plugin_controller.ReuseConfirmedPointDialog.exec', return_value=QDialog.DialogCode.Accepted), \
             patch('geolichen.controllers.plugin_controller.CopyPointTargetsDialog.exec', return_value=QDialog.DialogCode.Accepted), \
             patch('geolichen.controllers.plugin_controller.QMessageBox.question', return_value=16384), \
             patch.object(self.c.italic_service, 'fetch_profile') as italic:
            self.c.reuse_confirmed_point()
        self.assertFalse(self.errors, self.errors)
        italic.assert_not_called()
        saved = self.records.getFeature(target.id())
        self.assertAlmostEqual(saved['longitude'], 10.2, places=7)
        self.assertAlmostEqual(saved['latitude'], 46.05, places=7)
        self.assertEqual(self.c._confirmed_results_layer().featureCount(), 2)

    def test_confirmation_creates_missing_numeric_columns_and_keeps_old_names(self):
        from geolichen.gui.confirm_point_dialog import ConfirmPointDialog
        from geolichen.services.confirmation_fields_service import ConfirmationFieldsService
        dialog = ConfirmPointDialog(self.records.fields().names(), 10.2, 46.05, 1234,
                                    defaults={'uncertainty': 250},
                                    uncertainty_info={'model_radius_m': 87.5}, target_layer=self.records)
        dialog.show()
        APP.processEvents()
        self.assertTrue(dialog.btnCreateFields.isVisible())
        self.assertEqual(dialog.cmbXField.currentText(), 'longitude')
        self.assertEqual(dialog.cmbYField.currentText(), 'latitude')
        dialog.grab().save(str(Path(TEMP) / 'previews/confirmation-missing-columns-15.6.6.png'))
        dialog.btnCreateFields.click()
        self.assertFalse(dialog.btnCreateFields.isVisible())
        self.assertEqual(dialog.values()['uncertainty_field'], 'inc_loc_m')
        self.assertEqual(dialog.values()['model_radius_field'], 'inc_geo_m')
        self.assertEqual(self.records.fields().count(), 9)
        for name in ('inc_loc_m', 'inc_geo_m'):
            self.assertEqual(self.records.fields().field(name).type(), FieldType.Double)
        self.c._write_confirmed_point_to_feature(self.records, self.feature, dialog.values(), QgsPointXY(10.2, 46.05))
        saved = self.records.getFeature(self.feature.id())
        self.assertEqual(saved['inc_loc_m'], 250)
        self.assertEqual(saved['inc_geo_m'], 87.5)
        self.assertEqual(saved['latitude'], 46.05)
        self.assertEqual(saved['municipality'], 'Test town')
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        self.assertIn('Incertezza località', labels)
        self.assertIn('Incertezza GeoLichen', labels)
        count = self.records.fields().count()
        mapping, created = ConfirmationFieldsService.ensure_fields(self.records, dialog.values())
        self.assertEqual(created, [])
        self.assertEqual(count, self.records.fields().count())
        dialog.grab().save(str(Path(TEMP) / 'previews/confirmation-15.6.6.png'))
        dialog.close()
        legacy = QgsVectorLayer('None', 'Legacy fields', 'memory')
        legacy.dataProvider().addAttributes([QgsField(name, FieldType.Double) for name in
            ('coordinata X', 'coordinata Y', 'Quota', 'incertezza GBIF (m)', 'incertezza R55 S70')])
        legacy.updateFields()
        mapping = ConfirmationFieldsService.resolve(legacy)
        self.assertEqual(mapping['uncertainty_field'], 'incertezza GBIF (m)')
        self.assertEqual(mapping['model_radius_field'], 'incertezza R55 S70')
        _, created = ConfirmationFieldsService.ensure_fields(legacy, mapping)
        self.assertEqual(created, [])

    def test_new_columns_preserve_pending_edits_and_are_undoable(self):
        from geolichen.services.confirmation_fields_service import ConfirmationFieldsService
        self.records.startEditing()
        self.records.changeAttributeValue(self.feature.id(), 0, 'pending-user-edit')
        mapping, created = ConfirmationFieldsService.ensure_fields(
            self.records, ConfirmationFieldsService.resolve(self.records))
        self.assertEqual(len(created), 2)
        self.assertTrue(self.records.isEditable())
        self.assertEqual(self.records.getFeature(self.feature.id())['record_id'], 'pending-user-edit')
        self.records.undoStack().undo()
        self.assertEqual(self.records.fields().indexOf('inc_loc_m'), -1)
        self.assertEqual(self.records.getFeature(self.feature.id())['record_id'], 'pending-user-edit')
        self.records.rollBack()

    def test_readonly_table_field_creation_reports_actionable_error(self):
        from geolichen.services.confirmation_fields_service import ConfirmationFieldsService
        path = Path(TEMP) / 'readonly-records.csv'
        path.write_text('record_id,locality,scientific_name\n1,Here,Test\n')
        layer = QgsVectorLayer(path.as_uri() + '?type=csv&geomType=none', 'CSV', 'delimitedtext')
        self.assertTrue(layer.isValid())
        with self.assertRaisesRegex(ValueError, 'GeoPackage'):
            ConfirmationFieldsService.ensure_fields(layer, {})
        self.assertEqual(layer.fields().count(), 3)

    def _copy_fixture(self):
        from geolichen.services.confirmation_fields_service import ConfirmationFieldsService
        mapping, _ = ConfirmationFieldsService.ensure_fields(
            self.records, ConfirmationFieldsService.resolve(self.records))
        values = dict(mapping, x=10.2, y=46.05, dem=1234.5, uncertainty=250, model_radius=87.5)
        self.c._write_confirmed_point_to_feature(self.records, self.feature, values, QgsPointXY(10.2, 46.05))
        features = []
        for record_id, locality, municipality in (
                ('TARGET-1', 'Test locality', 'Test town'),
                ('TARGET-2', ' TEST   LOCALITY ', 'Test town'),
                ('NOT-CHOSEN', 'Test locality', 'Test town'),
                ('OTHER-LOCALITY', 'Elsewhere', 'Test town'),
                ('OTHER-TOWN', 'Test locality', 'Elsewhere')):
            feature = QgsFeature(self.records.fields())
            feature['record_id'] = record_id
            feature['locality'] = locality
            feature['municipality'] = municipality
            feature['scientific_name'] = 'Test species'
            features.append(feature)
        ok, _ = self.records.dataProvider().addFeatures(features)
        self.assertTrue(ok)
        return mapping, {row['record_id']: row.id() for row in self.records.getFeatures()}

    def test_copy_targets_filter_and_manual_selection_do_not_select_similar_rows(self):
        from geolichen.gui.copy_point_targets_dialog import CopyPointTargetsDialog
        from qgis.PyQt.QtCore import QItemSelectionModel
        mapping, ids = self._copy_fixture()
        source = self.c._confirmed_result_rows()[1][0]
        rows = [self.c._copy_target_row(row) for row in self.records.getFeatures() if row.id() != self.feature.id()]
        dialog = CopyPointTargetsDialog(self.records, rows, source, mapping)
        self.assertEqual(dialog.selected_ids(), [])
        self.assertEqual(sum(not dialog.table.isRowHidden(i) for i in range(len(rows))), 3)
        dialog.table.selectAll()
        self.assertEqual(set(dialog.selected_ids()), {ids['TARGET-1'], ids['TARGET-2'], ids['NOT-CHOSEN']})
        dialog.search.setText('TARGET-1')
        self.assertEqual(dialog.selected_ids(), [ids['TARGET-1']])
        dialog.search.clear()
        self.assertEqual(dialog.selected_ids(), [ids['TARGET-1']])
        dialog.chkSameLocality.setChecked(False)
        index = next(i for i, row in enumerate(rows) if row['fid'] == ids['OTHER-TOWN'])
        dialog.table.selectionModel().select(dialog.table.model().index(index, 0),
                                             QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.assertIn(ids['OTHER-TOWN'], dialog.selected_ids())
        dialog.chkSameLocality.setChecked(True)
        self.assertEqual(dialog.selected_ids(), [ids['TARGET-1']])
        dialog.show()
        APP.processEvents()
        dialog.grab().save(str(Path(TEMP) / 'previews/copy-targets-15.6.6.png'))
        dialog.close()

    def test_copy_multiple_rows_only_writes_explicit_destinations_without_analysis(self):
        mapping, ids = self._copy_fixture()
        self.records.selectByIds([ids['TARGET-1'], ids['TARGET-2']])
        before_selection = set(self.records.selectedFeatureIds())
        before_analysis = self.c.current_suitability_result
        with patch('geolichen.controllers.plugin_controller.ReuseConfirmedPointDialog.exec', return_value=QDialog.DialogCode.Accepted), \
             patch('geolichen.controllers.plugin_controller.CopyPointTargetsDialog.exec', return_value=QDialog.DialogCode.Accepted), \
             patch('geolichen.controllers.plugin_controller.QMessageBox.question', return_value=16384) as question, \
             patch.object(self.c.italic_service, 'fetch_profile') as italic, \
             patch.object(self.c.habitat_suitability_service, 'find_best_point') as analysis:
            self.c.reuse_confirmed_point()
        self.assertFalse(self.errors, self.errors)
        italic.assert_not_called()
        analysis.assert_not_called()
        self.assertIn('2 righe', question.call_args.args[2])
        self.assertIs(self.c.current_suitability_result, before_analysis)
        self.assertEqual(set(self.records.selectedFeatureIds()), before_selection)
        for name in ('TARGET-1', 'TARGET-2'):
            row = self.records.getFeature(ids[name])
            self.assertEqual(row[mapping['x_field']], 10.2)
            self.assertEqual(row[mapping['dem_field']], 1234.5)
            self.assertEqual(row[mapping['uncertainty_field']], 250)
            self.assertEqual(row[mapping['model_radius_field']], 87.5)
        for name in ('NOT-CHOSEN', 'OTHER-LOCALITY', 'OTHER-TOWN'):
            self.assertEqual(self.records.getFeature(ids[name])['longitude'], NULL)
        self.assertEqual(self.c._confirmed_results_layer().featureCount(), 3)

    def test_copy_cancel_and_changed_destination_do_not_write(self):
        mapping, ids = self._copy_fixture()
        self.records.selectByIds([ids['TARGET-1'], ids['TARGET-2']])
        source_dialog = 'geolichen.controllers.plugin_controller.ReuseConfirmedPointDialog.exec'
        target_dialog = 'geolichen.controllers.plugin_controller.CopyPointTargetsDialog.exec'
        with patch(source_dialog, return_value=QDialog.DialogCode.Accepted), \
             patch(target_dialog, return_value=QDialog.DialogCode.Rejected):
            self.c.reuse_confirmed_point()
        self.assertEqual(self.records.getFeature(ids['TARGET-1'])['longitude'], NULL)
        def change_destination(*args):
            self.records.dataProvider().changeAttributeValues({ids['TARGET-2']: {
                self.records.fields().indexOf('locality'): 'Changed after preview'}})
            return 16384
        with patch(source_dialog, return_value=QDialog.DialogCode.Accepted), \
             patch(target_dialog, return_value=QDialog.DialogCode.Accepted), \
             patch('geolichen.controllers.plugin_controller.QMessageBox.question', side_effect=change_destination):
            self.c.reuse_confirmed_point()
        self.assertIn('cambiate', self.errors[-1])
        self.assertEqual(self.records.getFeature(ids['TARGET-1'])['longitude'], NULL)
        self.assertEqual(self.c._confirmed_results_layer().featureCount(), 1)

    def test_copy_batch_write_failure_rolls_back_all_target_rows_only(self):
        mapping, ids = self._copy_fixture()
        self.records.startEditing()
        self.records.changeAttributeValue(self.feature.id(), 0, 'pending-edit')
        original = self.records.changeAttributeValue
        def fail_second(fid, *args, **kwargs):
            return False if fid == ids['TARGET-2'] else original(fid, *args, **kwargs)
        values = dict(mapping, x=10.4, y=46.2, dem=1500, uncertainty=200, model_radius=80)
        with patch.object(self.records, 'changeAttributeValue', side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, 'Impossibile aggiornare'):
                self.c._write_confirmed_points_to_features(self.records,
                    [self.records.getFeature(ids['TARGET-1']), self.records.getFeature(ids['TARGET-2'])], values, QgsPointXY(10.4, 46.2))
        self.assertEqual(self.records.getFeature(ids['TARGET-1'])['longitude'], NULL)
        self.assertEqual(self.records.getFeature(self.feature.id())['record_id'], 'pending-edit')
        self.assertTrue(self.records.isEditable())
        self.assertEqual(self.c._confirmed_results_layer().featureCount(), 1)
        self.records.rollBack()

    def test_field_autodetection_does_not_match_y_inside_municipality(self):
        from geolichen.gui.confirm_point_dialog import ConfirmPointDialog
        dialog = ConfirmPointDialog(['record_id', 'municipality', 'locality', 'scientific_name'], 10.2, 46.05)
        self.assertEqual(dialog.cmbYField.currentText(), '')
        self.assertEqual(dialog.cmbXField.currentText(), '')
        dialog.close()

    def test_created_columns_persist_in_geopackage_after_reopen(self):
        from qgis.core import QgsVectorFileWriter
        from geolichen.services.confirmation_fields_service import ConfirmationFieldsService
        path = str(Path(TEMP) / 'confirmation-columns.gpkg')
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = 'records'
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            self.records, path, QgsProject.instance().transformContext(), options)
        self.assertEqual(result[0], QgsVectorFileWriter.WriterError.NoError, result)
        layer = QgsVectorLayer(path + '|layername=records', 'Saved records', 'ogr')
        self.assertTrue(layer.isValid())
        mapping, created = ConfirmationFieldsService.ensure_fields(layer, ConfirmationFieldsService.resolve(layer))
        self.assertEqual(created, ['inc_loc_m', 'inc_geo_m'])
        feature = next(layer.getFeatures())
        values = dict(mapping, x=10.2, y=46.05, dem=1234.5, uncertainty=250, model_radius=87.5)
        self.c._write_confirmed_point_to_feature(layer, feature, values)
        reopened = QgsVectorLayer(path + '|layername=records', 'Reopened', 'ogr')
        row = next(reopened.getFeatures())
        self.assertEqual(row['municipality'], 'Test town')
        self.assertEqual(row['inc_loc_m'], 250)
        self.assertEqual(row['inc_geo_m'], 87.5)
        self.assertFalse(layer.isEditable())

    def test_copy_coordinates_follow_projected_destination_crs(self):
        mapping, ids = self._copy_fixture()
        self.records.setCrs(QgsCoordinateReferenceSystem('EPSG:32632'))
        self.records.selectByIds([ids['TARGET-1']])
        with patch('geolichen.controllers.plugin_controller.ReuseConfirmedPointDialog.exec', return_value=QDialog.DialogCode.Accepted), \
             patch('geolichen.controllers.plugin_controller.CopyPointTargetsDialog.exec', return_value=QDialog.DialogCode.Accepted), \
             patch('geolichen.controllers.plugin_controller.QMessageBox.question', return_value=16384):
            self.c.reuse_confirmed_point()
        self.assertFalse(self.errors, self.errors)
        transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'),
                                            self.records.crs(), QgsProject.instance())
        expected = transform.transform(QgsPointXY(10.2, 46.05))
        saved = self.records.getFeature(ids['TARGET-1'])
        self.assertAlmostEqual(saved['longitude'], expected.x(), places=5)
        self.assertAlmostEqual(saved['latitude'], expected.y(), places=5)
        point, uncertainty = self.c._confirmed_visual_data_from_feature(self.records, saved)
        self.assertAlmostEqual(point.x(), 10.2, places=5)
        self.assertAlmostEqual(point.y(), 46.05, places=5)
        self.assertEqual(uncertainty, 250)
        confirmed = next(row for row in self.c._confirmed_results_layer().getFeatures()
                         if row['source_fid'] == ids['TARGET-1'])
        self.assertAlmostEqual(confirmed['longitude'], 10.2, places=5)
        self.assertAlmostEqual(confirmed['latitude'], 46.05, places=5)

    def _automatic_flow_fixture(self):
        from geolichen.services.geocoding_service import GeocodingResult
        candidates = [
            {'center': [10.21, 46.06], 'text': 'Other locality', 'place_name': 'Other locality', 'place_type': ['locality']},
            {'center': [10.2, 46.05], 'text': 'Test locality', 'place_name': 'Test locality', 'place_type': ['locality']},
        ]
        result = GeocodingResult(ok=True, feature=candidates[0], candidates=candidates, matched_source='locality')
        return result, metric_buffer(80)

    def _run_automatic_flow(self, selector=None):
        from geolichen.gui.candidate_selector_dialog import CandidateSelectorDialog
        result, boundary = self._automatic_flow_fixture()
        def choose(dialog):
            dialog.table.selectRow(1)
            dialog._accept_selection()
            return QDialog.DialogCode.Accepted
        with patch.object(self.c.geocoding_service, 'geocode_prefer_municipality', return_value=result), \
             patch.object(self.c.initial_boundary_service, 'build_extents', return_value={
                 'search_extent': boundary, 'documented_extent': QgsGeometry(boundary)}), \
             patch.object(self.c.italic_service, 'fetch_profile', side_effect=lambda *a: copy.deepcopy(PROFILE)), \
             patch.object(CandidateSelectorDialog, 'exec', selector or choose):
            self.dock.btnAutomaticPoint.click()
        return result

    def test_automatic_button_resolves_locality_and_saves_rank_one_with_dem(self):
        dem = self.add_dem('Automatic DEM', 1350)
        self.dock.populate_dem_layer_list([dem.name()])
        self.dock.lstDemLayers.item(0).setCheckState(Qt.CheckState.Checked)
        with patch('geolichen.controllers.plugin_controller.ConfirmPointDialog') as confirm_dialog, \
             patch('geolichen.controllers.plugin_controller.QMessageBox.question') as question:
            result = self._run_automatic_flow()
        self.assertFalse(self.errors, self.errors)
        confirm_dialog.assert_not_called()
        question.assert_not_called()
        self.assertEqual(result.center, [10.2, 46.05])
        self.assertEqual(self.c.current_selection_metadata['selection_method'], 'automatic_rank_1')
        selected = self.c.current_selected_candidate
        self.assertEqual(selected['rank'], 1)
        saved = self.records.getFeature(self.feature.id())
        self.assertAlmostEqual(saved['longitude'], selected['point'].x(), places=7)
        self.assertAlmostEqual(saved['latitude'], selected['point'].y(), places=7)
        self.assertEqual(saved['quota_dem'], 1350)
        self.assertGreater(saved['inc_loc_m'], 0)
        self.assertGreater(saved['inc_geo_m'], 0)
        confirmed = self.c._confirmed_results_layer()
        row = next(confirmed.getFeatures())
        self.assertEqual(row['rank'], 1)
        self.assertAlmostEqual(row['model_r_m'], saved['inc_geo_m'])
        self.assertEqual(row['altitude_m'], 1350)
        self.assertTrue(QgsProject.instance().layerTreeRoot().findLayer(confirmed.id()).isVisible())
        self.assertTrue(self.c.confirmed_point_marker.isVisible())
        self.assertFalse(self.c._automatic_point_running)
        self.assertTrue(self.dock.btnAutomaticPoint.isEnabled())
        self.assertTrue(self.dock.btnAnalyze.isEnabled())

    def test_automatic_heatmap_only_still_displays_rank_one_and_keeps_missing_dem_null(self):
        self.dock.cmbSuitabilityView.setCurrentText('Suitability Surface')
        self._run_automatic_flow()
        self.assertFalse(self.errors, self.errors)
        result = self.c.current_suitability_result
        self.assertIsNotNone(result['heatmap_layer'])
        saved = self.records.getFeature(self.feature.id())
        self.assertEqual(saved['quota_dem'], NULL)
        self.assertEqual(next(self.c._confirmed_results_layer().getFeatures())['altitude_m'], NULL)
        self.assertTrue(self.c.confirmed_point_marker.isVisible())

    def test_automatic_cancel_locality_never_ranks_or_creates_columns(self):
        with patch('geolichen.controllers.plugin_controller.HabitatSuitabilityService.find_best_point') as ranking:
            self._run_automatic_flow(selector=lambda dialog: QDialog.DialogCode.Rejected)
        ranking.assert_not_called()
        self.assertEqual(self.records.fields().indexOf('inc_loc_m'), -1)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)
        self.assertIsNone(self.c.confirmed_results_layer_id)
        self.assertTrue(self.dock.btnAutomaticPoint.isEnabled())

    def test_automatic_geocoding_failure_does_not_use_previous_analysis(self):
        from geolichen.services.geocoding_service import GeocodingResult
        self.automatic_analysis(80)
        self.c.find_habitat_suitability_point()
        with patch.object(self.c.geocoding_service, 'geocode_prefer_municipality', return_value=GeocodingResult(ok=False, error='fixture error')), \
             patch('geolichen.controllers.plugin_controller.QMessageBox.warning'), \
             patch('geolichen.gui.candidate_selector_dialog.CandidateSelectorDialog.exec', return_value=QDialog.DialogCode.Rejected), \
             patch('geolichen.controllers.plugin_controller.HabitatSuitabilityService.find_best_point') as ranking:
            self.dock.btnAutomaticPoint.click()
        ranking.assert_not_called()
        self.assertIsNone(self.c.current_suitability_result)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)
        self.assertIsNone(self.c.confirmed_results_layer_id)

    def test_automatic_record_switch_during_locality_choice_blocks_writes(self):
        other, row = self.add_other_table()
        def switch(dialog):
            dialog.table.selectRow(1)
            dialog._accept_selection()
            other.selectByIds([row.id()])
            return QDialog.DialogCode.Accepted
        with patch('geolichen.controllers.plugin_controller.HabitatSuitabilityService.find_best_point') as ranking:
            self._run_automatic_flow(selector=switch)
        ranking.assert_not_called()
        self.assertTrue(self.errors)
        self.assertEqual(other.getFeature(row.id())['longitude'], NULL)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)
        self.assertIsNone(self.c.confirmed_results_layer_id)

    def test_automatic_missing_rank_one_and_scoring_failure_do_not_write(self):
        for failed_result in ({'features': []}, None):
            with self.subTest(result=failed_result), \
                 patch('geolichen.controllers.plugin_controller.HabitatSuitabilityService.find_best_point', return_value=failed_result):
                self._run_automatic_flow()
            self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)
            self.assertIsNone(self.c.confirmed_results_layer_id)
            self.assertEqual(self.records.fields().indexOf('inc_loc_m'), -1)
            self.assertTrue(self.dock.btnHabitatSuitability.isEnabled())

    def test_automatic_requires_one_record_and_prevents_reentry(self):
        self.records.removeSelection()
        with patch.object(self.c.geocoding_service, 'geocode_prefer_municipality') as geocoding:
            self.dock.btnAutomaticPoint.click()
        geocoding.assert_not_called()
        self.assertTrue(self.errors)
        self.errors.clear()
        self.records.selectByIds([self.feature.id()])
        def reenter_then_choose(dialog):
            self.assertTrue(self.c._automatic_point_running)
            self.assertFalse(self.dock.btnAutomaticPoint.isEnabled())
            self.c.find_and_save_automatic_point()
            dialog.table.selectRow(1)
            dialog._accept_selection()
            return QDialog.DialogCode.Accepted
        self._run_automatic_flow(selector=reenter_then_choose)
        self.assertFalse(self.errors, self.errors)
        self.assertEqual(self.c._confirmed_results_layer().featureCount(), 1)

    def test_automatic_keeps_pending_edits_and_uses_existing_legacy_columns(self):
        self.records.dataProvider().addAttributes([
            QgsField('incertezza GBIF', FieldType.Double), QgsField('incertezza R55 S70', FieldType.Double)])
        self.records.updateFields()
        self.records.startEditing()
        self.records.changeAttributeValue(self.feature.id(), 0, 'unsaved-user-value')
        self._run_automatic_flow()
        self.assertFalse(self.errors, self.errors)
        self.assertTrue(self.records.isEditable())
        self.assertEqual(self.records.getFeature(self.feature.id())['record_id'], 'unsaved-user-value')
        self.assertEqual(self.records.fields().indexOf('inc_loc_m'), -1)
        self.assertGreater(self.records.getFeature(self.feature.id())['incertezza GBIF'], 0)
        self.assertGreater(self.records.getFeature(self.feature.id())['incertezza R55 S70'], 0)
        self.assertIn('Salva le modifiche', self.dock.lblOperationalStatus.text())
        self.records.undoStack().undo()
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)
        self.assertEqual(self.records.getFeature(self.feature.id())['record_id'], 'unsaved-user-value')
        self.records.rollBack()

    def test_automatic_record_switch_during_ranking_blocks_writes(self):
        from geolichen.services.habitat_suitability_service import HabitatSuitabilityService
        other, row = self.add_other_table()
        original = HabitatSuitabilityService.find_best_point
        def rank_then_switch(service, *args, **kwargs):
            result = original(service, *args, **kwargs)
            other.selectByIds([row.id()])
            return result
        with patch.object(HabitatSuitabilityService, 'find_best_point', autospec=True, side_effect=rank_then_switch):
            self._run_automatic_flow()
        self.assertTrue(self.errors)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)
        self.assertEqual(other.getFeature(row.id())['longitude'], NULL)
        self.assertEqual(self.records.fields().indexOf('inc_loc_m'), -1)
        self.assertIsNone(self.c.confirmed_results_layer_id)

    def test_automatic_readonly_source_reports_error_and_restores_actions(self):
        self.records.setReadOnly(True)
        self._run_automatic_flow()
        self.assertTrue(self.errors)
        self.assertEqual(self.records.getFeature(self.feature.id())['longitude'], NULL)
        self.assertEqual(self.records.fields().indexOf('inc_loc_m'), -1)
        self.assertIsNone(self.c.confirmed_results_layer_id)
        self.assertTrue(self.dock.btnAutomaticPoint.isEnabled())
        self.assertTrue(self.dock.btnHabitatSuitability.isEnabled())

    def test_automatic_projected_table_uses_target_crs_and_restores_result_visibility(self):
        self.records.setCrs(QgsCoordinateReferenceSystem('EPSG:32632'))
        confirmed = self.c._confirmed_results_layer()
        node = QgsProject.instance().layerTreeRoot().findLayer(confirmed.id())
        node.setItemVisibilityChecked(False)
        self._run_automatic_flow()
        self.assertFalse(self.errors, self.errors)
        point = self.c.current_selected_candidate['point']
        expected = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'),
                                         self.records.crs(), QgsProject.instance()).transform(point)
        saved = self.records.getFeature(self.feature.id())
        self.assertAlmostEqual(saved['longitude'], expected.x(), places=5)
        self.assertAlmostEqual(saved['latitude'], expected.y(), places=5)
        self.assertTrue(node.isVisible())
        final = next(confirmed.getFeatures())
        self.assertAlmostEqual(final['longitude'], point.x(), places=7)
        self.assertAlmostEqual(final['latitude'], point.y(), places=7)

    def test_preview_interface(self):
        output = Path(TEMP) / 'previews'
        output.mkdir(exist_ok=True)
        self.iface.window.resize(540, 820)
        self.iface.window.show()
        APP.processEvents()
        self.dock.grab().save(str(output / 'interface-collapsed.png'))
        self.dock.configurationSection.setExpanded(True)
        APP.processEvents()
        self.dock.grab().save(str(output / 'interface-configuration.png'))


def main():
    global TEMP, APP, FieldType
    with tempfile.TemporaryDirectory(prefix='geolichen_interface_') as temporary:
        TEMP = temporary
        (Path(TEMP) / "previews").mkdir()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, temporary)
        APP = QgsApplication([], True, temporary)
        APP.initQgis()
        spec = importlib.util.spec_from_file_location('geolichen', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
        package = importlib.util.module_from_spec(spec)
        sys.modules['geolichen'] = package
        spec.loader.exec_module(package)
        from geolichen.core.qgis_compat import FieldType
        with patch.object(QgsApplication, 'qgisSettingsDirPath', return_value=temporary):
            result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(InterfaceRegression))
        if not result.wasSuccessful():
            raise SystemExit(1)


if __name__ == '__main__':
    main()
