import re
import math
from qgis.PyQt.QtCore import QSettings, pyqtSignal, Qt, QEventLoop, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QMessageBox, QDialog
from qgis.PyQt import sip
from qgis.core import (
    QgsProject,
    QgsWkbTypes,
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMapLayerType,
    QgsPointXY,
    QgsRaster,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsMarkerSymbol,
)
from qgis.gui import QgsRubberBand, QgsMapToolEmitPoint, QgsVertexMarker

from ..gui.field_mapping_dialog import FieldMappingDialog
from ..gui.candidate_selector_dialog import CandidateSelectorDialog
from ..gui.confirm_point_dialog import ConfirmPointDialog
from ..gui.reuse_confirmed_point_dialog import ReuseConfirmedPointDialog
from ..gui.redefine_buffer_dialog import RedefineBufferDialog
from ..services.geocoding_service import GeocodingService
from ..services.initial_boundary_service import InitialBoundaryService
from ..services.semantic_search_buffer_service import SemanticSearchBufferService
from ..services.locality_parser_service import LocalityParserService
from ..services.locality_interpreter import LocalityInterpreter
from ..services.italic_service import ItalicService
from ..services.record_constraints_service import RecordConstraintsService
from ..services.record_semantic_interpreter import RecordSemanticInterpreter
from ..services.environment_overlay_service import EnvironmentOverlayService
from ..services.geology_group_service import GeologyGroupService
from ..services.tree_service import TreeService
from ..services.soil_service import SoilService
from ..services.ecology_engine import EcologyEngine
from ..services.ecological_layer_decision_service import EcologicalLayerDecisionService
from ..services.habitat_suitability_service import HabitatSuitabilityService
from ..services.osm_trail_service import OsmTrailService
from ..services.context_engine import ContextEngine
from ..services.search_area_service import SearchAreaService
from ..services.explainability_service import ExplainabilityService
from ..services._shared_geo_utils import local_metric_crs
from ..core.terrain_engine import TerrainPreparationEngine
from ..core.summit_detection_engine import SummitDetectionEngine
from ..core.terrain_polygon_engine import TerrainPolygonReconstructionEngine
from ..core.terrain_geometry_validation_engine import TerrainGeometryValidationEngine
from ..core.terrain_geometry_decision_engine import TerrainGeometryDecisionEngine
from ..core.terrain_documented_geometry_integrator import TerrainDocumentedGeometryIntegrator


class CandidateSnapMapTool(QgsMapToolEmitPoint):
    """Map tool con anteprima magnetica verso il candidato più vicino."""

    canvasMoved = pyqtSignal(object)

    def canvasMoveEvent(self, event):
        try:
            self.canvasMoved.emit(self.toMapCoordinates(event.pos()))
        except Exception:
            pass
        super().canvasMoveEvent(event)


class PluginController:
    def __init__(self, iface, dock, performance_service=None):
        self.iface = iface
        self.dock = dock
        self.performance_service = performance_service
        self.active_layer = None
        self.input_layer = None
        self.mapping = None
        self.current_feature = None
        # FASE 1 GBIF: geometrie mantenute separate.
        # original_locality_extent = interpretazione documentale iniziale
        # search_extent = area usata per generare i candidati
        # ecological_candidate_extent = area dopo i filtri ecologici
        # current_boundary resta alias dell'area ecologica per compatibilita'.
        self.original_locality_extent = None
        self.search_extent = None
        # Search Geometry: i rami automatico e manuale sono mantenuti separati.
        # ``search_extent`` resta l'alias operativo letto dal Candidate Engine.
        self.search_geometry_mode = "automatic"
        self.automatic_search_extent = None
        self.manual_search_extent = None
        self.manual_search_center_wgs84 = None
        self.manual_search_radius_m = None
        self.current_resolved_locality = None
        self.current_terrain_context = None
        self.current_summit_result = None
        self.current_terrain_polygon_result = None
        self.current_terrain_validation_result = None
        self.current_terrain_decision_result = None
        self.current_terrain_integration_result = None
        self.ecological_candidate_extent = None
        self.current_boundary = None
        self.current_environment_result = None
        self.current_suitability_result = None
        self.current_selected_candidate = None
        # FASE 13: risultati diagnostici e integrazione della geometria terrain.
        self.current_terrain_context = None
        self.current_summit_result = None
        self.current_terrain_polygon_result = None
        self.current_terrain_validation_result = None
        self.current_terrain_decision_result = None
        self.current_terrain_integration_result = None
        # FASI 2-3: audit dei vincoli e della selezione, separato dal ranking.
        self.current_constraint_metadata = []
        self.current_selection_metadata = None
        # FASE 5.5: contesto geografico centralizzato, inizialmente solo informativo.
        self.current_locality_context = None
        self.rubber_band = None
        self.last_feature = None
        self.manual_point_tool = None
        self.manual_point_previous_tool = None
        self.manual_line_tool = None
        self.manual_line_previous_tool = None
        self.manual_line_feature = None
        self.manual_line_vertices = []
        self.manual_line_band = None
        self.manual_line_vertex_band = None
        # Stato esclusivo dello strumento manuale ATTIVO. È separato dalla
        # geometria manuale già confermata, così un click accidentale su un
        # pulsante non distrugge il boundary valido precedente.
        self.active_manual_capture_mode = None
        self.manual_geometry_kind = 'point_buffer'
        self.manual_line_length_m = None
        self.manual_line_offset_m = None
        self.redefine_buffer_tool = None
        self.redefine_buffer_feature = None
        self.redefine_buffer_radius_m = None
        self.confirm_point_tool = None
        self.confirm_snap_marker = None
        self.confirmed_point_marker = None
        self.confirmed_results_layer_id = None
        self.confirmed_uncertainty_band = None
        self.manual_point_feature = None
        self.candidate_preview_band = None
        self.candidate_preview_center_band = None

        self.geocoding_service = GeocodingService()
        self.initial_boundary_service = InitialBoundaryService()
        self.semantic_search_buffer_service = SemanticSearchBufferService()
        self.locality_parser_service = LocalityParserService()
        self.locality_interpreter = LocalityInterpreter()
        self.italic_service = ItalicService()
        self.record_constraints_service = RecordConstraintsService()
        self.record_semantic_interpreter = RecordSemanticInterpreter()
        self.environment_overlay_service = EnvironmentOverlayService()
        self.geology_group_service = GeologyGroupService()
        self.soil_service = SoilService()
        self.tree_service = TreeService()
        self.ecology_engine = EcologyEngine()
        self.ecological_layer_decision_service = EcologicalLayerDecisionService()
        self.habitat_suitability_service = HabitatSuitabilityService(self.ecology_engine)
        # Do not recreate the OSM service or forget the current layer at every
        # analysis step: that previously made the trail layer disappear between
        # SearchGeometry resolution and candidate evaluation.
        if not hasattr(self, "osm_trail_service") or self.osm_trail_service is None:
            self.osm_trail_service = OsmTrailService()
        if not hasattr(self, "current_osm_trail_layer"):
            self.current_osm_trail_layer = None
        self.explainability_service = ExplainabilityService()
        self.terrain_preparation_engine = TerrainPreparationEngine()
        self.summit_detection_engine = SummitDetectionEngine()
        self.terrain_polygon_engine = TerrainPolygonReconstructionEngine()
        self.terrain_validation_engine = TerrainGeometryValidationEngine()
        self.terrain_decision_engine = TerrainGeometryDecisionEngine()
        self.terrain_geometry_integrator = TerrainDocumentedGeometryIntegrator()
        if not hasattr(self, "context_engine") or self.context_engine is None:
            self.context_engine = ContextEngine()
        self.context_engine = ContextEngine()

        self._connect_signals()
        self._load_search_area_settings()
        self._project = QgsProject.instance()
        self._project_layers_added_slot = self._on_project_layers_changed
        self._project_layers_removed_slot = self._on_project_layers_changed
        self._iface_layer_changed_connected = False
        self._project.layersAdded.connect(self._project_layers_added_slot)
        self._project.layersRemoved.connect(self._project_layers_removed_slot)
        self.iface.currentLayerChanged.connect(self.on_layer_changed)
        self._iface_layer_changed_connected = True
        self._refresh_layers()
        self.on_layer_changed(self.iface.activeLayer())

    def cleanup(self):
        try:
            if self._iface_layer_changed_connected:
                self.iface.currentLayerChanged.disconnect(self.on_layer_changed)
                self._iface_layer_changed_connected = False
        except Exception:
            pass
        try:
            self._project.layersAdded.disconnect(self._project_layers_added_slot)
        except Exception:
            pass
        try:
            self._project.layersRemoved.disconnect(self._project_layers_removed_slot)
        except Exception:
            pass
        try:
            if self.active_layer and hasattr(self.active_layer, 'selectionChanged'):
                self.active_layer.selectionChanged.disconnect(self._on_selection_changed)
        except Exception:
            pass
        try:
            self._clear_candidate_preview()
        except Exception:
            pass
        try:
            self._clear_confirmed_visuals()
        except Exception:
            pass
        try:
            if self.rubber_band is not None:
                self.iface.mapCanvas().scene().removeItem(self.rubber_band)
                self.rubber_band = None
        except Exception:
            pass

    def _on_project_layers_changed(self, *args):
        self._refresh_layers()

    def _connect_signals(self):
        self.dock.btnConfigureFields.clicked.connect(self.configure_fields)
        self.dock.btnAnalyze.clicked.connect(self.analyze_selected_record)
        self.dock.btnItalic.clicked.connect(self.run_italic_lookup)
        if hasattr(self.dock, 'btnManualPoint'):
            self.dock.btnManualPoint.clicked.connect(self.start_manual_point_capture)
        if hasattr(self.dock, 'btnManualLine'):
            self.dock.btnManualLine.clicked.connect(self.start_manual_line_capture)
        if hasattr(self.dock, 'btnRedefineBuffer'):
            self.dock.btnRedefineBuffer.clicked.connect(self.start_redefine_buffer_capture)
        if hasattr(self.dock, 'btnConfirmPoint'):
            self.dock.btnConfirmPoint.clicked.connect(self.start_confirm_point_capture)
        if hasattr(self.dock, 'btnReuseConfirmedPoint'):
            self.dock.btnReuseConfirmedPoint.clicked.connect(self.reuse_confirmed_point)
        self.dock.btnCreateGroupLito.clicked.connect(self.create_group_lito)
        if hasattr(self.dock, 'btnHabitatSuitability'):
            self.dock.btnHabitatSuitability.clicked.connect(self.find_habitat_suitability_point)
        self.dock.cmbGeologyLayer.currentTextChanged.connect(
            lambda _: self._update_fields_for_layer(self.dock.cmbGeologyLayer, self.dock.cmbGeologyField)
        )
        self.dock.cmbSoilLayer.currentTextChanged.connect(
            lambda _: self._update_fields_for_layer(self.dock.cmbSoilLayer, self.dock.cmbSoilField)
        )
        self.dock.cmbTreesLayer.currentTextChanged.connect(
            lambda _: self._update_fields_for_layer(self.dock.cmbTreesLayer, self.dock.cmbTreesField)
        )
        if hasattr(self.dock, 'cmbVegetationBeltLayer') and hasattr(self.dock, 'cmbVegetationBeltField'):
            self.dock.cmbVegetationBeltLayer.currentTextChanged.connect(
                lambda _: self._update_fields_for_layer(self.dock.cmbVegetationBeltLayer, self.dock.cmbVegetationBeltField)
            )

        if hasattr(self.dock, 'cmbSearchArea'):
            self.dock.cmbSearchArea.currentTextChanged.connect(lambda _: self._on_search_area_changed())
        if hasattr(self.dock, 'txtBbox'):
            self.dock.txtBbox.editingFinished.connect(self._save_search_area_settings)
        if hasattr(self.dock, 'chkLimitSearchArea'):
            self.dock.chkLimitSearchArea.stateChanged.connect(lambda _: self._save_search_area_settings())
        if hasattr(self.dock, 'chkAutoExpandSearchArea'):
            self.dock.chkAutoExpandSearchArea.stateChanged.connect(lambda _: self._save_search_area_settings())


    def _settings(self):
        return QSettings("GeoLichen", "GeoLichen")

    def _load_search_area_settings(self):
        try:
            s = self._settings()
            area = s.value("search_area/name", SearchAreaService.DEFAULT_AREA)
            custom_bbox = s.value("search_area/custom_bbox", "")
            limit = str(s.value("search_area/limit", "true")).lower() not in ["false", "0", "no"]
            auto_expand = str(s.value("search_area/auto_expand", "true")).lower() not in ["false", "0", "no"]
            if hasattr(self.dock, "set_search_area"):
                self.dock.set_search_area(area, custom_bbox=custom_bbox, limit=limit, auto_expand=auto_expand)
        except Exception:
            pass

    def _save_search_area_settings(self):
        try:
            s = self._settings()
            area = self.dock.cmbSearchArea.currentText() if hasattr(self.dock, "cmbSearchArea") else SearchAreaService.DEFAULT_AREA
            bbox = self.dock.txtBbox.text().strip() if hasattr(self.dock, "txtBbox") else ""
            limit = self.dock.chkLimitSearchArea.isChecked() if hasattr(self.dock, "chkLimitSearchArea") else True
            auto_expand = self.dock.chkAutoExpandSearchArea.isChecked() if hasattr(self.dock, "chkAutoExpandSearchArea") else True
            s.setValue("search_area/name", area)
            s.setValue("search_area/custom_bbox", bbox)
            s.setValue("search_area/limit", bool(limit))
            s.setValue("search_area/auto_expand", bool(auto_expand))
        except Exception:
            pass

    def _on_search_area_changed(self):
        try:
            if hasattr(self.dock, "update_search_area_bbox"):
                self.dock.update_search_area_bbox()
            self._save_search_area_settings()
        except Exception:
            pass

    def _current_search_area_bbox(self):
        try:
            area = self.dock.cmbSearchArea.currentText() if hasattr(self.dock, "cmbSearchArea") else SearchAreaService.DEFAULT_AREA
            custom = self.dock.txtBbox.text().strip() if hasattr(self.dock, "txtBbox") else None
            return SearchAreaService.bbox_for(area, custom_bbox=custom)
        except Exception:
            return SearchAreaService.bbox_for(SearchAreaService.DEFAULT_AREA)



    def _is_mountain_ref_type_for_altitude_expand(self, ref_type):
        return str(ref_type or "").lower() in {"mountain_area", "mountain_group", "summit", "summit_peak"}

    def _record_altitude_context_for_boundary_expand(self, feature):
        """Legge quota/range dal cartellino usando i parser già presenti nel controller."""
        out = {
            "has_altitude": False,
            "is_range": False,
            "min": None,
            "max": None,
            "mid": None,
            "tolerance": None,
        }
        try:
            field_names = feature.fields().names() if feature is not None else []
            lowered = {str(f).lower(): f for f in field_names}
            candidate_names = [
                "quota", "Quota", "QUOTA", "quota_m", "Quota_m",
                "altitudine", "Altitudine", "quota_cartellino",
                "Quota_cartellino", "quota_record", "Quota_record",
                "record_altitude", "label_altitude"
            ]

            configured_altitude = getattr(self.mapping, "elevation", None) if self.mapping is not None else None
            if configured_altitude:
                candidate_names.insert(0, configured_altitude)

            seen = set()
            for name in candidate_names:
                actual = name if name in field_names else lowered.get(str(name).lower())
                if not actual or actual in seen:
                    continue
                seen.add(actual)
                value = self._get_attr(feature, actual)

                rng = None
                try:
                    rng = self._parse_record_altitude_range(value)
                except Exception:
                    rng = None
                if rng:
                    mn = rng.get("min")
                    mx = rng.get("max")
                    mid = rng.get("mid")
                    out.update({
                        "has_altitude": True,
                        "is_range": True,
                        "min": mn,
                        "max": mx,
                        "mid": mid,
                        "tolerance": 100.0,
                    })
                    return out

                val = None
                try:
                    val = self._parse_record_altitude(value)
                except Exception:
                    val = None
                if val is not None:
                    try:
                        a = abs(int(round(float(val))))
                        if a % 100 == 0:
                            tol = 100.0
                        elif a % 10 == 0:
                            tol = 10.0
                        else:
                            tol = 10.0
                    except Exception:
                        tol = 10.0
                    out.update({
                        "has_altitude": True,
                        "is_range": False,
                        "min": float(val),
                        "max": float(val),
                        "mid": float(val),
                        "tolerance": tol,
                    })
                    return out
        except Exception:
            pass
        return out

    def _boundary_contains_altitude_band(self, boundary_geom, altitude_context, sample_step_m=250):
        """Controlla se il boundary contiene almeno un punto DEM nella fascia quota richiesta.

        È un controllo veloce a griglia larga: serve solo per decidere se espandere
        il buffer di un monte. Il filtro altitudinale hard resta nel candidate scoring.
        """
        if not altitude_context or not altitude_context.get("has_altitude"):
            return True
        if boundary_geom is None or boundary_geom.isEmpty():
            return True

        try:
            dem_layers = self._selected_dem_layers()
        except Exception:
            dem_layers = []

        if not dem_layers:
            # Se manca DEM, non espandere alla cieca.
            return True

        try:
            mn = float(altitude_context.get("min"))
            mx = float(altitude_context.get("max"))
            tol = float(altitude_context.get("tolerance") or 100.0)
            lo = min(mn, mx) - tol
            hi = max(mn, mx) + tol
        except Exception:
            return True

        try:
            src = QgsCoordinateReferenceSystem("EPSG:4326")
            center_wgs84 = boundary_geom.centroid().asPoint()
            dst = local_metric_crs(center_wgs84)
            project = QgsProject.instance()
            geom_m = QgsGeometry(boundary_geom)
            geom_m.transform(QgsCoordinateTransform(src, dst, project))
            rect = geom_m.boundingBox()

            # Limite massimo per non bloccare QGIS.
            max_samples = 700
            samples = 0
            x = rect.xMinimum()
            while x <= rect.xMaximum():
                y = rect.yMinimum()
                while y <= rect.yMaximum():
                    if samples > max_samples:
                        return False
                    pt_m = QgsGeometry.fromPointXY(QgsPointXY(x, y))
                    if geom_m.contains(pt_m):
                        pt_w = QgsGeometry(pt_m)
                        pt_w.transform(QgsCoordinateTransform(dst, src, project))
                        p = pt_w.asPoint()
                        try:
                            sample = self._sample_first_valid_dem(p, src)
                            if sample is not None:
                                alt = float(sample.get("value"))
                                if lo <= alt <= hi:
                                    return True
                        except Exception:
                            pass
                        samples += 1
                    y += sample_step_m
                x += sample_step_m
        except Exception:
            return True

        return False

    def _maybe_expand_mountain_boundary_for_record_altitude(self, boundary, feature, ref_type):
        """Espande automaticamente il boundary dei monti se non intercetta la quota del cartellino."""
        if not self._is_mountain_ref_type_for_altitude_expand(ref_type):
            return boundary

        altitude_context = self._record_altitude_context_for_boundary_expand(feature)
        if not altitude_context.get("has_altitude"):
            return boundary

        if self._boundary_contains_altitude_band(boundary, altitude_context):
            return boundary

        # Espansione progressiva: media, controllata, con limite.
        try:
            center_geom = self.initial_boundary_service._point_from_feature(self.current_geocoding_result.feature)
        except Exception:
            center_geom = None

        if center_geom is None:
            return boundary

        # Phase 15.1: preserve the existing sequence while reading it from
        # the centralized semantic strategy registry.
        _, radii = self.semantic_search_buffer_service.altitude_expansion_radii_for("mountain")
        expanded = boundary
        for radius in radii:
            try:
                candidate = self.initial_boundary_service._metric_buffer_in_wgs84(center_geom, radius)
                if self._boundary_contains_altitude_band(candidate, altitude_context):
                    try:
                        self.dock.set_status(
                            f"Buffer monte esteso automaticamente a {radius} m per intercettare quota cartellino."
                        )
                    except Exception:
                        pass
                    try:
                        plan = self.current_resolved_locality.search_geometry.metadata.get("adaptive_buffer_plan")
                        if isinstance(plan, dict):
                            plan["selected_radius_m"] = float(radius)
                            plan["altitude_expansion_applied"] = True
                            plan["altitude_expansion_result"] = "band_intersected"
                            reasons = plan.setdefault("reasons", [])
                            if "altitude_band_required_expansion" not in reasons:
                                reasons.append("altitude_band_required_expansion")
                    except Exception:
                        pass
                    return candidate
                expanded = candidate
            except Exception:
                continue

        # Se non trova la quota, restituisce comunque l'ultima espansione moderata
        # e sarà il filtro altitudinale hard a bloccare i candidati incompatibili.
        try:
            plan = self.current_resolved_locality.search_geometry.metadata.get("adaptive_buffer_plan")
            if isinstance(plan, dict) and radii:
                plan["selected_radius_m"] = float(radii[-1])
                plan["altitude_expansion_applied"] = True
                plan["altitude_expansion_result"] = "band_not_intersected"
                reasons = plan.setdefault("reasons", [])
                if "altitude_band_required_expansion" not in reasons:
                    reasons.append("altitude_band_required_expansion")
        except Exception:
            pass
        try:
            self.dock.set_status(
                "Warning: quota cartellino non intercettata nel buffer monte anche dopo espansione controllata."
            )
        except Exception:
            pass
        return expanded


    def _warn(self, msg):
        self.dock.set_status(msg)
        QMessageBox.warning(self.iface.mainWindow(), 'Lombardy Lichen Plugin', msg)


    def _layer_is_vector_tile(self, layer):
        if layer is None:
            return False
        try:
            # QGIS 3.x exposes VectorTileLayer enum on QgsMapLayerType.
            return layer.type() == QgsMapLayerType.VectorTileLayer and layer.isValid()
        except Exception:
            try:
                return layer.__class__.__name__ == "QgsVectorTileLayer" and layer.isValid()
            except Exception:
                return False

    def _accessibility_layer_items(self):
        """Lista layer selezionabili per accessibilità: vettoriali classici + vector tiles."""
        items = []
        for lyr in QgsProject.instance().mapLayers().values():
            try:
                if self._layer_supports_fields(lyr):
                    items.append(lyr.name())
                elif self._layer_is_vector_tile(lyr):
                    items.append(f"{lyr.name()} [VectorTile]")
            except Exception:
                continue
        return sorted(items)


    def _layer_is_raster(self, layer):
        if layer is None:
            return False
        try:
            return layer.type() == QgsMapLayerType.RasterLayer and layer.isValid()
        except Exception:
            return False

    def _layer_supports_fields(self, layer):
        if layer is None:
            return False
        try:
            if sip.isdeleted(layer):
                return False
            if layer.type() != QgsMapLayerType.VectorLayer:
                return False
        except Exception:
            return False
        try:
            return hasattr(layer, 'fields') and callable(layer.fields)
        except Exception:
            return False

    def _valid_input_or_active_layer(self):
        """Restituisce un layer vettoriale ancora vivo, evitando wrapper SIP gia' eliminati."""
        input_layer = getattr(self, 'input_layer', None)
        if self._layer_supports_fields(input_layer):
            return input_layer
        if input_layer is not None:
            self.input_layer = None

        active_layer = getattr(self, 'active_layer', None)
        if self._layer_supports_fields(active_layer):
            return active_layer
        if active_layer is not None:
            self.active_layer = None

        return None

    def on_layer_changed(self, layer):
        self._clear_confirmed_visuals()
        try:
            if self.active_layer and hasattr(self.active_layer, 'selectionChanged'):
                self.active_layer.selectionChanged.disconnect(self._on_selection_changed)
        except Exception:
            pass
        self.active_layer = layer
        if layer is None:
            self.dock.set_status('Nessun layer attivo')
            return
        if not self._layer_supports_fields(layer):
            self.dock.set_status('Layer attivo non compatibile: seleziona una tabella o un layer vettoriale con attributi')
            return
        try:
            layer.selectionChanged.connect(self._on_selection_changed)
        except Exception:
            pass
        self.dock.set_status('Configura i campi input oppure seleziona un record')

    def _on_selection_changed(self, *args):
        """Mostra punto e incertezza soltanto per la riga attualmente selezionata."""
        self._clear_confirmed_uncertainty_band()

        layer = self._valid_input_or_active_layer()
        if layer is None or not self._layer_supports_fields(layer):
            return

        try:
            selected = layer.selectedFeatures()
        except Exception:
            selected = []

        # Nessuna selezione (o selezione multipla): non lasciare cerchi residui.
        if len(selected) != 1:
            if not selected:
                self.last_feature = None
            return

        feature = selected[0]
        self.last_feature = feature
        point_wgs84, uncertainty_m = self._confirmed_visual_data_from_feature(layer, feature)
        if point_wgs84 is not None:
            self._show_confirmed_visuals(point_wgs84, uncertainty_m)

    def _confirmed_visual_data_from_feature(self, layer, feature):
        """Recupera centro WGS84 e incertezza dalla feature selezionata."""
        defaults = self._load_confirm_point_defaults()
        uncertainty_field = str(defaults.get("uncertainty_field") or "").strip()
        x_field = str(defaults.get("x_field") or "").strip()
        y_field = str(defaults.get("y_field") or "").strip()

        uncertainty_m = 0.0
        if uncertainty_field and layer.fields().indexOf(uncertainty_field) >= 0:
            try:
                uncertainty_m = max(0.0, float(feature[uncertainty_field] or 0.0))
            except Exception:
                uncertainty_m = 0.0

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        point_wgs84 = None

        # Priorità 1: geometria puntuale effettiva della feature.
        try:
            geom = feature.geometry()
            if geom is not None and not geom.isEmpty() and QgsWkbTypes.geometryType(geom.wkbType()) == QgsWkbTypes.PointGeometry:
                geom = QgsGeometry(geom)
                if layer.crs().isValid() and layer.crs() != wgs84:
                    geom.transform(QgsCoordinateTransform(layer.crs(), wgs84, QgsProject.instance()))
                if geom.isMultipart():
                    points = geom.asMultiPoint()
                    if points:
                        point_wgs84 = QgsPointXY(points[0])
                else:
                    point_wgs84 = QgsPointXY(geom.asPoint())
        except Exception:
            point_wgs84 = None

        # Priorità 2: campi X/Y configurati nel dialogo di conferma.
        if point_wgs84 is None and x_field and y_field:
            try:
                if layer.fields().indexOf(x_field) >= 0 and layer.fields().indexOf(y_field) >= 0:
                    lon = float(feature[x_field])
                    lat = float(feature[y_field])
                    if -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0:
                        point_wgs84 = QgsPointXY(lon, lat)
            except Exception:
                point_wgs84 = None

        return point_wgs84, uncertainty_m

    def configure_fields(self):
        if self.active_layer is None or not self._layer_supports_fields(self.active_layer):
            self._warn('Carica e seleziona prima una tabella o layer vettoriale con attributi.')
            return
        field_names = [f.name() for f in self.active_layer.fields()]
        dlg = FieldMappingDialog(field_names, self.iface.mainWindow())
        if dlg.exec_():
            self.mapping = dlg.get_mapping()
            self.input_layer = self.active_layer
            if not self.mapping.is_valid():
                self._warn('Devi selezionare almeno Specie e uno tra Comune o Località.')
                return
            self.dock.set_mapping_summary(self.mapping)
            self.dock.set_status('Campi configurati')

    def _refresh_layers(self):
        if self.dock is None or sip.isdeleted(self.dock):
            return

        vector_names = [
            lyr.name()
            for lyr in QgsProject.instance().mapLayers().values()
            if self._layer_supports_fields(lyr)
        ]
        self.dock.populate_layer_combos(sorted(vector_names))
        if hasattr(self.dock, "populate_accessibility_layer_list"):
            self.dock.populate_accessibility_layer_list(self._accessibility_layer_items())

        raster_names = [
            lyr.name()
            for lyr in QgsProject.instance().mapLayers().values()
            if self._layer_is_raster(lyr)
        ]

        if hasattr(self.dock, "populate_dem_layer_list"):
            self.dock.populate_dem_layer_list(sorted(raster_names))

        if hasattr(self.dock, 'cmbDemLayer'):
            if hasattr(self.dock, 'populate_raster_combo'):
                self.dock.populate_raster_combo(self.dock.cmbDemLayer, sorted(raster_names))
            else:
                current = self.dock.cmbDemLayer.currentText()
                self.dock.cmbDemLayer.blockSignals(True)
                self.dock.cmbDemLayer.clear()
                self.dock.cmbDemLayer.addItem('')
                self.dock.cmbDemLayer.addItems(sorted(raster_names))
                idx = self.dock.cmbDemLayer.findText(current)
                if idx >= 0:
                    self.dock.cmbDemLayer.setCurrentIndex(idx)
                self.dock.cmbDemLayer.blockSignals(False)

        self._update_fields_for_layer(self.dock.cmbGeologyLayer, self.dock.cmbGeologyField)
        self._update_fields_for_layer(self.dock.cmbSoilLayer, self.dock.cmbSoilField)
        self._update_fields_for_layer(self.dock.cmbTreesLayer, self.dock.cmbTreesField)
        if hasattr(self.dock, 'cmbVegetationBeltLayer') and hasattr(self.dock, 'cmbVegetationBeltField'):
            self._update_fields_for_layer(self.dock.cmbVegetationBeltLayer, self.dock.cmbVegetationBeltField)



    def _run_terrain_documented_geometry_pipeline(self, feature):
        """Run Phase 13A-D.3 for mountain localities and update SLGE safely.

        Failures never interrupt the historical GeoLichen workflow: the semantic
        DocumentedGeometry remains active and the SearchGeometry is untouched.
        """
        resolved = self.current_resolved_locality
        if resolved is None:
            return None
        feature_type = str(getattr(resolved.interpretation, "feature_type", "") or "").lower()
        if feature_type not in {"mountain", "mountain_area", "mountain_group", "summit_peak", "peak"}:
            return None
        dem_layers = self._selected_dem_layers()
        if not dem_layers:
            resolved.provenance["terrain_integration"] = {
                "phase": "13D.3", "applied": False, "reason": "no_dem_selected"
            }
            return None
        center = getattr(self.current_locality_context, "geocoded_center", None)
        if center is None:
            resolved.provenance["terrain_integration"] = {
                "phase": "13D.3", "applied": False, "reason": "missing_geocoded_center"
            }
            return None
        source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        try:
            record_altitude = self._get_record_altitude(feature)
        except Exception:
            record_altitude = None
        try:
            terrain = self.terrain_preparation_engine.prepare(
                dem_layers, center, source_crs, radius_m=2500.0, band=1
            )
            summit = self.summit_detection_engine.detect(
                terrain, anchor_point=terrain.center if terrain is not None else None,
                record_elevation_m=record_altitude,
            )
            polygon = self.terrain_polygon_engine.reconstruct(terrain, summit)
            validation = self.terrain_validation_engine.validate(terrain, summit, polygon)
            decision = self.terrain_decision_engine.decide(
                resolved.documented_geometry, polygon, validation
            )
            integration = self.terrain_geometry_integrator.integrate(
                resolved, polygon, validation, decision,
                terrain_crs=getattr(terrain, "crs", None),
                documented_crs=source_crs,
                summit_result=summit, terrain_context=terrain,
            )
            self.current_terrain_context = terrain
            self.current_summit_result = summit
            self.current_terrain_polygon_result = polygon
            self.current_terrain_validation_result = validation
            self.current_terrain_decision_result = decision
            self.current_terrain_integration_result = integration
            if self.current_locality_context is not None:
                self.current_locality_context.set_resolved_locality(resolved)
            return integration
        except Exception as exc:
            resolved.provenance["terrain_integration"] = {
                "phase": "13D.3", "applied": False,
                "reason": "pipeline_exception", "error": str(exc),
            }
            resolved.warnings.append(f"Ricostruzione terrain non applicata: {exc}")
            return None

    def _raster_layer_by_name(self, name):
        if not name:
            return None
        layers = QgsProject.instance().mapLayersByName(name)
        for lyr in layers:
            if self._layer_is_raster(lyr):
                return lyr
        return None

    def _selected_dem_layers(self):
        layers = []
        try:
            if hasattr(self.dock, "lstDemLayers"):
                for i in range(self.dock.lstDemLayers.count()):
                    item = self.dock.lstDemLayers.item(i)
                    if item and item.checkState() == Qt.Checked:
                        layer = self._raster_layer_by_name(item.text())
                        if layer is not None and layer not in layers:
                            layers.append(layer)
        except Exception:
            pass
        if not layers and hasattr(self.dock, "cmbDemLayer"):
            layer = self._raster_layer_by_name(self.dock.cmbDemLayer.currentText())
            if layer is not None:
                layers.append(layer)
        return layers

    def _sample_dem_layer_at_point(self, dem_layer, point, point_crs, band=1):
        """Campiona un singolo DEM solo se il punto ricade nella sua estensione.

        La scelta del DEM è spaziale: ogni tassello viene interrogato soltanto
        quando copre realmente il punto. L'ordine della lista viene usato solo
        come spareggio nelle eventuali sovrapposizioni.
        """
        try:
            if dem_layer is None or not self._layer_is_raster(dem_layer):
                return None

            if isinstance(point, QgsPointXY):
                source_point = QgsPointXY(point)
            else:
                source_point = QgsPointXY(float(point.x()), float(point.y()))

            geom = QgsGeometry.fromPointXY(source_point)
            dem_crs = dem_layer.crs()
            if point_crs and point_crs.isValid() and dem_crs.isValid() and point_crs != dem_crs:
                geom.transform(QgsCoordinateTransform(point_crs, dem_crs, QgsProject.instance()))
            p = QgsPointXY(geom.asPoint())

            extent = dem_layer.extent()
            if extent is None or extent.isEmpty() or not extent.contains(p):
                return None

            provider = dem_layer.dataProvider()
            if provider is None:
                return None

            # identify() è più affidabile di sample() con GeoTIFF tassellati,
            # provider GDAL e raster con NoData. sample() resta come fallback.
            value = None
            try:
                identified = provider.identify(p, QgsRaster.IdentifyFormatValue)
                if identified is not None and identified.isValid():
                    results = identified.results() or {}
                    value = results.get(int(band))
            except Exception:
                value = None

            if value is None:
                try:
                    result = provider.sample(p, int(band))
                    if isinstance(result, tuple):
                        sampled = result[0]
                        ok = bool(result[1]) if len(result) > 1 else sampled is not None
                    else:
                        sampled = result
                        ok = sampled is not None
                    if ok:
                        value = sampled
                except Exception:
                    value = None

            if value is None:
                return None

            value = float(value)
            if not math.isfinite(value):
                return None

            try:
                nodata = provider.sourceNoDataValue(int(band))
                if nodata is not None and math.isfinite(float(nodata)) and value == float(nodata):
                    return None
            except Exception:
                pass

            return value
        except Exception:
            return None

    def _sample_first_valid_dem(self, point, point_crs):
        """Seleziona il DEM in base alla posizione del punto, non alla priorità."""
        covering = []
        for index, dem_layer in enumerate(self._selected_dem_layers()):
            value = self._sample_dem_layer_at_point(dem_layer, point, point_crs, band=1)
            if value is not None:
                covering.append((index, dem_layer, value))

        if not covering:
            return None

        index, dem_layer, value = covering[0]
        return {
            "value": value,
            "layer": dem_layer,
            "source": dem_layer.name(),
            "priority": index + 1,
            "selection_rule": "spatial_extent",
            "covering_count": len(covering),
        }

    def _layer_by_name(self, name):
        if not name:
            return None
        layers = QgsProject.instance().mapLayersByName(name)
        return layers[0] if layers else None

    def _update_fields_for_layer(self, layer_combo, field_combo):
        if self.dock is None or sip.isdeleted(self.dock):
            return
        if sip.isdeleted(layer_combo) or sip.isdeleted(field_combo):
            return
        layer = self._layer_by_name(layer_combo.currentText())
        field_names = [f.name() for f in layer.fields()] if self._layer_supports_fields(layer) else []
        self.dock.populate_field_combo(field_combo, field_names)
        if field_names and field_combo.currentText() == '':
            preferred = ['GRUPPO_LITO', 'LITOLOGIA', 'DESCRIZION', 'DESCRIZIONE', 'UNITA', 'FORMAZIONE', 'NOME', 'name', 'nome']
            for p in preferred:
                idx = field_combo.findText(p)
                if idx >= 0:
                    field_combo.setCurrentIndex(idx)
                    break

    def _selected_feature(self):
        layer = self._valid_input_or_active_layer()
        if layer is None or not self._layer_supports_fields(layer):
            return None
        self.active_layer = layer
        features = layer.selectedFeatures()
        if not features:
            return self.last_feature
        feature = features[0]
        self.last_feature = feature
        try:
            layer.selectByIds([feature.id()])
        except Exception:
            pass
        return feature

    def create_group_lito(self):
        geology_layer = self._layer_by_name(self.dock.cmbGeologyLayer.currentText())
        if not geology_layer:
            self._warn('Seleziona prima il layer geologico.')
            return
        source_field = self.dock.cmbGeologyField.currentText() or None
        try:
            res = self.geology_group_service.ensure_group_field(geology_layer, source_field=source_field)
            self._update_fields_for_layer(self.dock.cmbGeologyLayer, self.dock.cmbGeologyField)
            idx = self.dock.cmbGeologyField.findText('GRUPPO_LITO')
            if idx >= 0:
                self.dock.cmbGeologyField.setCurrentIndex(idx)
            self.dock.set_group_lito_info(
                f"Creato/aggiornato {res['target_field']} da {res['source_field']} ({res['changed_count']} feature aggiornate)"
            )
            self.dock.set_status('GRUPPO_LITO pronto')
        except Exception as exc:
            self._warn(f'Creazione GRUPPO_LITO fallita: {exc}')

    def _ensure_aux_services(self):
        """Garantisce che tutti i servizi ausiliari esistano anche dopo reload parziali di QGIS."""
        if not hasattr(self, "soil_service"):
            self.soil_service = SoilService()
        if not hasattr(self, "tree_service"):
            self.tree_service = TreeService()
        if not hasattr(self, "ecology_engine"):
            self.ecology_engine = EcologyEngine()
        if not hasattr(self, 'ecological_layer_decision_service') or self.ecological_layer_decision_service is None:
            self.ecological_layer_decision_service = EcologicalLayerDecisionService()
        if not hasattr(self, 'locality_interpreter') or self.locality_interpreter is None:
            self.locality_interpreter = LocalityInterpreter()
        self.habitat_suitability_service = HabitatSuitabilityService(self.ecology_engine)
        # Do not recreate the OSM service or forget the current layer at every
        # analysis step: that previously made the trail layer disappear between
        # SearchGeometry resolution and candidate evaluation.
        if not hasattr(self, "osm_trail_service") or self.osm_trail_service is None:
            self.osm_trail_service = OsmTrailService()
        if not hasattr(self, "current_osm_trail_layer"):
            self.current_osm_trail_layer = None
        self.explainability_service = ExplainabilityService()

    def _create_locality_context(self, municipality, locality):
        """Crea e conserva il contesto senza alterare il flusso storico."""
        self.current_locality_context = self.locality_interpreter.build_context(
            municipality=municipality,
            locality=locality,
        )
        return self.current_locality_context

    def _sync_locality_extents(
        self,
        original_locality_extent=None,
        search_extent=None,
        ecological_extent=None,
    ):
        """Sincronizza le geometrie del controller nel LocalityContext."""
        return self.locality_interpreter.update_extents(
            self.current_locality_context,
            original_locality_extent=original_locality_extent,
            search_extent=search_extent,
            ecological_extent=ecological_extent,
        )

    def analyze_selected_record(self):
        token = None
        status = "ok"
        if self.performance_service is not None:
            try:
                token = self.performance_service.start("analisi_record")
            except Exception:
                token = None
        try:
            return self._analyze_selected_record_impl()
        except Exception:
            status = "error"
            raise
        finally:
            if token is not None:
                try:
                    details = {
                        "layer": self.active_layer.name() if self.active_layer is not None else "",
                        "has_boundary": self.current_boundary is not None,
                        "has_candidate": self.current_selected_candidate is not None,
                    }
                    self.performance_service.finish(token, status=status, details=details)
                except Exception:
                    pass

    def _analyze_selected_record_impl(self):
        # L'analisi automatica è mutuamente esclusiva con gli strumenti manuali.
        # Se la linea/punto sono stati attivati per errore, vengono annullati
        # prima di iniziare geocoding e pipeline automatica.
        self._cancel_active_manual_capture(restore_previous=False)
        is_manual_line = False
        self._ensure_aux_services()
        if self.mapping is None:
            self._warn('Configura prima i campi input.')
            return
        layer = self._valid_input_or_active_layer()
        if layer is None or not self._layer_supports_fields(layer):
            self._warn('Nessun layer attivo compatibile')
            return
        self.active_layer = layer
        feature = self._selected_feature()
        if feature is None:
            self._warn('Seleziona una riga nella tabella.')
            return
        self.current_feature = feature
        self.current_environment_result = None
        self.original_locality_extent = None
        self.search_extent = None
        self.search_geometry_mode = "automatic"
        self.automatic_search_extent = None
        self.manual_search_extent = None
        self.manual_search_center_wgs84 = None
        self.manual_search_radius_m = None
        self.current_resolved_locality = None
        self.current_terrain_context = None
        self.current_summit_result = None
        self.current_terrain_polygon_result = None
        self.current_terrain_validation_result = None
        self.current_terrain_decision_result = None
        self.current_terrain_integration_result = None
        self.ecological_candidate_extent = None
        self.current_boundary = None
        self.current_locality_context = None

        municipality = self._get_attr(feature, self.mapping.municipality)
        locality = self._get_attr(feature, self.mapping.locality)
        scientific_name = self._get_attr(feature, self.mapping.scientific_name)

        api_key = self.dock.txtApiKey.text().strip()
        self.geocoding_service.set_api_key(api_key)
        # GeoLichen 2.5: area di ricerca persistente.
        # L'utente la sceglie una volta e resta valida finché non la cambia.
        try:
            if hasattr(self.dock, "chkLimitSearchArea") and not self.dock.chkLimitSearchArea.isChecked():
                self.geocoding_service.set_bbox(None)
            else:
                bbox_vals = self._current_search_area_bbox()
                if bbox_vals:
                    self.geocoding_service.set_bbox(tuple(bbox_vals))
            self._save_search_area_settings()
        except Exception:
            pass

        # FASE 5.5b: crea e conserva un unico contesto della località.
        # In questa sottofase parser e geocoder ricevono ancora i valori originali,
        # così il comportamento operativo resta identico alla 5.5a.
        self._create_locality_context(municipality, locality)

        locality_parse_result = self.locality_parser_service.parse(
            locality_context=self.current_locality_context,
        )
        self.current_locality_parse_result = locality_parse_result
        self.current_locality_text = locality or ""
        # FASE 6: prima classificazione basata su cartellino e parser.
        # È solo descrittiva e non modifica query, buffer o ranking.
        self.locality_interpreter.classify(
            self.current_locality_context,
            parse_result=locality_parse_result,
        )
        result = self.geocoding_service.geocode_prefer_municipality(
            locality_parse_result=locality_parse_result,
            locality_context=self.current_locality_context,
        )
        if not result.ok:
            self.dock.set_status(f'Geocoding fallito: {result.error}. Usa “Punto manuale + buffer” per indicare il punto sulla mappa.')
            QMessageBox.warning(self.iface.mainWindow(), 'Lombardy Lichen Plugin', 'Geocoding fallito. Puoi usare il pulsante “Punto manuale + buffer” e cliccare un punto sulla mappa.')
            return

        result = self._select_geocoding_candidate_if_needed(result)
        if result is None:
            self.current_geocoding_result = None
            self.original_locality_extent = None
            self.search_extent = None
            self.ecological_candidate_extent = None
            self.current_boundary = None
            self.current_constraint_metadata = []
            self.current_selection_metadata = None
            self.dock.set_status('Selezione località annullata: nessun buffer creato.')
            return

        self.current_geocoding_result = result
        # FASE 7: conserva il centro del geocoder per il corrected center GBIF.
        try:
            c = result.center
            if c and len(c) == 2:
                self.current_locality_context.set_geocoded_center(
                    QgsPointXY(float(c[0]), float(c[1]))
                )
        except Exception:
            pass

        raw_ref_type = result.matched_source or 'locality'
        ref_type = self._semantic_ref_type_from_locality(locality, raw_ref_type)

        # FASE 6: affina la classificazione con il risultato del geocoder e
        # il tipo semantico già usato dal flusso storico.
        self.locality_interpreter.classify(
            self.current_locality_context,
            parse_result=locality_parse_result,
            geocoding_result=result,
            ref_type=ref_type,
        )

        # Mantiene traccia della riclassificazione semantica nel candidato.
        try:
            result.feature["_geolichen_ref_type"] = ref_type
            result.feature["_geolichen_raw_ref_type"] = raw_ref_type
        except Exception:
            pass

        try:
            result.feature["_geolichen_boundary_altitude"] = self._boundary_altitude_context_from_record(feature)
        except Exception:
            pass

        self.dock.set_match_type(ref_type if ref_type == raw_ref_type else f"{ref_type} (da {raw_ref_type})")
        self.dock.set_tried_queries(getattr(result, 'tried_queries', []))
        self.dock.set_candidates(self._summarize_candidates(result))
        extent_result = self.initial_boundary_service.build_extents(
            result.feature,
            ref_type=ref_type,
            locality_context=self.current_locality_context,
        )
        self.current_resolved_locality = extent_result.get("resolved_locality")
        documented_boundary = extent_result.get("documented_extent")
        boundary = extent_result.get("search_extent")

        # FASE 13D.3: per le località montane tenta la ricostruzione DEM e,
        # soltanto dopo validazione/decisione positiva, sostituisce la sola
        # DocumentedGeometry. La SearchGeometry resta identica.
        self._run_terrain_documented_geometry_pipeline(feature)
        if self.current_resolved_locality is not None:
            documented_boundary = self.current_resolved_locality.documented_geometry.geometry

        # Eventuali espansioni richieste dalla quota del record sono operative:
        # modificano la ricerca, non la rappresentazione documentale GBIF.
        boundary_before_altitude = QgsGeometry(boundary) if boundary is not None else None
        boundary = self._maybe_expand_mountain_boundary_for_record_altitude(
            boundary, feature, ref_type
        )
        if self.current_resolved_locality is not None and boundary is not None:
            changed = False
            try:
                changed = boundary_before_altitude is None or not boundary.equals(boundary_before_altitude)
            except Exception:
                changed = True
            if changed:
                self.current_resolved_locality.search_geometry.replace_geometry(
                    QgsGeometry(boundary),
                    reason="Espansione operativa guidata dalla quota del record",
                )
                self.current_resolved_locality.search_geometry.record_expansion(
                    "record_altitude",
                    reference_type=ref_type,
                )

        # Congela esclusivamente la geometria sostenuta dalla fonte geografica.
        self.original_locality_extent = (
            QgsGeometry(documented_boundary)
            if documented_boundary is not None
            else None
        )
        self.search_extent = QgsGeometry(boundary) if boundary is not None else None
        self._sync_locality_extents(
            original_locality_extent=self.original_locality_extent,
            search_extent=self.search_extent,
        )

        geology_layer = self._layer_by_name(self.dock.cmbGeologyLayer.currentText())
        soil_layer = self._layer_by_name(self.dock.cmbSoilLayer.currentText())
        trees_layer = self._layer_by_name(self.dock.cmbTreesLayer.currentText())
        geology_field = self.dock.cmbGeologyField.currentText() or None
        soil_field = self.dock.cmbSoilField.currentText() or None
        trees_field = self.dock.cmbTreesField.currentText() or None

        # FASE 1: prima record + litologia/suolo/alberi, come nel flusso originale.
        record_constraints = self.record_constraints_service.extract_record_constraints(feature, self.mapping)
        record_semantics = self.record_semantic_interpreter.interpret(record_constraints)
        record_constraints.update(record_semantics)
        record_metadata = list(record_constraints.get("constraint_metadata") or [])
        # Le inferenze semantiche derivate dal testo restano tracciate come tali.
        for _name in ["habitat", "humidity", "slope", "altitude_min", "altitude_max"]:
            record_metadata = self.record_constraints_service.add_derived_constraint(
                record_metadata, _name, record_semantics.get(_name),
                source="record_semantic_interpreter",
                affects_gbif_extent=False,
                affects_gss=True,
                evidence=record_semantics.get("semantic_details"),
            )
        record_constraints["constraint_metadata"] = record_metadata

        env_record = self.environment_overlay_service.apply(
            boundary_geom=boundary,
            geology_layer=geology_layer,
            geology_field=geology_field,
            soil_layer=soil_layer,
            soil_field=soil_field,
            trees_layer=trees_layer,
            trees_field=trees_field,
            constraints=record_constraints,
        )

        # La SearchGeometry deve restare l'intera area operativa della località.
        # Gli overlay ambientali vengono conservati come diagnostica e valutati
        # punto per punto dal GSS: non devono ritagliare la griglia a monte.
        self.search_extent = QgsGeometry(boundary)
        if self.current_resolved_locality is not None:
            # Mantiene la geometria operativa originaria; registra soltanto il
            # fatto che gli overlay del record saranno usati nello scoring.
            if env_record.get('geometry'):
                self.current_resolved_locality.search_geometry.add_filter(
                    "record_environment_overlay_scoring_only",
                    geometry_changed=False,
                    usage="scoring_only",
                )
        if self.current_locality_context is not None:
            self.current_locality_context.replace_search_extent(
                self.search_extent,
                reason="Area operativa completa; overlay ambientali applicati nello scoring",
            )
        self._sync_locality_extents(search_extent=self.search_extent)

        taxon_for_italic = self._get_taxon_value(feature) or scientific_name
        italic_profile = self.italic_service.fetch_profile(taxon_for_italic)
        italic_profile = self._attach_record_context_to_profile(italic_profile, feature)
        italic_profile = self._attach_record_altitude_to_profile(italic_profile, feature)
        profile = self.record_semantic_interpreter.merge_record_and_italic(record_semantics, italic_profile)
        # Propaga l'esito unico del Substrate Resolution Engine nel contesto del
        # record. I servizi successivi non devono riclassificare il substrato.
        for _key in (
            'substrate_group', 'substrate_raw', 'substrate_source',
            'substrate_locked', 'substrate_confidence',
            'substrate_resolution_reason',
        ):
            if _key in profile:
                record_constraints[_key] = profile.get(_key)

        layer_decision = self.ecological_layer_decision_service.decide(profile, record_constraints)
        profile['layer_decision'] = layer_decision

        ecology_constraints = self.ecology_engine.compute_constraints(profile)
        ecology_score_result = self.ecology_engine.compute_score(
            profile,
            self._build_ecology_env_from_record(record_constraints, env_record),
        )
        profile['gis_constraints'] = ecology_constraints
        profile['ecological_score'] = ecology_score_result.get('score')
        profile['ecological_score_details'] = ecology_score_result.get('details', [])

        self.dock.set_italic_profile(profile)
        italic_constraints = self.record_constraints_service.extract_italic_constraints(profile)
        for _key in (
            'substrate_group', 'substrate_raw', 'substrate_source',
            'substrate_locked', 'substrate_confidence',
            'substrate_resolution_reason',
        ):
            if _key in profile:
                italic_constraints[_key] = profile.get(_key)
        italic_constraints['layer_decision'] = layer_decision
        if layer_decision.get('soil_ph_preference'):
            italic_constraints['soil_ph_preference'] = layer_decision.get('soil_ph_preference')

        # Uniforma il comportamento non-saxicolo:
        # - terricoli/muscicoli: usa inferenze suolo/pH
        # - epifiti/lignicoli: usa inferenze alberi/boschi/forofita
        soil_constraints = self.soil_service.infer_constraints(profile)
        tree_constraint = self.tree_service.infer_tree_type(profile)

        if ecology_constraints.get('rock_type'):
            italic_constraints['rock_type'] = ecology_constraints.get('rock_type')
        if ecology_constraints.get('substrate'):
            italic_constraints['substrate'] = ecology_constraints.get('substrate')
        if ecology_constraints.get('habitat'):
            existing_h = italic_constraints.get('fallback_habitat') or []
            italic_constraints['fallback_habitat'] = list(dict.fromkeys(existing_h + ecology_constraints.get('habitat')))
            italic_constraints['habitat_classes'] = ecology_constraints.get('habitat')
        if ecology_constraints.get('humidity'):
            italic_constraints['humidity'] = ecology_constraints.get('humidity')
        if ecology_constraints.get('slope'):
            italic_constraints['slope'] = ecology_constraints.get('slope')
        if ecology_constraints.get('altitude_min') is not None:
            italic_constraints['altitude_min'] = ecology_constraints.get('altitude_min')
        if ecology_constraints.get('altitude_max') is not None:
            italic_constraints['altitude_max'] = ecology_constraints.get('altitude_max')

        if soil_constraints.get('substrate'):
            italic_constraints['substrate'] = soil_constraints.get('substrate')
        if soil_constraints.get('rock_type') and not italic_constraints.get('rock_type'):
            italic_constraints['rock_type'] = soil_constraints.get('rock_type')
        if soil_constraints.get('soil_ph_preference'):
            italic_constraints['soil_ph_preference'] = soil_constraints.get('soil_ph_preference')
        if soil_constraints.get('fallback_substrata'):
            existing = italic_constraints.get('fallback_substrata') or []
            italic_constraints['fallback_substrata'] = list(dict.fromkeys(existing + soil_constraints.get('fallback_substrata')))
        if soil_constraints.get('habitat_classes'):
            existing_h = italic_constraints.get('fallback_habitat') or []
            italic_constraints['fallback_habitat'] = list(dict.fromkeys(existing_h + soil_constraints.get('habitat_classes')))
            italic_constraints['habitat_classes'] = soil_constraints.get('habitat_classes')

        if tree_constraint:
            italic_constraints['tree_type'] = tree_constraint

        italic_metadata = list(italic_constraints.get("constraint_metadata") or [])
        for _name, _source in [
            ("soil_ph_preference", "soil_service"),
            ("habitat_classes", "ecology_engine"),
            ("humidity", "ecology_engine"),
            ("slope", "ecology_engine"),
            ("altitude_min", "ITALIC"),
            ("altitude_max", "ITALIC"),
        ]:
            italic_metadata = self.record_constraints_service.add_derived_constraint(
                italic_metadata, _name, italic_constraints.get(_name),
                source=_source, affects_gbif_extent=False, affects_gss=True
            )
        self.current_constraint_metadata = self.record_constraints_service.merge_constraint_metadata(
            record_metadata, italic_metadata
        )
        profile["constraint_metadata"] = list(self.current_constraint_metadata)
        italic_constraints["constraint_metadata"] = italic_metadata
        # In modalità manuale la search extent coincide inizialmente con il
        # buffer disegnato. Il fallback impedisce che una sincronizzazione del
        # contesto possa lasciare passare una geometria None al secondo overlay.
        italic_boundary = self.search_extent
        if italic_boundary is None or italic_boundary.isNull() or italic_boundary.isEmpty():
            italic_boundary = self.original_locality_extent

        env_italic = self.environment_overlay_service.apply(
            boundary_geom=italic_boundary,
            geology_layer=geology_layer,
            geology_field=geology_field,
            soil_layer=soil_layer,
            soil_field=soil_field,
            trees_layer=trees_layer,
            trees_field=trees_field,
            constraints=italic_constraints,
        )

        env_result = self._merge_environment_results(env_record, env_italic, profile)
        env_result["constraint_metadata"] = list(self.current_constraint_metadata)
        if is_manual_line:
            env_result["search_geometry_mode"] = "manual_line"
            env_result["manual_line_length_m"] = float(self.manual_line_length_m or 0.0)
            env_result["manual_line_offset_m"] = float(self.manual_line_offset_m or radius_m)
            env_result["search_geometry"] = QgsGeometry(self.search_extent)
        self.current_environment_result = env_result
        self.ecological_candidate_extent = QgsGeometry(
            env_result['geometry'] if env_result.get('geometry') else self.search_extent
        )
        # Il motore di campionamento lavora sempre sulla SearchGeometry completa.
        # L'estensione ecologica resta separata per diagnostica e provenance.
        self.current_boundary = QgsGeometry(self.search_extent)
        self._sync_locality_extents(
            ecological_extent=self.ecological_candidate_extent,
        )

        self._zoom_to_geometry(self.current_boundary)
        self._show_boundary_highlight(self.current_boundary)

        source_labels = {
            'municipality': 'comune', 'locality': 'località', 'valley': 'valle', 'summit': 'cima/monte/colle',
            'summit_peak': 'cima/vetta', 'mountain_area': 'monte/area del rilievo', 'mountain_group': 'gruppo montuoso',
            'pass': 'passo', 'meadow': 'prato/piana', 'refuge_malga': 'rifugio/malga', 'hydro': 'torrente/rio/lago',
            'nearby_place': 'località vicina', 'trail': 'sentiero', 'forest_area': 'area forestale', 'generic_toponym': 'toponimo'
        }
        src_label = source_labels.get(result.matched_source, result.matched_source or 'località')
        record_rock = record_constraints.get('rock_type') or '-'
        italic_rock = profile.get('rock_type') or '-'
        rock_label = f'record={record_rock}; ITALIC={italic_rock}'
        status_parts = [
            f'Luogo trovato da {src_label}',
            f'Specie: {scientific_name or "-"}',
            f'Profilo: {profile.get("source")}',
            f'Substrata ITALIC: {", ".join(profile.get("substrata", []) or []) or "-"}',
            f'Roccia: {rock_label}',
            f'Decisione ecologica: {layer_decision.get("explain") or "-"}',
            f'Campo geologia: {env_result.get("resolved_geology_field") or "-"}',
            f'Score ambiente: {env_result.get("score")}',
            f'Cartellino: {"; ".join(profile.get("semantic_details", [])[:2]) if profile.get("semantic_details") else "-"}',
            f'Area ricerca: {self.dock.cmbSearchArea.currentText() if hasattr(self.dock, "cmbSearchArea") else "-"}',
        ]
        if env_result.get('details'):
            status_parts.append('Dettagli: ' + '; '.join(env_result['details'][:2]))
        if env_result.get('warnings'):
            status_parts.append('Warning: ' + '; '.join(env_result['warnings'][:2]))
        if env_result.get('blocking_reasons'):
            status_parts.append('Blocchi: ' + '; '.join(env_result['blocking_reasons'][:2]))
        self.dock.set_status(' | '.join(status_parts))


    def _confirm_point_settings(self):
        return QSettings("GeoLichen", "GeoLichenConfirmPoint")

    def _load_confirm_point_defaults(self):
        try:
            s = self._confirm_point_settings()
            return {
                "x_field": s.value("fields/x", ""),
                "y_field": s.value("fields/y", ""),
                "dem_field": s.value("fields/dem", ""),
                "uncertainty_field": s.value("fields/uncertainty", ""),
                "model_radius_field": s.value("fields/model_radius", ""),
                "uncertainty": s.value("last/uncertainty", 0),
            }
        except Exception:
            return {}

    def _save_confirm_point_defaults(self, vals):
        try:
            s = self._confirm_point_settings()
            s.setValue("fields/x", vals.get("x_field", ""))
            s.setValue("fields/y", vals.get("y_field", ""))
            s.setValue("fields/dem", vals.get("dem_field", ""))
            s.setValue("fields/uncertainty", vals.get("uncertainty_field", ""))
            s.setValue("fields/model_radius", vals.get("model_radius_field", ""))
            s.setValue("last/uncertainty", vals.get("uncertainty", 0))
        except Exception:
            pass

    def _clear_confirm_snap_marker(self):
        try:
            if self.confirm_snap_marker is not None:
                self.iface.mapCanvas().scene().removeItem(self.confirm_snap_marker)
        except Exception:
            pass
        self.confirm_snap_marker = None

    def _show_confirm_snap_marker(self, point_wgs84):
        """Mostra sul canvas il candidato a cui il cursore è agganciato."""
        self._clear_confirm_snap_marker()
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        geom = QgsGeometry.fromPointXY(QgsPointXY(point_wgs84))
        if canvas_crs.isValid() and canvas_crs != wgs84:
            geom.transform(QgsCoordinateTransform(wgs84, canvas_crs, QgsProject.instance()))
        canvas_point = geom.asPoint()
        marker = QgsVertexMarker(canvas)
        marker.setCenter(QgsPointXY(canvas_point))
        marker.setIconType(QgsVertexMarker.ICON_BOX)
        marker.setIconSize(8)
        marker.setPenWidth(2)
        marker.setColor(QColor(255, 23, 68))
        self.confirm_snap_marker = marker
        canvas.refresh()

    def _clear_confirmed_uncertainty_band(self):
        """Rimuove soltanto il cerchio blu, lasciando visibile il punto."""
        canvas = self.iface.mapCanvas()
        item = getattr(self, 'confirmed_uncertainty_band', None)
        if item is not None:
            try:
                canvas.scene().removeItem(item)
            except Exception:
                pass
        self.confirmed_uncertainty_band = None

    def _clear_confirmed_point_marker(self):
        canvas = self.iface.mapCanvas()
        item = getattr(self, 'confirmed_point_marker', None)
        if item is not None:
            try:
                canvas.scene().removeItem(item)
            except Exception:
                pass
        self.confirmed_point_marker = None

    def _clear_confirmed_visuals(self):
        self._clear_confirmed_uncertainty_band()
        self._clear_confirmed_point_marker()

    def _show_confirmed_point_marker(self, point_wgs84):
        """Mostra il punto confermato in modo persistente sulla mappa."""
        self._clear_confirmed_point_marker()
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        point_geom = QgsGeometry.fromPointXY(QgsPointXY(point_wgs84))
        if canvas_crs.isValid() and canvas_crs != wgs84:
            point_geom.transform(QgsCoordinateTransform(wgs84, canvas_crs, QgsProject.instance()))
        canvas_point = point_geom.asPoint()
        marker = QgsVertexMarker(canvas)
        marker.setCenter(QgsPointXY(canvas_point))
        marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
        marker.setIconSize(16)
        marker.setPenWidth(4)
        marker.setColor(QColor(255, 23, 68))
        self.confirmed_point_marker = marker
        marker.show()
        canvas.refresh()

    def _show_confirmed_visuals(self, point_wgs84, uncertainty_m):
        """Mostra il punto persistente e, per la riga selezionata, il cerchio blu."""
        self._clear_confirmed_uncertainty_band()
        self._show_confirmed_point_marker(point_wgs84)
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        point_geom = QgsGeometry.fromPointXY(QgsPointXY(point_wgs84))
        if canvas_crs.isValid() and canvas_crs != wgs84:
            point_geom.transform(QgsCoordinateTransform(wgs84, canvas_crs, QgsProject.instance()))
        canvas_point = point_geom.asPoint()

        try:
            radius = max(0.0, float(uncertainty_m or 0.0))
            if radius > 0:
                metric = local_metric_crs(point_wgs84)
                metric_geom = QgsGeometry.fromPointXY(QgsPointXY(point_wgs84))
                metric_geom.transform(QgsCoordinateTransform(wgs84, metric, QgsProject.instance()))
                circle = metric_geom.buffer(radius, 48)
                if canvas_crs != metric:
                    circle.transform(QgsCoordinateTransform(metric, canvas_crs, QgsProject.instance()))
                band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
                band.setColor(QColor(41, 182, 246, 230))
                band.setFillColor(QColor(41, 182, 246, 40))
                band.setWidth(2)
                band.setToGeometry(circle, None)
                band.show()
                self.confirmed_uncertainty_band = band
        except Exception:
            pass
        canvas.refresh()

    @staticmethod
    def _normalized_field_name(value):
        text = str(value or "").strip().casefold()
        return re.sub(r"[^a-z0-9]+", "", text)

    def _resolve_reuse_target_fields(self, layer):
        """Risoluzione prudente dei campi di output per la copia rapida."""
        defaults = self._load_confirm_point_defaults() or {}
        names = [field.name() for field in layer.fields()]
        normalized = {self._normalized_field_name(name): name for name in names}

        def choose(default_key, aliases, required=False):
            configured = defaults.get(default_key)
            if configured in names:
                return configured
            for alias in aliases:
                found = normalized.get(self._normalized_field_name(alias))
                if found:
                    return found
            if required:
                raise ValueError(
                    "Campi coordinate non configurati. Conferma una volta un punto oppure "
                    "crea i campi coordinata X e coordinata Y."
                )
            return ""

        return {
            "x_field": choose("x_field", ("coordinata X", "coordinate X", "longitude", "decimalLongitude", "lon", "x"), True),
            "y_field": choose("y_field", ("coordinata Y", "coordinate Y", "latitude", "decimalLatitude", "lat", "y"), True),
            "dem_field": choose("dem_field", ("quota DEM", "altitude DEM", "elevation DEM", "altitude_m")),
            "uncertainty_field": choose("uncertainty_field", ("incertezza GBIF (m)", "incertezza GBIF", "coordinateUncertaintyInMeters", "uncert_m")),
            "model_radius_field": choose("model_radius_field", ("incertezza R55 S70", "incertezza R55-S70", "R55 S70", "model_r_m")),
        }

    def _confirmed_result_rows(self):
        layer = self._confirmed_results_layer()
        rows = []
        for feature in layer.getFeatures():
            row = {"_feature_id": feature.id()}
            for field in layer.fields():
                name = field.name()
                try:
                    row[name] = feature[name]
                except Exception:
                    row[name] = None
            rows.append(row)
        rows.sort(key=lambda item: str(item.get("confirmed") or ""), reverse=True)
        return layer, rows

    def reuse_confirmed_point(self):
        """Copia una georeferenziazione confermata nel record selezionato.

        La funzione non esegue geocoding, DEM, scoring, raffinamento o heatmap.
        Riutilizza esclusivamente il risultato già validato dall'utente.
        """
        layer = self._valid_input_or_active_layer()
        if layer is None or not self._layer_supports_fields(layer):
            self._warn("Nessun layer attivo compatibile.")
            return
        target_feature = self._selected_feature()
        if target_feature is None:
            self._warn("Seleziona la riga di destinazione prima di copiare il punto.")
            return

        try:
            _, rows = self._confirmed_result_rows()
            # Non proporre come sorgente lo stesso record del layer corrente.
            rows = [
                row for row in rows
                if not (str(row.get("source_lyr") or "") == layer.id()
                        and int(row.get("source_fid") or -1) == int(target_feature.id()))
            ]
            if not rows:
                self._warn("Non sono presenti altri punti confermati da copiare.")
                return

            dialog = ReuseConfirmedPointDialog(rows, self.iface.mainWindow())
            if dialog.exec_() != QDialog.Accepted:
                self.dock.set_status("Copia del punto annullata.")
                return
            source = dialog.selected_row()
            if not source:
                self._warn("Nessun punto confermato selezionato.")
                return

            lon = float(source.get("longitude"))
            lat = float(source.get("latitude"))
            point_wgs84 = QgsPointXY(lon, lat)
            target_fields = self._resolve_reuse_target_fields(layer)
            vals = {
                **target_fields,
                "x": lon,
                "y": lat,
                "dem": source.get("altitude_m"),
                "uncertainty": source.get("uncert_m"),
                "model_radius": source.get("model_r_m"),
            }

            target_taxon_field = getattr(self.mapping, "scientific_name", None) if self.mapping else None
            target_taxon = self._feature_text(target_feature, target_taxon_field)
            source_taxon = str(source.get("taxon") or "")
            warning = ""
            if target_taxon and source_taxon and target_taxon.casefold() != source_taxon.casefold():
                warning = (
                    "\n\nAttenzione: il taxon del record sorgente è diverso. "
                    "Coordinate e incertezze verranno copiate, ma GSS ed ecologia "
                    "non vengono ricalcolati."
                )

            summary = (
                "Copiare questa georeferenziazione nel record selezionato?\n\n"
                f"Taxon sorgente: {source_taxon or '-'}\n"
                f"Località: {source.get('locality') or '-'}\n"
                f"Comune: {source.get('municipality') or '-'}\n"
                f"Coordinate: {lat:.6f}, {lon:.6f}\n"
                f"Quota DEM: {source.get('altitude_m') if source.get('altitude_m') is not None else '-'} m\n"
                f"Incertezza GBIF: {source.get('uncert_m') if source.get('uncert_m') is not None else '-'} m\n"
                f"R55–S70: {source.get('model_r_m') if source.get('model_r_m') is not None else '-'} m"
                + warning
            )
            reply = QMessageBox.question(
                self.iface.mainWindow(),
                "Copia punto già confermato",
                summary,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.dock.set_status("Copia del punto annullata.")
                return

            previous_candidate = self.current_selected_candidate
            previous_result = self.current_suitability_result
            previous_selection = self.current_selection_metadata
            try:
                self.current_selected_candidate = {
                    "rank": source.get("rank"),
                    "score": source.get("gss"),
                    "final_score": source.get("gss"),
                    "raw_score": source.get("raw_score"),
                    "confidence": source.get("confidence"),
                    "substrate_group": source.get("substrate"),
                    "pipeline": source.get("pipeline"),
                    "altitude": source.get("altitude_m"),
                    "point": point_wgs84,
                }
                self.current_suitability_result = {
                    "selected_candidate": dict(self.current_selected_candidate),
                    "selected_point": point_wgs84,
                }
                self.current_selection_metadata = {
                    "selection_method": "reused_confirmed_point",
                    "selected_rank": source.get("rank"),
                    "selected_score": source.get("gss"),
                    "selected_raw_score": source.get("raw_score"),
                    "selected_reason": "copied_from_confirmed_record",
                    "source_confirmed_feature_id": source.get("_feature_id"),
                    "source_layer_id": source.get("source_lyr"),
                    "source_feature_id": source.get("source_fid"),
                    "point_changed_by_gbif": False,
                }
                self._write_confirmed_point_to_feature(
                    layer, target_feature, vals, snapped_point_wgs84=point_wgs84
                )
            finally:
                self.current_selected_candidate = previous_candidate
                self.current_suitability_result = previous_result
                self.current_selection_metadata = previous_selection

            self._clear_confirmed_uncertainty_band()
            self._show_confirmed_point_marker(point_wgs84)
            self.dock.set_status(
                "Punto confermato copiato senza rieseguire l’analisi."
            )
        except Exception as exc:
            self._warn(f"Copia del punto fallita: {exc}")

    def start_confirm_point_capture(self):
        """Attiva la selezione con snap a un candidato del ranking.

        Questa funzione è solo UI/scrittura attributi: non modifica buffer,
        scoring, ITALIC, quota o pipeline ecologica.
        """
        layer = self._valid_input_or_active_layer()
        if layer is None or not self._layer_supports_fields(layer):
            self._warn('Nessun layer attivo compatibile.')
            return

        self.active_layer = layer
        feature = self._selected_feature()
        if feature is None:
            self._warn('Seleziona una riga nella tabella prima di confermare il punto.')
            return

        # Il cerchio di incertezza appartiene esclusivamente alla selezione
        # della tabella. Durante la conferma viene nascosto e non deve essere
        # ricreato automaticamente al termine della scrittura.
        self._clear_confirmed_visuals()

        canvas = self.iface.mapCanvas()

        try:
            if self.confirm_point_tool is not None:
                self.confirm_point_tool.canvasClicked.disconnect(self._on_confirm_point_clicked)
                try:
                    self.confirm_point_tool.canvasMoved.disconnect(self._on_confirm_point_moved)
                except Exception:
                    pass
        except Exception:
            pass

        self.confirm_point_tool = CandidateSnapMapTool(canvas)
        self.confirm_point_tool.canvasClicked.connect(self._on_confirm_point_clicked)
        self.confirm_point_tool.canvasMoved.connect(self._on_confirm_point_moved)
        canvas.setMapTool(self.confirm_point_tool)

        self.dock.set_status(
            'Muovi il cursore vicino ai candidati: il quadrato azzurro mostra lo snap. Clicca per confermare.'
        )

    def _nearest_confirm_candidate(self, canvas_point):
        """Restituisce candidato, distanza metrica e punto click WGS84."""
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        geom_click = QgsGeometry.fromPointXY(QgsPointXY(canvas_point))
        if canvas_crs.isValid() and canvas_crs != wgs84:
            geom_click.transform(
                QgsCoordinateTransform(canvas_crs, wgs84, QgsProject.instance())
            )
        click_wgs84 = geom_click.asPoint()

        candidates = (self.current_suitability_result or {}).get("display_features") or (self.current_suitability_result or {}).get("features") or []
        selected = None
        selected_distance = None
        for row in candidates:
            candidate_point = row.get("point")
            if candidate_point is None:
                continue
            try:
                distance = self.habitat_suitability_service.uncertainty_service._distance_m(
                    QgsPointXY(click_wgs84), candidate_point
                )
            except Exception:
                continue
            if distance is not None and (selected_distance is None or distance < selected_distance):
                selected = row
                selected_distance = float(distance)
        return selected, selected_distance, click_wgs84

    def _on_confirm_point_moved(self, point):
        """Mostra in tempo reale il candidato verso cui il cursore farà snap."""
        try:
            selected, distance, _ = self._nearest_confirm_candidate(point)
            if selected is None or selected.get("point") is None:
                self._clear_confirm_snap_marker()
                return
            self._show_confirm_snap_marker(selected.get("point"))
            rank = int(selected.get("rank") or 0)
            score = float(selected.get("score") or 0.0)
            self.dock.set_status(
                f'Snap → candidato rank {rank} (score {score:.2f}, distanza {distance:.1f} m). '
                'Clicca per selezionarlo.'
            )
        except Exception:
            pass

    def _on_confirm_point_clicked(self, point, button=None):
        """Aggancia il click al candidato più vicino e ricalcola l’incertezza."""
        layer = self._valid_input_or_active_layer()
        feature = self._selected_feature()
        if layer is None or feature is None:
            self._warn('Nessun record selezionato.')
            return

        try:
            canvas = self.iface.mapCanvas()
            canvas_crs = canvas.mapSettings().destinationCrs()
            layer_crs = layer.crs()

            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            suitability = self.current_suitability_result or {}
            candidates = suitability.get("display_features") or suitability.get("features") or []
            if not candidates:
                self._warn(
                    "Non sono disponibili candidati da agganciare. "
                    "Esegui prima Trova punto più probabile."
                )
                return

            selected, selected_distance, click_wgs84 = self._nearest_confirm_candidate(point)

            if selected is None or selected.get("point") is None:
                self._warn("Impossibile agganciare il click a un candidato.")
                return

            snapped_point = selected.get("point")
            selected_score = float(selected.get("score") or 0.0)
            selected_rank = int(selected.get("rank") or 0)
            self.current_selected_candidate = selected
            self._show_confirm_snap_marker(snapped_point)
            self.dock.set_status(
                f"Agganciato al candidato rank {selected_rank} "
                f"(score {selected_score:.2f}, distanza dal click {selected_distance:.1f} m)."
            )

            # Calcola separatamente l'incertezza geografica GBIF point-radius e il
            # raggio locale pesato R55-S70 del modello rispetto al candidato scelto.
            uncertainty = self.habitat_suitability_service.uncertainty_service.estimate(
                self.current_boundary,
                candidates,
                gbif_extent_geom=self.original_locality_extent,
                best_point=snapped_point,
                grid_step_m=suitability.get("grid_step_m") or self._get_suitability_grid_step(),
                selected_score=selected_score,
                selected_rank=selected_rank,
                center_source="user_selected_candidate",
                locality_context=self.current_locality_context,
                resolved_locality=self.current_resolved_locality,
            )
            uncertainty_m = float(uncertainty.get("coordinate_uncertainty_m") or uncertainty.get("uncertainty_m") or 0.0)

            # Coordinate da scrivere nel CRS del layer del cartellino.
            geom_snapped_wgs84 = QgsGeometry.fromPointXY(snapped_point)
            geom_layer = QgsGeometry(geom_snapped_wgs84)
            if layer_crs.isValid() and layer_crs != wgs84:
                geom_layer.transform(
                    QgsCoordinateTransform(wgs84, layer_crs, QgsProject.instance())
                )
            pt_layer = geom_layer.asPoint()

            # Campiona il DEM sul candidato agganciato.
            geom_snapped_canvas = QgsGeometry(geom_snapped_wgs84)
            if canvas_crs.isValid() and canvas_crs != wgs84:
                geom_snapped_canvas.transform(
                    QgsCoordinateTransform(wgs84, canvas_crs, QgsProject.instance())
                )
            snapped_canvas_point = geom_snapped_canvas.asPoint()

            # La quota già calcolata durante il ranking è la fonte primaria:
            # è stata ottenuta con la stessa logica multi-DEM usata per quota,
            # pendenza ed esposizione del candidato. Se non è disponibile,
            # si esegue un nuovo campionamento sui DEM selezionati.
            selected_env = selected.get("env") or {}
            dem_value = selected_env.get("altitude")
            try:
                dem_value = float(dem_value)
                if not math.isfinite(dem_value):
                    dem_value = None
            except Exception:
                dem_value = None

            if dem_value is None:
                # Campionamento diretto sul punto candidato in WGS84. Evita
                # passaggi intermedi nel CRS del canvas e sceglie il tassello
                # DEM che contiene realmente il punto.
                dem_value = self._sample_dem_at_confirm_point(
                    snapped_point, wgs84
                )
            else:
                self.current_confirm_dem_source = (
                    selected_env.get("dem_source") or None
                )

            defaults = self._load_confirm_point_defaults()
            defaults["uncertainty"] = uncertainty_m

            fields = [f.name() for f in layer.fields()]
            dlg = ConfirmPointDialog(
                fields=fields,
                x_value=round(float(pt_layer.x()), 6),
                y_value=round(float(pt_layer.y()), 6),
                dem_value=None if dem_value is None else round(float(dem_value), 2),
                defaults=defaults,
                parent=self.iface.mainWindow(),
                candidate_rank=selected_rank,
                candidate_score=selected_score,
                snap_distance_m=selected_distance,
                uncertainty_info=uncertainty,
                locality_context=self.current_locality_context,
                ecological_point_wgs84=snapped_point,
                explainability_report=self.explainability_service.build_report(
                    selected, candidates, self.current_locality_context, uncertainty
                ),
                iface=self.iface,
                candidate_dem_value=dem_value,
            )

            # Il dialogo di conferma viene mostrato senza modalità applicativa.
            # Un QDialog.exec_() renderebbe modale l'intera applicazione e
            # impedirebbe a un QgsMapTool aperto dalla validazione di ricevere
            # i click sul canvas. Il QEventLoop locale mantiene invece il
            # flusso sincrono del controller senza bloccare la mappa.
            confirm_loop = QEventLoop()
            dlg.finished.connect(confirm_loop.quit)
            dlg.setWindowModality(Qt.NonModal)
            dlg.setModal(False)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            confirm_loop.exec_()

            if dlg.result() != QDialog.Accepted:
                self._clear_confirm_snap_marker()
                self.dock.set_status('Conferma candidato annullata.')
                return

            vals = dlg.values()
            self._save_confirm_point_defaults(vals)

            corrected_lon = uncertainty.get("corrected_center_lon")
            corrected_lat = uncertainty.get("corrected_center_lat")
            corrected_text = "non calcolabile"
            if corrected_lon is not None and corrected_lat is not None:
                corrected_text = f"{float(corrected_lat):.6f}, {float(corrected_lon):.6f}"
            locality_type = getattr(self.current_locality_context, "locality_type", "unknown") or "unknown"
            geometry_type = getattr(self.current_locality_context, "geometry_type", "unknown") or "unknown"

            msg = (
                f"Usare il candidato rank {selected_rank} come posizione finale?\n\n"
                "RISULTATO ECOLOGICO\n"
                f"GSS candidato: {round(selected_score, 2)}\n"
                f"Distanza click-candidato: {round(selected_distance, 1)} m\n"
                f"{vals['x_field']}: {vals['x']}\n"
                f"{vals['y_field']}: {vals['y']}\n"
            )
            if vals.get("dem_field"):
                msg += f"{vals['dem_field']}: {vals['dem']}\n"
            model_confidence = uncertainty.get('model_confidence') or uncertainty.get('confidence') or '-'
            locality_label = ConfirmPointDialog._locality_type_label(locality_type)
            geometry_label = ConfirmPointDialog._geometry_type_label(geometry_type)
            center_method_label = ConfirmPointDialog._center_method_label(
                uncertainty.get('corrected_center_method')
            )
            confidence_label = ConfirmPointDialog._model_confidence_label(model_confidence)
            confidence_index = uncertainty.get('model_confidence_index')
            if confidence_index is None:
                confidence_index = uncertainty.get('model_confidence_score')
            try:
                confidence_text = f"{float(confidence_index):.0f}% ({confidence_label})"
            except Exception:
                confidence_text = confidence_label
            center_distance_text = ConfirmPointDialog._center_distance_text(
                corrected_lon, corrected_lat, snapped_point
            )

            msg += f"Raggio del modello R55-S70: {float(uncertainty.get('model_radius_m') or 0):.1f} m\n"
            msg += f"Affidabilità del modello (MCI): {confidence_text}\n"
            for reason in (uncertainty.get('model_confidence_reasons') or [])[:3]:
                msg += f"- {reason}\n"
            msg += "\n"
            msg += "GEOREFERENZIAZIONE GBIF\n"
            msg += f"Tipo di località: {locality_label} ({geometry_label})\n"
            msg += f"Centro corretto GBIF: {corrected_text}\n"
            msg += f"Distanza dal punto GeoLichen: {center_distance_text}\n"
            msg += f"Incertezza geografica GBIF: {vals['uncertainty']} m\n"
            msg += "L'incertezza è calcolata esclusivamente sulla geometria documentale SLGE.\n"
            if uncertainty.get("slge_active"):
                try:
                    gci_text = f"{float(uncertainty.get('slge_geometry_confidence') or 0) * 100.0:.0f}%"
                except Exception:
                    gci_text = "-"
                msg += f"Sorgente geometria documentale: {uncertainty.get('slge_documented_source') or '-'}\n"
                msg += f"Metodo geometria documentale: {uncertainty.get('slge_documented_method') or '-'}\n"
                msg += f"Geometry Confidence Index: {gci_text}\n"
                if uncertainty.get("slge_requires_review"):
                    msg += "Verifica manuale geometria: richiesta\n"
            if uncertainty.get("terrain_reconstruction_available"):
                terrain_status = "utilizzata" if uncertainty.get("terrain_reconstruction_used") else "fallback semantico"
                msg += "\nRICOSTRUZIONE MORFOLOGICA\n"
                msg += f"Esito: {terrain_status}\n"
                if uncertainty.get("terrain_summit_elevation_m") is not None:
                    msg += f"Quota cima: {float(uncertainty.get('terrain_summit_elevation_m')):.1f} m\n"
                if uncertainty.get("terrain_polygon_area_km2") is not None:
                    msg += f"Area poligono: {float(uncertainty.get('terrain_polygon_area_km2')):.3f} km²\n"
                if uncertainty.get("terrain_validation_confidence") is not None:
                    msg += f"Confidenza validazione: {float(uncertainty.get('terrain_validation_confidence')) * 100.0:.0f}%\n"
                if uncertainty.get("terrain_manual_review_required"):
                    msg += "Revisione manuale terrain: richiesta\n"
            msg += f"Metodo di calcolo del centro: {center_method_label}"


            reply = QMessageBox.question(
                self.iface.mainWindow(),
                'Usa questo candidato',
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self._clear_confirm_snap_marker()
                self.dock.set_status('Scrittura annullata.')
                return

            self.current_selection_metadata = {
                "selection_method": "manual_candidate_selection",
                "selected_rank": selected_rank,
                "selected_score": selected_score,
                "selected_raw_score": selected.get("raw_score"),
                "selected_reason": "user_confirmed_snapped_candidate",
                "manual_snap_distance_m": selected_distance,
                "point_changed_by_gbif": False,
            }
            if self.current_suitability_result is not None:
                self.current_suitability_result["selection"] = dict(self.current_selection_metadata)
                self.current_suitability_result["selected_point"] = snapped_point
                self.current_suitability_result["selected_candidate"] = selected
                self._update_candidate_selection_layer(selected, self.current_selection_metadata)

            self._write_confirmed_point_to_feature(layer, feature, vals, snapped_point_wgs84=snapped_point)
            # Il punto confermato resta sempre visibile. Il cerchio blu è invece
            # legato alla selezione della riga e ricompare al successivo evento
            # reale di selezione nella tabella attributi.
            self._clear_confirmed_uncertainty_band()
            self._show_confirmed_point_marker(snapped_point)
            self._clear_confirm_snap_marker()

            try:
                if self.confirm_point_tool is not None:
                    self.confirm_point_tool.canvasClicked.disconnect(self._on_confirm_point_clicked)
                try:
                    self.confirm_point_tool.canvasMoved.disconnect(self._on_confirm_point_moved)
                except Exception:
                    pass
                self.confirm_point_tool = None
            except Exception:
                pass

        except Exception as exc:
            self._warn(f'Conferma punto fallita: {exc}')

    def _sample_dem_at_confirm_point(self, canvas_point, canvas_crs):
        sample = self._sample_first_valid_dem(canvas_point, canvas_crs)
        if sample is None:
            self.current_confirm_dem_source = None
            return None
        self.current_confirm_dem_source = sample.get("source")
        return sample.get("value")


    def _confirmed_results_layer(self):
        """Restituisce o crea il layer puntuale cumulativo dei risultati confermati.

        Il layer non viene eliminato quando cambia la riga o quando parte una nuova
        analisi. Ogni conferma aggiunge (o aggiorna) una feature reale, distinta dai
        marker e dai rubber band temporanei del canvas.
        """
        project = QgsProject.instance()
        layer = None

        if self.confirmed_results_layer_id:
            layer = project.mapLayer(self.confirmed_results_layer_id)
            if layer is not None and layer.isValid():
                return layer

        for candidate in project.mapLayers().values():
            try:
                if candidate.customProperty('geolichen/confirmed_results', False):
                    self.confirmed_results_layer_id = candidate.id()
                    return candidate
            except Exception:
                pass

        layer = QgsVectorLayer(
            'Point?crs=EPSG:4326',
            'GeoLichen – Punti confermati',
            'memory',
        )
        if not layer.isValid():
            raise ValueError('Impossibile creare il layer dei punti confermati')

        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField('source_lyr', QVariant.String, len=120),
            QgsField('source_fid', QVariant.LongLong),
            QgsField('record_id', QVariant.String, len=120),
            QgsField('taxon', QVariant.String, len=255),
            QgsField('locality', QVariant.String, len=255),
            QgsField('municipality', QVariant.String, len=160),
            QgsField('rank', QVariant.Int),
            QgsField('gss', QVariant.Double),
            QgsField('raw_score', QVariant.Double),
            QgsField('confidence', QVariant.Double),
            QgsField('uncert_m', QVariant.Double),
            QgsField('model_r_m', QVariant.Double),
            QgsField('altitude_m', QVariant.Double),
            QgsField('substrate', QVariant.String, len=80),
            QgsField('pipeline', QVariant.String, len=80),
            QgsField('longitude', QVariant.Double),
            QgsField('latitude', QVariant.Double),
            QgsField('confirmed', QVariant.String, len=32),
        ])
        layer.updateFields()
        layer.setCustomProperty('geolichen/confirmed_results', True)
        layer.setCustomProperty('geolichen/schema_version', '15.5.0')

        try:
            symbol = QgsMarkerSymbol.createSimple({
                'name': 'circle',
                'color': '255,241,118,255',
                'outline_color': '35,35,35,255',
                'outline_width': '0.55',
                'size': '3.6',
                'size_unit': 'MM',
            })
            layer.renderer().setSymbol(symbol)
            layer.setDisplayExpression(
                "concat(coalesce(\"taxon\", 'Record'), ' — ', coalesce(\"locality\", ''))"
            )
        except Exception:
            pass

        project.addMapLayer(layer)
        self.confirmed_results_layer_id = layer.id()
        return layer

    def _feature_text(self, feature, field_name):
        """Legge in sicurezza un attributo configurato dal record sorgente."""
        if feature is None or not field_name:
            return ''
        try:
            value = feature[field_name]
            return '' if value is None else str(value)
        except Exception:
            return ''

    def _append_confirmed_result(self, source_layer, source_feature, vals, point_wgs84):
        """Aggiunge il punto finale al layer cumulativo, aggiornando i duplicati."""
        if point_wgs84 is None:
            return

        result_layer = self._confirmed_results_layer()
        provider = result_layer.dataProvider()
        selected = {}
        if isinstance(self.current_selected_candidate, dict):
            selected = dict(self.current_selected_candidate)
        if isinstance(self.current_suitability_result, dict):
            selected = dict(self.current_suitability_result.get('selected_candidate') or selected)
        selection = dict(self.current_selection_metadata or {})

        taxon_field = getattr(self.mapping, 'scientific_name', None) if self.mapping else None
        locality_field = getattr(self.mapping, 'locality', None) if self.mapping else None
        municipality_field = getattr(self.mapping, 'municipality', None) if self.mapping else None

        source_layer_id = source_layer.id() if source_layer is not None else ''
        source_fid = int(source_feature.id()) if source_feature is not None else -1
        record_id = ''
        try:
            record_id = str(source_feature.id())
        except Exception:
            pass

        def numeric(*values):
            for value in values:
                try:
                    if value is not None and value != '':
                        return float(value)
                except Exception:
                    continue
            return None

        attrs = {
            'source_lyr': source_layer_id,
            'source_fid': source_fid,
            'record_id': record_id,
            'taxon': self._feature_text(source_feature, taxon_field),
            'locality': self._feature_text(source_feature, locality_field),
            'municipality': self._feature_text(source_feature, municipality_field),
            'rank': int(selection.get('selected_rank') or selected.get('rank') or 0),
            'gss': numeric(selection.get('selected_score'), selected.get('final_score'), selected.get('score')),
            'raw_score': numeric(selection.get('selected_raw_score'), selected.get('raw_score')),
            'confidence': numeric(selected.get('confidence'), selected.get('model_confidence')),
            'uncert_m': numeric(vals.get('uncertainty')),
            'model_r_m': numeric(vals.get('model_radius')),
            'altitude_m': numeric(vals.get('dem'), selected.get('altitude'), selected.get('elevation')),
            'substrate': str(selected.get('substrate_group') or selected.get('substrate') or ''),
            'pipeline': str(selected.get('pipeline') or selected.get('ecological_pipeline') or ''),
            'longitude': float(point_wgs84.x()),
            'latitude': float(point_wgs84.y()),
            'confirmed': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
        }

        geometry = QgsGeometry.fromPointXY(QgsPointXY(point_wgs84))
        existing_id = None
        for existing in result_layer.getFeatures():
            try:
                if (str(existing['source_lyr']) == source_layer_id and
                        int(existing['source_fid']) == source_fid):
                    existing_id = existing.id()
                    break
            except Exception:
                continue

        if existing_id is None:
            out = QgsFeature(result_layer.fields())
            out.setGeometry(geometry)
            for name, value in attrs.items():
                out[name] = value
            ok, _ = provider.addFeatures([out])
            if not ok:
                raise ValueError('Impossibile aggiungere il punto al layer dei risultati confermati')
        else:
            provider.changeGeometryValues({existing_id: geometry})
            changes = {}
            for name, value in attrs.items():
                idx = result_layer.fields().indexOf(name)
                if idx >= 0:
                    changes[idx] = value
            provider.changeAttributeValues({existing_id: changes})

        result_layer.updateExtents()
        result_layer.triggerRepaint()
        try:
            result_layer.setSubsetString('')
        except Exception:
            pass

    def _write_confirmed_point_to_feature(self, layer, feature, vals, snapped_point_wgs84=None):
        """Scrive valori e, se possibile, sposta la geometria sul candidato agganciato."""
        if layer is None or feature is None:
            raise ValueError('Layer o feature non disponibile')

        field_map = {
            vals.get("x_field"): vals.get("x"),
            vals.get("y_field"): vals.get("y"),
            vals.get("uncertainty_field"): vals.get("uncertainty"),
            vals.get("model_radius_field"): vals.get("model_radius"),
        }
        if vals.get("dem_field"):
            field_map[vals.get("dem_field")] = vals.get("dem")

        field_map = {k: v for k, v in field_map.items() if k}

        if not field_map:
            raise ValueError('Nessun campo selezionato per la scrittura')

        started_editing = False
        if not layer.isEditable():
            started_editing = layer.startEditing()


        # Per un layer vettoriale puntuale, lo snap non aggiorna soltanto X/Y:
        # sposta anche la geometria effettiva della feature sul candidato.
        if snapped_point_wgs84 is not None:
            try:
                if QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PointGeometry:
                    geom = QgsGeometry.fromPointXY(QgsPointXY(snapped_point_wgs84))
                    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                    if layer.crs().isValid() and layer.crs() != wgs84:
                        geom.transform(
                            QgsCoordinateTransform(wgs84, layer.crs(), QgsProject.instance())
                        )
                    layer.changeGeometry(feature.id(), geom)
            except Exception as exc:
                raise ValueError(f'Impossibile applicare lo snap alla geometria: {exc}')

        for field_name, value in field_map.items():
            idx = layer.fields().indexOf(field_name)
            if idx < 0:
                raise ValueError(f'Campo non trovato: {field_name}')
            layer.changeAttributeValue(feature.id(), idx, value)

        if started_editing:
            ok = layer.commitChanges()
            if not ok:
                raise ValueError('Commit modifiche fallito: ' + '; '.join(layer.commitErrors()))

        if snapped_point_wgs84 is not None:
            self._append_confirmed_result(layer, feature, vals, snapped_point_wgs84)

        layer.triggerRepaint()
        self.dock.set_status('Candidato confermato e aggiunto al layer GeoLichen – Punti confermati.')



    def _estimate_current_boundary_radius_m(self):
        """Stima il raggio del boundary corrente. Fallback: Buffer manuale."""
        try:
            if self.current_boundary is None or self.current_boundary.isEmpty():
                return self._manual_buffer_radius()

            src = QgsCoordinateReferenceSystem("EPSG:4326")
            center_wgs84 = self.current_boundary.centroid().asPoint()
            dst = local_metric_crs(center_wgs84)
            geom = QgsGeometry(self.current_boundary)
            geom.transform(QgsCoordinateTransform(src, dst, QgsProject.instance()))
            rect = geom.boundingBox()
            radius = max(float(rect.width()), float(rect.height())) / 2.0
            if radius > 0:
                return radius
        except Exception:
            pass
        return self._manual_buffer_radius()

    def start_redefine_buffer_capture(self):
        """Ridefinisce il boundary corrente senza modificare geocoder/scoring/ITALIC.

        Il buffer precedente resta valido finché il nuovo non viene confermato.
        """
        if self.mapping is None:
            self._warn('Configura prima i campi input.')
            return

        layer = self._valid_input_or_active_layer()
        if layer is None or not self._layer_supports_fields(layer):
            self._warn('Nessun layer attivo compatibile.')
            return

        self.active_layer = layer
        feature = self._selected_feature()
        if feature is None:
            self._warn('Seleziona una riga nella tabella prima di ridefinire il buffer.')
            return

        if self.search_geometry_mode != "manual" or self.manual_search_extent is None or self.manual_search_extent.isEmpty():
            self._warn('Prima crea una zona manuale con “Punto manuale + buffer”. Ridefinisci buffer non modifica la Search Geometry automatica.')
            return

        current_radius = float(self.manual_search_radius_m or self._estimate_current_boundary_radius_m())
        dlg = RedefineBufferDialog(current_radius_m=current_radius, parent=self.iface.mainWindow())
        if not dlg.exec_():
            self.dock.set_status('Ridefinizione buffer annullata.')
            return

        vals = dlg.values()
        radius = current_radius if vals.get("mode") == "move" else vals.get("radius_m")
        self.redefine_buffer_feature = feature
        self.redefine_buffer_radius_m = float(radius)

        canvas = self.iface.mapCanvas()
        try:
            if self.redefine_buffer_tool is not None:
                self.redefine_buffer_tool.canvasClicked.disconnect(self._on_redefine_buffer_clicked)
        except Exception:
            pass

        self.redefine_buffer_tool = QgsMapToolEmitPoint(canvas)
        self.redefine_buffer_tool.canvasClicked.connect(self._on_redefine_buffer_clicked)
        canvas.setMapTool(self.redefine_buffer_tool)

        self.dock.set_status(
            f'Clicca sulla mappa il nuovo centro del buffer. Raggio: {float(radius):g} m.'
        )

    def _on_redefine_buffer_clicked(self, point, button=None):
        """Crea un nuovo buffer candidato e lo applica solo dopo conferma."""
        feature = self.redefine_buffer_feature or self._selected_feature()
        if feature is None:
            self._warn('Nessun record selezionato per ridefinire il buffer.')
            return

        radius_m = float(self.redefine_buffer_radius_m or self._manual_buffer_radius())
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')

        try:
            point_geom = QgsGeometry.fromPointXY(QgsPointXY(point))
            center_wgs84_geom = QgsGeometry(point_geom)
            if canvas_crs != wgs84:
                center_wgs84_geom.transform(
                    QgsCoordinateTransform(canvas_crs, wgs84, QgsProject.instance())
                )
            center_wgs84 = QgsPointXY(center_wgs84_geom.asPoint())
            metric_crs = local_metric_crs(center_wgs84)

            point_metric = QgsGeometry(center_wgs84_geom)
            point_metric.transform(
                QgsCoordinateTransform(wgs84, metric_crs, QgsProject.instance())
            )

            buffer_metric = point_metric.buffer(radius_m, 48)
            to_wgs84 = QgsCoordinateTransform(metric_crs, wgs84, QgsProject.instance())
            new_boundary = QgsGeometry(buffer_metric)
            new_boundary.transform(to_wgs84)

            reply = QMessageBox.question(
                self.iface.mainWindow(),
                'Conferma ridefinizione buffer',
                (
                    f'Sostituire il buffer corrente con un nuovo buffer di {radius_m:g} m?\\n\\n'
                    'Dopo la conferma GeoLichen riapplicherà la stessa pipeline ecologica '
                    'usata dal punto manuale: litologia solo se pertinente, suolo, foreste, quota e diagnostica.'
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.dock.set_status('Ridefinizione buffer annullata. Il buffer precedente è rimasto invariato.')
                return

            try:
                if self.redefine_buffer_tool is not None:
                    self.redefine_buffer_tool.canvasClicked.disconnect(self._on_redefine_buffer_clicked)
                self.redefine_buffer_tool = None
            except Exception:
                pass

            # Aggiorna esclusivamente la geometria manuale; il ramo automatico resta intatto.
            try:
                self.manual_search_center_wgs84 = QgsPointXY(center_wgs84_geom.asPoint())
            except Exception:
                self.manual_search_center_wgs84 = None
            self._analyze_manual_boundary(feature, new_boundary, radius_m)
            self.dock.set_status('Buffer ridefinito e pipeline ecologica riapplicata.')

        except Exception as exc:
            self._warn(f'Ridefinizione buffer fallita: {exc}')


    def _cleanup_manual_point_capture(self, restore_previous=True):
        """Disattiva in sicurezza lo strumento del punto manuale."""
        canvas = self.iface.mapCanvas()
        tool = self.manual_point_tool
        try:
            if tool is not None:
                tool.canvasClicked.disconnect(self._on_manual_map_point_clicked)
        except Exception:
            pass
        try:
            if tool is not None and canvas.mapTool() is tool:
                if restore_previous and self.manual_point_previous_tool is not None:
                    canvas.setMapTool(self.manual_point_previous_tool)
                else:
                    canvas.unsetMapTool(tool)
        except Exception:
            pass
        self.manual_point_tool = None
        self.manual_point_previous_tool = None
        self.manual_point_feature = None
        if getattr(self, 'active_manual_capture_mode', None) == 'point':
            self.active_manual_capture_mode = None

    def _cancel_active_manual_capture(self, restore_previous=True):
        """Annulla qualsiasi strumento manuale IN CORSO senza toccare il boundary confermato.

        Punto e linea sono mutuamente esclusivi. Questa funzione elimina soltanto
        tool, vertici e rubber band temporanei: non cancella una Search Geometry
        manuale già costruita.
        """
        had_point = self.manual_point_tool is not None
        had_line = self.manual_line_tool is not None
        if had_point:
            self._cleanup_manual_point_capture(restore_previous=restore_previous)
        if had_line:
            self._cleanup_manual_line_capture(restore_previous=restore_previous)
        self.active_manual_capture_mode = None
        try:
            if hasattr(self.dock, 'btnManualPoint'):
                self.dock.btnManualPoint.setText('Punto manuale + buffer')
            if hasattr(self.dock, 'btnManualLine'):
                self.dock.btnManualLine.setText('Linea manuale + offset')
        except Exception:
            pass
        return had_point or had_line

    def start_manual_point_capture(self):
        """Attiva un vero click su mappa e crea il boundary senza richiederne uno preesistente."""
        if self.mapping is None:
            self._warn('Configura prima i campi input.')
            return

        layer = self._valid_input_or_active_layer()
        if layer is None or not self._layer_supports_fields(layer):
            self._warn('Nessun layer attivo compatibile')
            return

        self.active_layer = layer
        feature = self._selected_feature()
        if feature is None:
            self._warn('Seleziona una riga nella tabella prima di usare il punto manuale.')
            return

        radius = self._manual_buffer_radius()
        if not math.isfinite(radius) or radius <= 0:
            self._warn('Il raggio del buffer manuale deve essere maggiore di zero.')
            return

        # Secondo click sullo stesso pulsante = annulla. Utile in caso di
        # attivazione accidentale senza dover cliccare sulla mappa.
        if self.manual_point_tool is not None:
            self._cancel_active_manual_capture(restore_previous=True)
            self.dock.set_status('Modalità punto manuale annullata.')
            return

        # Punto e linea non possono restare attivi insieme. L'eventuale linea
        # incompleta viene cancellata (rubber band + vertici) senza alterare un
        # boundary già confermato.
        self._cancel_active_manual_capture(restore_previous=False)
        self.manual_point_feature = feature
        canvas = self.iface.mapCanvas()
        self.manual_point_previous_tool = canvas.mapTool()
        self.manual_point_tool = QgsMapToolEmitPoint(canvas)
        self.manual_point_tool.canvasClicked.connect(self._on_manual_map_point_clicked)
        canvas.setMapTool(self.manual_point_tool)
        self.active_manual_capture_mode = 'point'
        try:
            if hasattr(self.dock, 'btnManualPoint'):
                self.dock.btnManualPoint.setText('Annulla punto manuale')
            if hasattr(self.dock, 'btnManualLine'):
                self.dock.btnManualLine.setText('Linea manuale + offset')
        except Exception:
            pass
        try:
            canvas.setFocus()
        except Exception:
            pass

        self.dock.set_status(
            f'Modalità buffer manuale attiva: clicca il centro sulla mappa '
            f'(raggio {radius:g} m; tasto destro per annullare).'
        )



    def _manual_line_offset(self):
        """Legge l'offset laterale del corridoio manuale, in metri per lato."""
        try:
            txt = ''
            if hasattr(self.dock, 'txtManualLineOffset'):
                txt = self.dock.txtManualLineOffset.text().strip()
            value = float(str(txt).replace(',', '.')) if txt else 500.0
            return value if math.isfinite(value) and value > 0 else 500.0
        except Exception:
            return 500.0

    def _cleanup_manual_line_capture(self, restore_previous=True):
        canvas = self.iface.mapCanvas()
        tool = self.manual_line_tool
        try:
            if tool is not None:
                tool.canvasClicked.disconnect(self._on_manual_line_clicked)
        except Exception:
            pass
        try:
            if tool is not None and canvas.mapTool() is tool:
                if restore_previous and self.manual_line_previous_tool is not None:
                    canvas.setMapTool(self.manual_line_previous_tool)
                else:
                    canvas.unsetMapTool(tool)
        except Exception:
            pass
        for attr in ('manual_line_band', 'manual_line_vertex_band'):
            band = getattr(self, attr, None)
            if band is not None:
                try:
                    canvas.scene().removeItem(band)
                except Exception:
                    try:
                        band.reset()
                    except Exception:
                        pass
            setattr(self, attr, None)
        self.manual_line_tool = None
        self.manual_line_previous_tool = None
        self.manual_line_vertices = []
        self.manual_line_feature = None
        if getattr(self, 'active_manual_capture_mode', None) == 'line':
            self.active_manual_capture_mode = None

    def start_manual_line_capture(self):
        """Disegna l'asse di una valle e crea un corridoio con offset metrico scelto dall'utente.

        Click sinistro = aggiunge un vertice; click destro = termina la linea e avvia l'analisi.
        """
        if self.mapping is None:
            self._warn('Configura prima i campi input.')
            return
        layer = self._valid_input_or_active_layer()
        if layer is None or not self._layer_supports_fields(layer):
            self._warn('Nessun layer attivo compatibile')
            return
        self.active_layer = layer
        feature = self._selected_feature()
        if feature is None:
            self._warn('Seleziona una riga nella tabella prima di usare la linea manuale.')
            return
        offset_m = self._manual_line_offset()
        if not math.isfinite(offset_m) or offset_m <= 0:
            self._warn("L'offset della linea manuale deve essere maggiore di zero.")
            return

        # Secondo click sul pulsante linea = annulla immediatamente la modalità.
        # Così un'attivazione accidentale non lascia QGIS in attesa di vertici.
        if self.manual_line_tool is not None:
            self._cancel_active_manual_capture(restore_previous=True)
            self.dock.set_status('Modalità linea manuale annullata.')
            return

        # La linea esclude sempre il puntatore manuale e viceversa.
        self._cancel_active_manual_capture(restore_previous=False)
        canvas = self.iface.mapCanvas()
        self.manual_line_feature = feature
        self.manual_line_vertices = []
        self.manual_line_previous_tool = canvas.mapTool()
        self.manual_line_tool = QgsMapToolEmitPoint(canvas)
        self.manual_line_tool.canvasClicked.connect(self._on_manual_line_clicked)
        self.manual_line_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self.manual_line_vertex_band = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        try:
            self.manual_line_vertex_band.setWidth(5)
            self.manual_line_band.setWidth(3)
        except Exception:
            pass
        canvas.setMapTool(self.manual_line_tool)
        self.active_manual_capture_mode = 'line'
        try:
            if hasattr(self.dock, 'btnManualLine'):
                self.dock.btnManualLine.setText('Annulla linea manuale')
            if hasattr(self.dock, 'btnManualPoint'):
                self.dock.btnManualPoint.setText('Punto manuale + buffer')
        except Exception:
            pass
        try:
            canvas.setFocus()
        except Exception:
            pass
        self.dock.set_status(
            f'Linea manuale attiva: click sinistro per i vertici; click destro per terminare '
            f'(offset {offset_m:g} m per lato).'
        )

    def _on_manual_line_clicked(self, point, button=None):
        if button == Qt.RightButton:
            if len(self.manual_line_vertices) < 2:
                self._cancel_active_manual_capture(restore_previous=True)
                self.dock.set_status('Linea manuale annullata: servono almeno due vertici.')
                return
            try:
                self._finish_manual_line_capture()
            except Exception as exc:
                self._cleanup_manual_line_capture()
                self._warn(f'Impossibile creare il corridoio manuale. Dettaglio tecnico: {exc}')
            return
        if button not in (None, Qt.LeftButton) or point is None:
            return
        pt = QgsPointXY(point)
        self.manual_line_vertices.append(pt)
        try:
            self.manual_line_band.addPoint(pt, True)
            self.manual_line_vertex_band.addPoint(pt, True)
        except Exception:
            pass
        self.dock.set_status(
            f'Linea manuale: {len(self.manual_line_vertices)} vertici. '
            'Aggiungi punti con click sinistro; termina con click destro.'
        )

    def _finish_manual_line_capture(self):
        feature = self.manual_line_feature or self._selected_feature()
        if feature is None:
            raise ValueError('nessun record selezionato')
        if len(self.manual_line_vertices) < 2:
            raise ValueError('servono almeno due vertici')

        offset_m = self._manual_line_offset()
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        if not canvas_crs.isValid():
            raise ValueError('CRS della mappa non valido')

        line_canvas = QgsGeometry.fromPolylineXY([QgsPointXY(v) for v in self.manual_line_vertices])
        line_wgs84 = QgsGeometry(line_canvas)
        if canvas_crs != wgs84:
            line_wgs84.transform(QgsCoordinateTransform(canvas_crs, wgs84, QgsProject.instance()))
        if line_wgs84.isNull() or line_wgs84.isEmpty():
            raise ValueError('linea manuale vuota')

        centroid = line_wgs84.centroid()
        if centroid is None or centroid.isEmpty():
            raise ValueError('impossibile determinare il centro della linea')
        anchor_wgs84 = QgsPointXY(centroid.asPoint())
        metric_crs = local_metric_crs(anchor_wgs84)
        line_metric = QgsGeometry(line_wgs84)
        line_metric.transform(QgsCoordinateTransform(wgs84, metric_crs, QgsProject.instance()))
        line_length_m = float(line_metric.length())
        if not math.isfinite(line_length_m) or line_length_m <= 0:
            raise ValueError('lunghezza della linea non valida')

        corridor_metric = line_metric.buffer(float(offset_m), 32)
        if corridor_metric is None or corridor_metric.isNull() or corridor_metric.isEmpty():
            raise ValueError('corridoio generato vuoto')
        if not corridor_metric.isGeosValid():
            corridor_metric = corridor_metric.makeValid()

        # Il centro tecnico è il punto a metà della linea, non il Rank 1.
        midpoint_metric = line_metric.interpolate(line_length_m / 2.0)
        midpoint_wgs84 = QgsGeometry(midpoint_metric)
        midpoint_wgs84.transform(QgsCoordinateTransform(metric_crs, wgs84, QgsProject.instance()))
        try:
            self.manual_search_center_wgs84 = QgsPointXY(midpoint_wgs84.asPoint())
        except Exception:
            self.manual_search_center_wgs84 = anchor_wgs84

        boundary = QgsGeometry(corridor_metric)
        boundary.transform(QgsCoordinateTransform(metric_crs, wgs84, QgsProject.instance()))
        if not boundary.isGeosValid():
            boundary = boundary.makeValid()
        if boundary.isNull() or boundary.isEmpty():
            raise ValueError('Search Geometry lineare finale non valida')

        self.manual_geometry_kind = 'line_corridor'
        self.manual_line_length_m = float(line_length_m)
        self.manual_line_offset_m = float(offset_m)

        # Registra SUBITO il corridoio come Search Geometry operativa, prima di
        # chiudere lo strumento di disegno e prima delle elaborazioni ecologiche.
        # In questo modo il pulsante "Trova punto ecologico più probabile" vede
        # sempre lo stesso boundary, esattamente come per "Punto manuale + buffer".
        self.search_geometry_mode = 'manual_line'
        self.manual_search_extent = QgsGeometry(boundary)
        self.manual_search_radius_m = float(offset_m)
        self.search_extent = QgsGeometry(boundary)
        self.current_boundary = QgsGeometry(boundary)

        self._cleanup_manual_line_capture()
        try:
            self.dock.btnManualLine.setText('Linea manuale + offset')
        except Exception:
            pass
        self.dock.set_status(
            f'Corridoio manuale creato: linea {line_length_m:.1f} m, offset ±{offset_m:g} m. '
            'Avvio dell’analisi ecologica…'
        )
        # radius_m resta un parametro legacy della pipeline; per la modalità lineare
        # contiene l'offset. L'incertezza personalizzata usa manual_line_length_m.
        # Registra e applica il corridoio come vera Search Geometry.
        # ``offset_m`` è solo la semilarghezza laterale; la geometria completa
        # viene passata alla normale pipeline dei candidati.
        self._analyze_manual_boundary(feature, boundary, offset_m)

        # A differenza del vecchio prototipo, la linea manuale entra subito
        # nell'analisi: non richiede un secondo click su
        # “Trova punto ecologico più probabile”. Questo evita che l'utente
        # lanci accidentalmente una nuova analisi automatica e perda il
        # corridoio appena disegnato.
        try:
            self.find_habitat_suitability_point()
        except Exception as exc:
            # Il corridoio resta comunque valido e visibile, così l'utente può
            # rilanciare manualmente la ricerca del punto senza ridisegnarlo.
            self.dock.set_status(
                f'Corridoio manuale creato (offset ±{offset_m:g} m), ma la ricerca '
                f'dei candidati non è partita automaticamente: {exc}'
            )


    def _boundary_altitude_context_from_record(self, feature):
        """Restituisce info quota min/max/mid per il boundary iniziale."""
        out = {
            "has_altitude": False,
            "is_range": False,
            "min": None,
            "max": None,
            "mid": None,
        }
        try:
            # Usa i parser già presenti nel controller.
            field_names = feature.fields().names() if feature is not None else []
            lowered = {str(f).lower(): f for f in field_names}
            candidate_names = [
                "quota", "Quota", "QUOTA", "quota_m", "Quota_m",
                "altitudine", "Altitudine", "quota_cartellino",
                "Quota_cartellino", "quota_record", "Quota_record",
                "record_altitude", "label_altitude"
            ]

            configured_altitude = getattr(self.mapping, "elevation", None) if self.mapping is not None else None
            if configured_altitude:
                candidate_names.insert(0, configured_altitude)

            seen = set()
            for name in candidate_names:
                actual = name if name in field_names else lowered.get(str(name).lower())
                if not actual or actual in seen:
                    continue
                seen.add(actual)
                value = self._get_attr(feature, actual)

                try:
                    rng = self._parse_record_altitude_range(value)
                except Exception:
                    rng = None
                if rng:
                    out.update({
                        "has_altitude": True,
                        "is_range": True,
                        "min": rng.get("min"),
                        "max": rng.get("max"),
                        "mid": rng.get("mid"),
                    })
                    return out

                try:
                    val = self._parse_record_altitude(value)
                except Exception:
                    val = None
                if val is not None:
                    out.update({
                        "has_altitude": True,
                        "is_range": False,
                        "min": val,
                        "max": val,
                        "mid": val,
                    })
                    return out

        except Exception:
            pass
        return out


    def _semantic_ref_type_from_locality(self, locality_text, current_ref_type=None):
        """Forza il tipo geografico in base al testo del cartellino.

        Serve perché il geocoder può restituire "summit" o "locality" anche quando
        il cartellino dice "Monte X". In GeoLichen 2.4, "Monte X" deve diventare
        mountain_area, cioè area del rilievo/versanti, non piccolo buffer di vetta.
        """
        txt = str(locality_text or "").strip().lower()
        txt = txt.replace("’", "'").replace("`", "'")
        txt = txt.replace("–", "-").replace("—", "-")
        txt = re.sub(r"\s+", " ", txt)

        # Gruppi montuosi o massicci.
        if re.search(r"\b(gruppo|massiccio|catena|dorsale)\b", txt):
            return "mountain_group"

        # Cime vere: buffer piccolo.
        if re.search(r"\b(cima|vetta|pizzo|punta|corno)\b", txt):
            # Se però c'è anche "monte" in una formula tipo "sotto le cime del Monte X",
            # è più prudente usare area del monte.
            if re.search(r"\b(sotto|pendici|versante|pendio)\b", txt) and re.search(r"\bmonte\b", txt):
                return "mountain_area"
            return "summit_peak"

        # Monte = area del rilievo.
        if re.search(r"\b(monte|montagna|mt\.|monte\.)\b", txt):
            return "mountain_area"

        # Colle/dosso/poggio: area intermedia, trattata come mountain_area.
        if re.search(r"\b(colle|dosso|poggio)\b", txt):
            return "mountain_area"

        # Foreste/aree boschive.
        if re.search(r"\b(foresta|bosco|selva|ersaf|demaniale)\b", txt):
            return "forest_area"

        return current_ref_type or "locality"


    def _manual_buffer_radius(self):
        """Legge il raggio buffer dal dock, in metri."""
        try:
            txt = ''
            if hasattr(self.dock, 'txtManualBuffer'):
                txt = self.dock.txtManualBuffer.text().strip()
            value = float(str(txt).replace(',', '.')) if txt else 250.0
            if value <= 0:
                return 250.0
            return value
        except Exception:
            return 250.0

    def _on_manual_map_point_clicked(self, point, button=None):
        """Crea un buffer valido dal click, indipendentemente dal boundary automatico."""
        if button == Qt.RightButton:
            self._cancel_active_manual_capture(restore_previous=True)
            self.dock.set_status('Creazione del buffer manuale annullata.')
            return
        if button not in (None, Qt.LeftButton):
            return

        feature = self.manual_point_feature or self._selected_feature()
        if feature is None:
            self._cleanup_manual_point_capture()
            self._warn('Nessun record selezionato per il punto manuale.')
            return

        radius_m = self._manual_buffer_radius()
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')

        try:
            if point is None:
                raise ValueError('click sulla mappa non valido')
            if not canvas_crs.isValid():
                raise ValueError('CRS della mappa non valido')
            if not math.isfinite(radius_m) or radius_m <= 0:
                raise ValueError('raggio manuale non valido')

            point_geom = QgsGeometry.fromPointXY(QgsPointXY(point))
            if point_geom.isNull() or point_geom.isEmpty():
                raise ValueError('punto manuale vuoto')

            center_wgs84_geom = QgsGeometry(point_geom)
            if canvas_crs != wgs84:
                center_wgs84_geom.transform(
                    QgsCoordinateTransform(canvas_crs, wgs84, QgsProject.instance())
                )
            center_wgs84 = QgsPointXY(center_wgs84_geom.asPoint())
            metric_crs = local_metric_crs(center_wgs84)

            point_metric = QgsGeometry(center_wgs84_geom)
            point_metric.transform(
                QgsCoordinateTransform(wgs84, metric_crs, QgsProject.instance())
            )
            if point_metric.isNull() or point_metric.isEmpty():
                raise ValueError('impossibile trasformare il punto nel CRS metrico locale')

            buffer_metric = point_metric.buffer(float(radius_m), 48)
            if buffer_metric is None or buffer_metric.isNull() or buffer_metric.isEmpty():
                raise ValueError('il buffer metrico generato è vuoto')
            if not buffer_metric.isGeosValid():
                buffer_metric = buffer_metric.makeValid()
            if buffer_metric is None or buffer_metric.isNull() or buffer_metric.isEmpty():
                raise ValueError('il buffer metrico non è una geometria valida')

            boundary = QgsGeometry(buffer_metric)
            if metric_crs != wgs84:
                to_wgs84 = QgsCoordinateTransform(metric_crs, wgs84, QgsProject.instance())
                boundary.transform(to_wgs84)
            if boundary.isNull() or boundary.isEmpty():
                raise ValueError('il boundary manuale finale è vuoto')
            if not boundary.isGeosValid():
                boundary = boundary.makeValid()
            if boundary.isNull() or boundary.isEmpty():
                raise ValueError('il boundary manuale finale non è valido')

            # Da questo momento il punto diventa la geometria manuale confermata.
            # Solo ora vengono azzerati i metadata della precedente linea, non
            # alla semplice attivazione del pulsante.
            self.manual_geometry_kind = 'point_buffer'
            self.manual_line_length_m = None
            self.manual_line_offset_m = None
            # Conserva il centro manuale in WGS84 come provenance autonoma.
            try:
                self.manual_search_center_wgs84 = QgsPointXY(center_wgs84_geom.asPoint())
            except Exception:
                self.manual_search_center_wgs84 = None

            self._cleanup_manual_point_capture()
            try:
                self.dock.btnManualPoint.setText('Punto manuale + buffer')
            except Exception:
                pass
            self.dock.set_status(
                f'Buffer manuale creato ({radius_m:g} m). Avvio dell’analisi ecologica…'
            )
            self._analyze_manual_boundary(feature, boundary, radius_m)

        except Exception as exc:
            self._cleanup_manual_point_capture()
            self._warn(
                'Impossibile creare il buffer manuale dal punto selezionato. '
                f'Dettaglio tecnico: {exc}'
            )


    def _analyze_manual_boundary(self, feature, boundary, radius_m):
        """Analisi completa usando un buffer manuale al posto del geocoding."""
        self.current_feature = feature
        self.current_environment_result = None

        # Il buffer manuale È la geometria iniziale dell'analisi: non deve
        # dipendere da una boundary prodotta in precedenza dal geocoder.
        if boundary is None or boundary.isNull() or boundary.isEmpty():
            raise ValueError('Il buffer manuale ricevuto è assente o vuoto.')
        manual_boundary = QgsGeometry(boundary)
        if not manual_boundary.isGeosValid():
            manual_boundary = manual_boundary.makeValid()
        if manual_boundary is None or manual_boundary.isNull() or manual_boundary.isEmpty():
            raise ValueError('Il buffer manuale ricevuto non è una geometria valida.')

        # Il buffer manuale è una Search Geometry autonoma, non una Document Geometry.
        # La geometria documentale eventualmente già risolta viene preservata.
        manual_kind = str(getattr(self, "manual_geometry_kind", "point_buffer") or "point_buffer")
        is_manual_line = manual_kind == "line_corridor"
        self.search_geometry_mode = "manual_line" if is_manual_line else "manual"
        self.manual_search_extent = QgsGeometry(manual_boundary)
        self.manual_search_radius_m = float(radius_m)
        self.search_extent = QgsGeometry(self.manual_search_extent)
        self.ecological_candidate_extent = None
        self.current_boundary = QgsGeometry(self.manual_search_extent)

        scientific_name = self._get_attr(feature, self.mapping.scientific_name)
        municipality = self._get_attr(feature, self.mapping.municipality)
        locality = self._get_attr(feature, self.mapping.locality)
        self.current_locality_context = self.locality_interpreter.build_context(
            municipality=municipality,
            locality=locality,
        )
        self._sync_locality_extents(
            original_locality_extent=self.original_locality_extent,
            search_extent=self.manual_search_extent,
        )
        # Metadati espliciti per report, GBIF provenance e diagnostica.
        try:
            setattr(self.current_locality_context, "search_geometry_mode", self.search_geometry_mode)
            setattr(self.current_locality_context, "manual_search_geometry", QgsGeometry(self.manual_search_extent))
            setattr(self.current_locality_context, "manual_search_radius_m", float(radius_m))
            setattr(self.current_locality_context, "manual_search_center_wgs84", self.manual_search_center_wgs84)
            setattr(self.current_locality_context, "automatic_search_bypassed", True)
            if is_manual_line:
                setattr(self.current_locality_context, "manual_line_length_m", float(self.manual_line_length_m or 0.0))
                setattr(self.current_locality_context, "manual_line_offset_m", float(self.manual_line_offset_m or radius_m))
                setattr(self.current_locality_context, "search_geometry_source", "user_defined_line_corridor")
                setattr(self.current_locality_context, "search_geometry_strategy", f"manual_line_offset_{float(self.manual_line_offset_m or radius_m):g}m")
            else:
                setattr(self.current_locality_context, "search_geometry_source", "user_defined_point_buffer")
                setattr(self.current_locality_context, "search_geometry_strategy", f"manual_point_buffer_{float(radius_m):g}m")
        except Exception:
            pass

        self.dock.set_match_type('corridoio manuale' if is_manual_line else 'search geometry manuale')
        if is_manual_line:
            self.dock.set_tried_queries([('manual_line', f'linea {float(self.manual_line_length_m or 0):.1f} m; offset ±{float(self.manual_line_offset_m or radius_m):g} m')])
        else:
            self.dock.set_tried_queries([('manual_point', f'buffer {radius_m:g} m')])
        self.dock.set_candidates([])
        try:
            self.current_locality_text = locality or 'Punto manuale'
            self.current_locality_parse_result = self.locality_parser_service.parse(
                locality_context=self.current_locality_context,
            )
            # FASE 6: il punto manuale è classificato come coordinate/punto,
            # mantenendo invariato il buffer scelto dall'utente.
            self.locality_interpreter.classify(
                self.current_locality_context,
                parse_result=self.current_locality_parse_result,
                manual=True,
            )
        except Exception:
            pass

        geology_layer = self._layer_by_name(self.dock.cmbGeologyLayer.currentText())
        soil_layer = self._layer_by_name(self.dock.cmbSoilLayer.currentText())
        trees_layer = self._layer_by_name(self.dock.cmbTreesLayer.currentText())
        geology_field = self.dock.cmbGeologyField.currentText() or None
        soil_field = self.dock.cmbSoilField.currentText() or None
        trees_field = self.dock.cmbTreesField.currentText() or None

        record_constraints = self.record_constraints_service.extract_record_constraints(feature, self.mapping)
        record_semantics = self.record_semantic_interpreter.interpret(record_constraints)
        record_constraints.update(record_semantics)
        record_metadata = list(record_constraints.get("constraint_metadata") or [])
        for _name in ["habitat", "humidity", "slope", "altitude_min", "altitude_max"]:
            record_metadata = self.record_constraints_service.add_derived_constraint(
                record_metadata, _name, record_semantics.get(_name),
                source="record_semantic_interpreter",
                affects_gbif_extent=False,
                affects_gss=True,
                evidence=record_semantics.get("semantic_details"),
            )
        record_constraints["constraint_metadata"] = record_metadata

        env_record = self.environment_overlay_service.apply(
            boundary_geom=boundary,
            geology_layer=geology_layer,
            geology_field=geology_field,
            soil_layer=soil_layer,
            soil_field=soil_field,
            trees_layer=trees_layer,
            trees_field=trees_field,
            constraints=record_constraints,
        )

        taxon_for_italic = self._get_taxon_value(feature) or scientific_name
        italic_profile = self.italic_service.fetch_profile(taxon_for_italic)
        italic_profile = self._attach_record_context_to_profile(italic_profile, feature)
        italic_profile = self._attach_record_altitude_to_profile(italic_profile, feature)
        profile = self.record_semantic_interpreter.merge_record_and_italic(record_semantics, italic_profile)
        # Propaga l'esito unico del Substrate Resolution Engine nel contesto del
        # record. I servizi successivi non devono riclassificare il substrato.
        for _key in (
            'substrate_group', 'substrate_raw', 'substrate_source',
            'substrate_locked', 'substrate_confidence',
            'substrate_resolution_reason',
        ):
            if _key in profile:
                record_constraints[_key] = profile.get(_key)

        layer_decision = self.ecological_layer_decision_service.decide(profile, record_constraints)
        profile['layer_decision'] = layer_decision

        ecology_constraints = self.ecology_engine.compute_constraints(profile)
        ecology_score_result = self.ecology_engine.compute_score(
            profile,
            self._build_ecology_env_from_record(record_constraints, env_record),
        )
        profile['gis_constraints'] = ecology_constraints
        profile['ecological_score'] = ecology_score_result.get('score')
        profile['ecological_score_details'] = ecology_score_result.get('details', [])

        self.dock.set_italic_profile(profile)
        italic_constraints = self.record_constraints_service.extract_italic_constraints(profile)
        for _key in (
            'substrate_group', 'substrate_raw', 'substrate_source',
            'substrate_locked', 'substrate_confidence',
            'substrate_resolution_reason',
        ):
            if _key in profile:
                italic_constraints[_key] = profile.get(_key)
        italic_constraints['layer_decision'] = layer_decision
        if layer_decision.get('soil_ph_preference'):
            italic_constraints['soil_ph_preference'] = layer_decision.get('soil_ph_preference')

        soil_constraints = self.soil_service.infer_constraints(profile)
        tree_constraint = self.tree_service.infer_tree_type(profile)

        if ecology_constraints.get('rock_type'):
            italic_constraints['rock_type'] = ecology_constraints.get('rock_type')
        if ecology_constraints.get('substrate'):
            italic_constraints['substrate'] = ecology_constraints.get('substrate')
        if ecology_constraints.get('habitat'):
            existing_h = italic_constraints.get('fallback_habitat') or []
            italic_constraints['fallback_habitat'] = list(dict.fromkeys(existing_h + ecology_constraints.get('habitat')))
            italic_constraints['habitat_classes'] = ecology_constraints.get('habitat')
        if ecology_constraints.get('humidity'):
            italic_constraints['humidity'] = ecology_constraints.get('humidity')
        if ecology_constraints.get('slope'):
            italic_constraints['slope'] = ecology_constraints.get('slope')
        if ecology_constraints.get('altitude_min') is not None:
            italic_constraints['altitude_min'] = ecology_constraints.get('altitude_min')
        if ecology_constraints.get('altitude_max') is not None:
            italic_constraints['altitude_max'] = ecology_constraints.get('altitude_max')

        if soil_constraints.get('substrate'):
            italic_constraints['substrate'] = soil_constraints.get('substrate')
        if soil_constraints.get('rock_type'):
            italic_constraints['rock_type'] = soil_constraints.get('rock_type')
        if soil_constraints.get('fallback_substrata'):
            existing = italic_constraints.get('fallback_substrata') or []
            italic_constraints['fallback_substrata'] = list(dict.fromkeys(existing + soil_constraints.get('fallback_substrata')))
        if soil_constraints.get('habitat_classes'):
            existing_h = italic_constraints.get('fallback_habitat') or []
            italic_constraints['fallback_habitat'] = list(dict.fromkeys(existing_h + soil_constraints.get('habitat_classes')))
            italic_constraints['habitat_classes'] = soil_constraints.get('habitat_classes')
        if tree_constraint:
            italic_constraints['tree_type'] = tree_constraint

        italic_metadata = list(italic_constraints.get("constraint_metadata") or [])
        for _name, _source in [
            ("soil_ph_preference", "soil_service"),
            ("habitat_classes", "ecology_engine"),
            ("humidity", "ecology_engine"),
            ("slope", "ecology_engine"),
            ("altitude_min", "ITALIC"),
            ("altitude_max", "ITALIC"),
        ]:
            italic_metadata = self.record_constraints_service.add_derived_constraint(
                italic_metadata, _name, italic_constraints.get(_name),
                source=_source, affects_gbif_extent=False, affects_gss=True
            )
        self.current_constraint_metadata = self.record_constraints_service.merge_constraint_metadata(
            record_metadata, italic_metadata
        )
        profile["constraint_metadata"] = list(self.current_constraint_metadata)
        italic_constraints["constraint_metadata"] = italic_metadata

        env_italic = self.environment_overlay_service.apply(
            boundary_geom=self.search_extent,
            geology_layer=geology_layer,
            geology_field=geology_field,
            soil_layer=soil_layer,
            soil_field=soil_field,
            trees_layer=trees_layer,
            trees_field=trees_field,
            constraints=italic_constraints,
        )

        env_result = self._merge_environment_results(env_record, env_italic, profile)
        env_result["constraint_metadata"] = list(self.current_constraint_metadata)
        self.current_environment_result = env_result
        self.ecological_candidate_extent = QgsGeometry(
            env_result['geometry'] if env_result.get('geometry') else self.search_extent
        )
        # Il motore di campionamento lavora sempre sulla SearchGeometry completa.
        # L'estensione ecologica resta separata per diagnostica e provenance.
        self.current_boundary = QgsGeometry(self.search_extent)
        self._sync_locality_extents(
            ecological_extent=self.ecological_candidate_extent,
        )

        self._zoom_to_geometry(self.current_boundary)
        self._show_boundary_highlight(self.current_boundary)

        record_rock = record_constraints.get('rock_type') or '-'
        italic_rock = profile.get('rock_type') or '-'
        manual_label = (
            f'Corridoio manuale: linea {float(self.manual_line_length_m or 0.0):.1f} m; '
            f'offset ±{float(self.manual_line_offset_m or radius_m):g} m'
            if is_manual_line
            else f'Punto manuale: buffer {radius_m:g} m'
        )
        status_parts = [
            manual_label,
            f'Specie: {scientific_name or "-"}',
            f'Profilo: {profile.get("source")}',
            f'Substrata ITALIC: {", ".join(profile.get("substrata", []) or []) or "-"}',
            f'Roccia: record={record_rock}; ITALIC={italic_rock}',
            f'Habitat ITALIC: {", ".join(italic_constraints.get("fallback_habitat", []) or []) or "-"}',
            f'Decisione ecologica: {layer_decision.get("explain") or "-"}',
            f'Vincoli GIS ITALIC: {self._summarize_ecology_constraints(profile.get("gis_constraints") or {})}',
            f'Score ecologico: {profile.get("ecological_score") if profile.get("ecological_score") is not None else "-"}',
            f'Campo geologia: {env_result.get("resolved_geology_field") or "-"}',
            f'Score ambiente: {env_result.get("score")}',
        ]
        if env_result.get('details'):
            status_parts.append('Dettagli: ' + '; '.join(env_result['details'][:2]))
        if env_result.get('warnings'):
            status_parts.append('Warning: ' + '; '.join(env_result['warnings'][:2]))
        if env_result.get('blocking_reasons'):
            status_parts.append('Blocchi: ' + '; '.join(env_result['blocking_reasons'][:2]))

        if is_manual_line:
            self.dock.set_found_place(
                f'Corridoio manuale · linea {float(self.manual_line_length_m or 0.0):.1f} m '
                f'· offset ±{float(self.manual_line_offset_m or radius_m):g} m'
            )
        else:
            self.dock.set_found_place(f'Zona manuale autonoma · buffer {radius_m:g} m')
        self.dock.set_status(' | '.join(status_parts))

    def _get_record_altitude(self, feature):
        """Legge la quota dal record input, se presente.

        Priorità:
        1. campo Quota configurato dall'utente nella finestra "Configura campi input";
        2. fallback solo su campi chiaramente riferiti alla quota del cartellino.

        Non usa campi generici come altitude/elevation/alt, perché possono contenere
        quote DEM o valori generati dai layer del plugin.
        """
        if feature is None:
            return None

        try:
            field_names = feature.fields().names()
            lowered = {str(f).lower(): f for f in field_names}
        except Exception:
            return None

        # 1) Priorità assoluta: campo quota configurato nel mapping input.
        configured_altitude = None
        if self.mapping is not None:
            configured_altitude = getattr(self.mapping, "elevation", None)

        if configured_altitude:
            actual = configured_altitude if configured_altitude in field_names else lowered.get(str(configured_altitude).lower())
            if actual:
                value = self._get_attr(feature, actual)
                parsed = self._parse_record_altitude(value)
                if parsed is not None:
                    try:
                        print(f"[GeoLichen] quota record letta dal mapping '{actual}' = {parsed}")
                    except Exception:
                        pass
                    return parsed

        # 2) Fallback conservativo: solo nomi esplicitamente riferiti al cartellino.
        possible_fields = [
            "quota", "Quota", "QUOTA",
            "quota_m", "Quota_m", "QUOTA_M",
            "altitudine", "Altitudine", "ALTITUDINE",
            "quota_cartellino", "Quota_cartellino", "QUOTA_CARTELLINO",
            "quota cartellino", "Quota cartellino",
            "quota_record", "Quota_record", "QUOTA_RECORD",
            "record_altitude", "Record_altitude",
            "label_altitude", "Label_altitude"
        ]

        for name in possible_fields:
            actual = name if name in field_names else lowered.get(name.lower())
            if actual:
                value = self._get_attr(feature, actual)
                parsed = self._parse_record_altitude(value)
                if parsed is not None:
                    try:
                        print(f"[GeoLichen] quota record letta da campo '{actual}' = {parsed}")
                    except Exception:
                        pass
                    return parsed

        try:
            print("[GeoLichen] quota record non trovata nei campi input")
        except Exception:
            pass
        return None

    def _parse_record_altitude(self, value):
        """Converte una quota testuale/numerica in metri."""
        if value in [None, "", [], {}]:
            return None
        try:
            if isinstance(value, (int, float)):
                v = float(value)
                return v if -500 <= v <= 9000 else None

            import re
            text = str(value).lower().replace(",", ".")
            # Prende il primo numero plausibile nella stringa.
            # Esempi: "1850", "1850 m", "m 1850", "quota 1850"
            nums = re.findall(r"-?\d+(?:\.\d+)?", text)
            for n in nums:
                v = float(n)
                if -500 <= v <= 9000:
                    return v
        except Exception:
            return None
        return None


    def _attach_record_context_to_profile(self, profile, feature):
        """Aggiunge al profilo ITALIC anche i dati originali del cartellino.

        Serve ai servizi ecologici avanzati, in particolare:
        - ForestTypeService / TreeService
        - quota range
        - forofita/albero/host
        """
        profile = profile or {}
        if feature is None:
            return profile

        try:
            rc = {}
            if self.mapping is not None:
                rc = self.record_constraints_service.extract_record_constraints(feature, self.mapping) or {}
            profile["record_constraints"] = rc
        except Exception:
            rc = {}

        try:
            field_names = feature.fields().names()
            raw = {}
            for name in field_names:
                try:
                    raw[name] = self._get_attr(feature, name)
                except Exception:
                    pass
            profile["raw_record"] = raw
            profile["record"] = raw

            # Copia esplicitamente i campi che possono contenere forofita/albero.
            for name, value in raw.items():
                lname = str(name).lower()
                if any(k in lname for k in [
                    "albero", "forof", "forophy", "phorophy", "host",
                    "cortecc", "bark", "legno", "wood", "tronco", "ramo"
                ]):
                    if value not in [None, "", [], {}]:
                        profile["record_tree_raw"] = str(value)
                        profile["tree_type"] = str(value)
                        profile["forofita_record"] = str(value)
                        break
        except Exception:
            pass

        return profile


    def _attach_record_altitude_to_profile(self, profile, feature):
        """Aggiunge quota e versante del record al profilo usato dallo scoring.

        Se il dato manca, non modifica il profilo.
        """
        profile = profile or {}
        record_altitude = self._get_record_altitude(feature)
        if record_altitude is not None:
            profile["record_altitude"] = record_altitude
            profile["quota_record"] = record_altitude
            profile["record_altitude_source"] = "input_field"

        try:
            if self.mapping is not None:
                rc = self.record_constraints_service.extract_record_constraints(feature, self.mapping)
                if rc.get("record_aspect"):
                    profile["record_aspect"] = rc.get("record_aspect")
                    profile["record_aspect_raw"] = rc.get("record_aspect_raw")
                    profile["record_aspect_source"] = "record_constraints"
        except Exception:
            pass

        return profile

    def _build_ecology_env_from_record(self, record_constraints, env_record):
        """Costruisce l'ambiente minimo per EcologyEngine."""
        record_constraints = record_constraints or {}
        env_record = env_record or {}

        env = {
            # Qui "altitude" deve rappresentare la quota ambientale/DEM del punto.
            # Non inseriamo la quota del record in altitude, per evitare di confonderla
            # con la quota del punto candidato. La quota del cartellino va in record_altitude.
            "altitude": None,
            "record_altitude": (
                self._safe_float(record_constraints.get("record_altitude"))
                or self._safe_float(record_constraints.get("quota"))
                or self._safe_float(record_constraints.get("elevation"))
                or self._safe_float(record_constraints.get("altitude_record"))
                or self._safe_float(record_constraints.get("elevation_record"))
            ),
            "rock_type": record_constraints.get("rock_type"),
            "substrate": record_constraints.get("substrate"),
            "slope": self._safe_float(record_constraints.get("slope")),
            "humidity": record_constraints.get("humidity"),
            "record_aspect": record_constraints.get("record_aspect"),
            "record_aspect_raw": record_constraints.get("record_aspect_raw"),
            "tree_type": (
                record_constraints.get("tree_type")
                or record_constraints.get("forofita")
                or record_constraints.get("forophyte")
                or record_constraints.get("albero")
                or record_constraints.get("host_tree")
            ),
            "tree_raw": (
                record_constraints.get("tree_type")
                or record_constraints.get("forofita")
                or record_constraints.get("forophyte")
                or record_constraints.get("albero")
                or record_constraints.get("host_tree")
            ),
        }

        details_text = " ".join(env_record.get("details", []) or []).lower()
        if not env.get("rock_type"):
            if "siliceo" in details_text:
                env["rock_type"] = "siliceo"
            elif "calcareo" in details_text:
                env["rock_type"] = "calcareo"
            elif "misto" in details_text:
                env["rock_type"] = "misto"

        return env

    def _safe_float(self, value):
        try:
            if value in [None, "", [], {}]:
                return None
            return float(str(value).replace(",", "."))
        except Exception:
            return None

    def _summarize_ecology_constraints(self, constraints):
        """Rende leggibili i vincoli GIS ITALIC nello status del pannello."""
        constraints = constraints or {}
        parts = []

        if constraints.get("rock_type"):
            parts.append("roccia=" + str(constraints.get("rock_type")))
        if constraints.get("substrate"):
            parts.append("substrato=" + str(constraints.get("substrate")))
        if constraints.get("altitude_min") is not None:
            alt_min = constraints.get("altitude_min")
            alt_max = constraints.get("altitude_max")
            if alt_max is not None:
                parts.append("quota=" + str(alt_min) + "-" + str(alt_max) + "m")
            else:
                parts.append("quota>=" + str(alt_min) + "m")
        if constraints.get("slope"):
            parts.append("pendenza=" + str(constraints.get("slope")))
        if constraints.get("humidity"):
            parts.append("umidità=" + str(constraints.get("humidity")))

        habitat = constraints.get("habitat") or []
        if habitat:
            if isinstance(habitat, (list, tuple)):
                parts.append("habitat=" + ", ".join(str(x) for x in habitat if x))
            else:
                parts.append("habitat=" + str(habitat))

        return "; ".join(parts) if parts else "-"

    def _get_suitability_grid_step(self):
        try:
            if hasattr(self.dock, 'txtSuitabilityGridStep'):
                value = float(self.dock.txtSuitabilityGridStep.text().replace(',', '.'))
                if value > 0:
                    return value
        except Exception:
            pass
        return 50

    def _get_suitability_visualization_mode(self):
        """Legge la modalità di visualizzazione richiesta dal dock.

        Valori interni:
        - points: solo layer punti candidati
        - heatmap: solo layer heat map
        - both: punti + heat map
        """
        try:
            if hasattr(self.dock, 'cmbSuitabilityView'):
                text = self.dock.cmbSuitabilityView.currentText().strip().lower()
                if 'entrambi' in text or 'both' in text:
                    return 'both'
                if 'surface' in text or 'suitability' in text or 'gss' in text or 'heat' in text:
                    return 'heatmap'
        except Exception:
            pass
        return 'points'

    def _get_heatmap_radius_mm(self):
        try:
            if hasattr(self.dock, 'txtHeatmapRadius'):
                value = float(self.dock.txtHeatmapRadius.text().replace(',', '.'))
                if 1 <= value <= 100:
                    return value
        except Exception:
            pass
        return 18.0

    def _get_heatmap_opacity(self):
        try:
            if hasattr(self.dock, 'txtHeatmapOpacity'):
                value = float(self.dock.txtHeatmapOpacity.text().replace(',', '.'))
                if value > 1:
                    value = value / 100.0
                if 0.05 <= value <= 1:
                    return value
        except Exception:
            pass
        return 0.60


    def _selected_accessibility_layers(self):
        """Ritorna layer accessibilità selezionati.

        Include:
        - QgsVectorLayer classici;
        - QgsVectorTileLayer come oggetti opzionali sperimentali.
        """
        layers = []
        try:
            if hasattr(self.dock, "lstAccessibilityLayers"):
                for i in range(self.dock.lstAccessibilityLayers.count()):
                    item = self.dock.lstAccessibilityLayers.item(i)
                    if item and item.checkState() == 2:
                        label = item.text()
                        clean = label.replace(" [VectorTile]", "")
                        lyr = self._layer_by_name(clean)
                        if lyr is not None:
                            layers.append(lyr)
        except Exception:
            layers = []

        if not layers:
            try:
                if hasattr(self.dock, 'cmbTrailLayer'):
                    lyr = self._layer_by_name(self.dock.cmbTrailLayer.currentText())
                    if lyr is not None:
                        layers.append(lyr)
            except Exception:
                pass

        return layers


    def _update_candidate_selection_layer(self, selected_candidate, metadata):
        """Aggiorna i campi di audit selezionando un solo candidato.

        Il rank non e' sufficiente quando coesistono griglia globale e raffinata,
        perche' entrambe possono contenere un Rank 1. La selezione viene quindi
        identificata dalla coppia ``grid_lvl + rank``; come ulteriore sicurezza
        viene confrontata anche la geometria del punto.
        """
        result = self.current_suitability_result or {}
        layer = result.get("layer")
        if layer is None or not hasattr(layer, "fields") or not selected_candidate:
            return
        try:
            names = layer.fields().names()
            if "selected" not in names or "sel_method" not in names:
                return
            idx_selected = layer.fields().indexOf("selected")
            idx_method = layer.fields().indexOf("sel_method")
            idx_reason = layer.fields().indexOf("sel_reason") if "sel_reason" in names else -1

            selected_rank = int(selected_candidate.get("rank") or 0)
            selected_level = str(selected_candidate.get("grid_level") or "final")
            selected_point = selected_candidate.get("point")

            layer.startEditing()
            for feat in layer.getFeatures():
                same_rank = int(feat["rank"] or 0) == selected_rank
                same_level = str(feat["grid_lvl"] or "final") == selected_level
                same_point = False
                if selected_point is not None and feat.geometry() is not None and not feat.geometry().isEmpty():
                    try:
                        p = feat.geometry().asPoint()
                        same_point = abs(float(p.x()) - float(selected_point.x())) < 1e-10 and abs(float(p.y()) - float(selected_point.y())) < 1e-10
                    except Exception:
                        same_point = False
                # Il campo ``selected`` governa la simbologia verde: deve restare
                # associato esclusivamente al vero Rank 1 finale, non alla posizione
                # della feature cliccata nella lista (es. 1791). La selezione manuale
                # resta tracciata in sel_method/sel_reason sulla feature scelta.
                is_manual_choice = bool(same_point or (same_rank and same_level))
                is_rank_one = int(feat["rank"] or 0) == 1
                layer.changeAttributeValue(feat.id(), idx_selected, "yes" if is_rank_one else "no")
                layer.changeAttributeValue(feat.id(), idx_method, metadata.get("selection_method") if is_manual_choice else "")
                if idx_reason >= 0:
                    layer.changeAttributeValue(feat.id(), idx_reason, metadata.get("selected_reason") if is_manual_choice else "")
            layer.commitChanges()
            layer.triggerRepaint()
        except Exception:
            try:
                layer.rollBack()
            except Exception:
                pass

    def find_habitat_suitability_point(self):
        """Trova il punto ecologicamente più probabile dentro il boundary/buffer corrente.

        Se l'utente sta ancora disegnando una linea manuale e ha già inserito
        almeno due vertici, il click su questo pulsante vale anche come
        "termina linea": il corridoio viene chiuso, registrato come Search
        Geometry e passato alla normale pipeline.
        """
        # UX robusta per la linea manuale: oltre al click destro, anche il
        # pulsante di ricerca può terminare il disegno. Evita il falso messaggio
        # "Nessun buffer/boundary disponibile" quando la linea è visibile ma
        # non è stata ancora finalizzata.
        if self.manual_line_tool is not None:
            if len(self.manual_line_vertices) >= 2:
                try:
                    self._finish_manual_line_capture()
                except Exception as exc:
                    self._warn(f'Impossibile terminare la linea manuale: {exc}')
                return
            # Nessun corridoio valido è stato creato: consideriamo la modalità
            # un'attivazione incompleta/accidentale, la annulliamo e proseguiamo
            # usando l'eventuale Search Geometry già valida.
            self._cancel_active_manual_capture(restore_previous=True)
            self.dock.set_status('Linea manuale incompleta annullata; uso la Search Geometry corrente.')

        # Recovery difensivo: se il corridoio manuale è già stato costruito ma
        # current_boundary è stato perso da un refresh/stato GUI, ripristinalo
        # dalla Search Geometry manuale persistente.
        if (self.current_boundary is None or self.current_boundary.isEmpty()):
            manual_extent = getattr(self, 'manual_search_extent', None)
            manual_mode = str(getattr(self, 'search_geometry_mode', '') or '')
            if manual_mode == 'manual_line' and manual_extent is not None and not manual_extent.isEmpty():
                self.search_extent = QgsGeometry(manual_extent)
                self.current_boundary = QgsGeometry(manual_extent)

        trail_layers = self._selected_accessibility_layers()
        self._ensure_aux_services()

        if self.current_boundary is None or self.current_boundary.isEmpty():
            self._warn('Nessun buffer/boundary disponibile. Prima analizza un record, crea un buffer manuale oppure termina la linea manuale.')
            return

        # OSM/Overpass: scarica una sola volta per elaborazione i sentieri
        # presenti nella SearchGeometry e li aggiunge ai layer di accessibilità.
        try:
            use_osm = True
            if hasattr(self.dock, "chkUseOsmTrails"):
                use_osm = bool(self.dock.chkUseOsmTrails.isChecked())
            if use_osm and self.search_extent is not None and not self.search_extent.isEmpty():
                self.dock.set_status("Download sentieri OpenStreetMap…")
                # The trail query is independent from the OSM locality query.
                # Remove only the previous temporary trail layer; never reuse a
                # locality-geometry response as if it already contained trails.
                previous_osm_layer = self.current_osm_trail_layer
                osm_result = self.osm_trail_service.fetch(
                    self.search_extent,
                    QgsCoordinateReferenceSystem("EPSG:4326"),
                )
                if osm_result.success and osm_result.layer is not None and osm_result.feature_count > 0:
                    # Sostituisce l'eventuale layer OSM della precedente elaborazione,
                    # evitando duplicati e garantendo che il nuovo layer sia quello
                    # realmente usato dal motore di accessibilità.
                    if previous_osm_layer is not None and previous_osm_layer.id() != osm_result.layer.id():
                        try:
                            if QgsProject.instance().mapLayer(previous_osm_layer.id()) is not None:
                                QgsProject.instance().removeMapLayer(previous_osm_layer.id())
                        except Exception:
                            pass
                    self.current_osm_trail_layer = osm_result.layer
                    trail_layers = [osm_result.layer] + [lyr for lyr in trail_layers if lyr is not osm_result.layer]
                    if hasattr(self.dock, "chkShowOsmTrails") and self.dock.chkShowOsmTrails.isChecked():
                        if QgsProject.instance().mapLayer(osm_result.layer.id()) is None:
                            QgsProject.instance().addMapLayer(osm_result.layer)
                    cache_text = " (cache)" if osm_result.from_cache else ""
                    self.dock.set_status(
                        f"{osm_result.feature_count} geometrie sentieristiche OSM trovate{cache_text}"
                    )
                else:
                    if previous_osm_layer is not None:
                        try:
                            if QgsProject.instance().mapLayer(previous_osm_layer.id()) is not None:
                                QgsProject.instance().removeMapLayer(previous_osm_layer.id())
                        except Exception:
                            pass
                    self.current_osm_trail_layer = None
                    if osm_result.error:
                        self.dock.set_status(
                            "Dati sentieristici OSM non disponibili: " + str(osm_result.error)
                        )
        except Exception as exc:
            self.current_osm_trail_layer = None
            try:
                self.dock.set_status("Analisi OSM non disponibile: " + str(exc))
            except Exception:
                pass

        trail_layer = trail_layers[0] if trail_layers else None

        profile = {}
        if self.current_environment_result:
            profile = self.current_environment_result.get('italic_profile') or {}
        if not profile and self.current_feature is not None:
            taxon = self._get_taxon_value(self.current_feature)
            if taxon:
                profile = self.italic_service.fetch_profile(taxon)
                self.dock.set_italic_profile(profile)

        if not profile:
            self._warn('Nessun profilo ITALIC disponibile per calcolare la suitability.')
            return

        if self.current_feature is not None:
            profile = self._attach_record_context_to_profile(profile, self.current_feature)
            profile = self._attach_record_altitude_to_profile(profile, self.current_feature)
        geology_layer = self._layer_by_name(self.dock.cmbGeologyLayer.currentText())
        soil_layer = self._layer_by_name(self.dock.cmbSoilLayer.currentText())
        trees_layer = self._layer_by_name(self.dock.cmbTreesLayer.currentText())
        vegetation_belt_layer = self._layer_by_name(self.dock.cmbVegetationBeltLayer.currentText()) if hasattr(self.dock, 'cmbVegetationBeltLayer') else None
        geology_field = self.dock.cmbGeologyField.currentText() or None
        soil_field = self.dock.cmbSoilField.currentText() or None
        trees_field = self.dock.cmbTreesField.currentText() or None
        vegetation_belt_field = self.dock.cmbVegetationBeltField.currentText() if hasattr(self.dock, 'cmbVegetationBeltField') else None
        vegetation_belt_field = vegetation_belt_field or None
        dem_layers = self._selected_dem_layers()
        dem_layer = dem_layers[0] if dem_layers else None

        try:
            if not profile.get('layer_decision'):
                record_constraints = {}
                if self.current_feature is not None and self.mapping is not None:
                    record_constraints = self.record_constraints_service.extract_record_constraints(self.current_feature, self.mapping)
                profile['layer_decision'] = self.ecological_layer_decision_service.decide(profile, record_constraints)

            context = self.context_engine.infer_context(
                geocoding_result=getattr(self, "current_geocoding_result", None),
                locality_parse_result=getattr(self, "current_locality_parse_result", None),
                locality_text=getattr(self, "current_locality_text", ""),
            )
            context_point = None
            try:
                if getattr(self, "current_geocoding_result", None) is not None:
                    c = self.current_geocoding_result.center
                    if c and len(c) == 2:
                        context_point = QgsPointXY(float(c[0]), float(c[1]))
            except Exception:
                context_point = None

            result = self.habitat_suitability_service.find_best_point(
                # La griglia deve essere generata sull'intera SearchGeometry,
                # mai sulla DocumentedGeometry o sull'ecological_candidate_extent.
                buffer_geom=self.search_extent,
                original_locality_extent=self.original_locality_extent,
                search_extent=self.search_extent,
                constraint_metadata=self.current_constraint_metadata,
                profile=profile,
                geology_layer=geology_layer,
                geology_field=geology_field,
                soil_layer=soil_layer,
                soil_field=soil_field,
                trees_layer=trees_layer,
                trees_field=trees_field,
                trail_layer=trail_layer,
                trail_layers=trail_layers,
                vegetation_belt_layer=vegetation_belt_layer,
                vegetation_belt_field=vegetation_belt_field,
                dem_layer=dem_layer,
                dem_layers=dem_layers,
                grid_step_m=self._get_suitability_grid_step(),
                create_layer=True,
                layer_name='Habitat suitability - punti',
                visualization_mode=self._get_suitability_visualization_mode(),
                heatmap_radius_mm=self._get_heatmap_radius_mm(),
                heatmap_opacity=self._get_heatmap_opacity(),
                context=context,
                context_point=context_point,
                locality_context=self.current_locality_context,
            )

            self.current_suitability_result = result
            self.current_selected_candidate = None
            self.current_selection_metadata = dict(result.get("selection") or {})

            best_point = result.get('best_point')
            score = result.get('best_score')
            env = result.get('best_env') or {}
            details = result.get('best_details') or []

            if best_point:
                point_geom = QgsGeometry.fromPointXY(best_point)
                self._zoom_to_geometry(point_geom)
                self._show_boundary_highlight(point_geom)

            alt = env.get('altitude')
            rec_alt = env.get('record_altitude')
            delta_alt = result.get('top_points', [{}])[0].get('alt_delta_m') if result.get('top_points') else None
            msg = (
                f"Punto migliore: score {score}/100; "
                f"punti valutati: {result.get('points_count')}; "
                f"quotaDEM={round(float(alt)) if alt is not None else '-'}m; "
                f"quotaRecord={round(float(rec_alt)) if rec_alt is not None else '-'}m; "
                f"Δquota={round(float(delta_alt)) if delta_alt is not None else '-'}m; "
                f"roccia={env.get('rock_type') or '-'}, "
                f"substrato={env.get('substrate') or '-'}; "
                f"visualizzazione={self._get_suitability_visualization_mode()}"
            )
            if hasattr(self.dock, 'set_habitat_suitability'):
                self.dock.set_habitat_suitability(msg)

            top_points = result.get('top_points') or []
            top_lines = []
            for row in top_points[:10]:
                env_row = row.get('env') or {}
                alt = env_row.get('altitude')
                rec_alt = env_row.get('record_altitude')
                delta_alt = row.get('alt_delta_m')
                alt_txt = '-'
                if alt is not None:
                    alt_txt = f"{round(float(alt))}m"
                delta_txt = '-'
                if delta_alt is not None:
                    delta_txt = f"{round(float(delta_alt))}m"
                rec_alt_txt = '-'
                if rec_alt is not None:
                    rec_alt_txt = f"{round(float(rec_alt))}m"
                top_lines.append(
                    f"#{row.get('rank')} score={row.get('score')}/100; "
                    f"quotaDEM={alt_txt}; quotaRecord={rec_alt_txt}; Δquota={delta_txt}; "
                    f"roccia={env_row.get('rock_type') or '-'}; "
                    f"substrato={env_row.get('substrate') or '-'}; "
                    f"sentiero={round(float(env_row.get('trail_dist_m'))) if env_row.get('trail_dist_m') is not None else '-'}m; "
                    f"dist={round(row.get('distance_to_center_m') or 0)}m"
                )
            if hasattr(self.dock, 'set_habitat_top10'):
                self.dock.set_habitat_top10('\n'.join(top_lines) if top_lines else '-')

            self.dock.set_status(msg + ((' | ' + '; '.join(details[:2])) if details else ''))

        except Exception as exc:
            self._warn(f'Calcolo punto ecologico fallito: {exc}')

    def _merge_environment_results(self, first, second, italic_profile):
        first = first or {}
        second = second or {}
        details = []
        warnings = []
        blocking = []
        details.extend(first.get('details', []) or [])
        warnings.extend(first.get('warnings', []) or [])
        blocking.extend(first.get('blocking_reasons', []) or [])
        if italic_profile:
            details.append('ITALIC letto dopo la litologia: ' + str(italic_profile.get('scientific_name') or italic_profile.get('queried_name') or '-'))
            if italic_profile.get('rock_type'):
                details.append('Vincolo roccia ITALIC: ' + str(italic_profile.get('rock_type')))
            if italic_profile.get('substrata'):
                details.append('Substrata ITALIC: ' + ', '.join(italic_profile.get('substrata') or []))
        details.extend(second.get('details', []) or [])
        warnings.extend(second.get('warnings', []) or [])
        blocking.extend(second.get('blocking_reasons', []) or [])
        score1 = first.get('score', 100)
        score2 = second.get('score', score1)
        try:
            score = round((float(score1) + float(score2)) / 2, 1)
        except Exception:
            score = score2 or score1
        return {
            'geometry': second.get('geometry') or first.get('geometry'),
            'details': details,
            'warnings': warnings,
            'blocking_reasons': blocking,
            'score': score,
            'resolved_geology_field': second.get('resolved_geology_field') or first.get('resolved_geology_field'),
            'italic_profile': italic_profile or {},
        }

    def _select_geocoding_candidate_if_needed(self, result):
        """Mostra il selettore candidati e gestisce Cancel correttamente.

        GeoLichen 2.6:
        se l'utente preme Cancel, l'analisi si interrompe e NON viene
        costruito nessun buffer con candidati di fallback.
        """
        if result is None or not getattr(result, "ok", False):
            return result

        candidates = getattr(result, "candidates", None) or []
        if len(candidates) <= 1:
            return result

        try:
            dlg = CandidateSelectorDialog(candidates, self.iface.mainWindow())
            accepted = dlg.exec_()
            if not accepted:
                return None

            # GeoLichen 15.3.4a: recupera realmente la riga scelta dall'utente.
            # CandidateSelectorDialog espone selected() come metodo, mentre
            # selected_feature e' un attributo dict. Il vecchio codice provava
            # a chiamare selected_feature() e, fallendo silenziosamente,
            # lasciava result.feature impostato sul primo candidato.
            selected = None
            for member_name in [
                "selected",
                "selected_candidate",
                "get_selected_candidate",
                "selected_feature",
            ]:
                if not hasattr(dlg, member_name):
                    continue
                try:
                    member = getattr(dlg, member_name)
                    selected = member() if callable(member) else member
                except Exception:
                    selected = None
                if selected:
                    break

            if selected:
                result.feature = selected
                try:
                    result.matched_source = selected.get("_geolichen_ref_type") or result.matched_source
                except Exception:
                    pass
            return result
        except Exception:
            # Se il dialog fallisce è più sicuro fermarsi che creare un buffer ambiguo.
            return None


    def _preview_geocoding_candidate(self, feature):
        """Mostra temporaneamente bbox/centro del candidato geocoder sulla mappa."""
        try:
            self._clear_candidate_preview()
            if not feature:
                return

            bbox = feature.get("bbox")
            center = feature.get("center")

            geom = None
            if bbox and len(bbox) == 4:
                from qgis.core import QgsRectangle
                geom = QgsGeometry.fromRect(QgsRectangle(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])))
            elif center and len(center) == 2:
                geom = QgsGeometry.fromPointXY(QgsPointXY(float(center[0]), float(center[1])))

            if geom is None or geom.isEmpty():
                return

            canvas = self.iface.mapCanvas()
            canvas_geom = self._geometry_to_canvas_crs(geom)

            geom_type = QgsWkbTypes.geometryType(canvas_geom.wkbType())
            rb_type = QgsWkbTypes.PointGeometry if geom_type == QgsWkbTypes.PointGeometry else QgsWkbTypes.PolygonGeometry

            self.candidate_preview_band = QgsRubberBand(canvas, rb_type)
            self.candidate_preview_band.setColor(QColor(255, 190, 0, 220))
            self.candidate_preview_band.setFillColor(QColor(255, 190, 0, 55))
            self.candidate_preview_band.setWidth(3)
            self.candidate_preview_band.setToGeometry(canvas_geom, None)
            self.candidate_preview_band.show()

            if center and len(center) == 2:
                center_geom = QgsGeometry.fromPointXY(QgsPointXY(float(center[0]), float(center[1])))
                center_canvas_geom = self._geometry_to_canvas_crs(center_geom)
                self.candidate_preview_center_band = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
                self.candidate_preview_center_band.setColor(QColor(255, 80, 0, 240))
                self.candidate_preview_center_band.setWidth(8)
                self.candidate_preview_center_band.setToGeometry(center_canvas_geom, None)
                self.candidate_preview_center_band.show()

            self._zoom_to_geometry(geom)
        except Exception as exc:
            try:
                print(f"[GeoLichen] preview candidato non riuscita: {exc}")
            except Exception:
                pass

    def _clear_candidate_preview(self):
        try:
            canvas = self.iface.mapCanvas()
            if self.candidate_preview_band is not None:
                canvas.scene().removeItem(self.candidate_preview_band)
                self.candidate_preview_band = None
            if self.candidate_preview_center_band is not None:
                canvas.scene().removeItem(self.candidate_preview_center_band)
                self.candidate_preview_center_band = None
        except Exception:
            self.candidate_preview_band = None
            self.candidate_preview_center_band = None

    def _geocoding_candidates(self, result):
        """Restituisce i candidati ordinati del geocoder, rimuovendo duplicati evidenti."""
        raw = getattr(result, "raw", None) or {}
        features = raw.get("features", []) if isinstance(raw, dict) else []
        if not features and getattr(result, "feature", None):
            features = [result.feature]

        out = []
        seen = set()
        for f in features:
            if not isinstance(f, dict):
                continue
            center = f.get("center") or []
            key = (
                str(f.get("place_name") or f.get("text") or "").lower(),
                tuple(round(float(x), 6) for x in center) if len(center) == 2 else None,
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
        return out

    def _should_show_candidate_dialog(self, candidates):
        """Mostra la scelta solo quando i risultati sono plausibilmente ambigui.

        La soglia è conservativa per non disturbare il workflow esistente:
        - se primo e secondo candidato hanno score simile;
        - oppure se il primo candidato non ha una bbox, ma altri sì;
        - oppure se tra i primi candidati compaiono nomi diversi ma vicini.
        """
        if len(candidates) < 2:
            return False

        def score(f):
            try:
                return float(f.get("_geolichen_score", 0.0))
            except Exception:
                return 0.0

        first, second = candidates[0], candidates[1]
        gap = score(first) - score(second)

        # Gap piccolo: candidato ambiguo.
        if gap <= 35:
            return True

        # Se il primo è puntuale ma il secondo ha bbox/geometria più informativa,
        # può essere utile far scegliere.
        if not first.get("bbox") and second.get("bbox") and gap <= 60:
            return True

        return False

    def _summarize_candidates(self, result):
        raw = getattr(result, 'raw', None) or {}
        features = raw.get('features', []) if isinstance(raw, dict) else []
        items = []
        for f in features[:3]:
            label = f.get('place_name') or f.get('text') or '-'
            ftype = f.get('place_type') or f.get('type') or ''
            score = f.get('_geolichen_score')
            score_txt = ''
            try:
                if score is not None:
                    score_txt = f" score={float(score):.1f}"
            except Exception:
                score_txt = ''
            dist = f.get('_geolichen_distance_to_municipality_m')
            dist_txt = ''
            try:
                if dist is not None:
                    dist = float(dist)
                    dist_txt = f" dist={round(dist)}m" if dist < 1000 else f" dist={dist/1000:.1f}km"
            except Exception:
                dist_txt = ''
            reason = f.get('_geolichen_score_reason')
            reason_txt = f" ({reason})" if reason else ''
            items.append(f"{label}" + (f" [{ftype}]" if ftype else "") + score_txt + dist_txt + reason_txt)
        return items



    def _get_taxon_value(self, feature):
        # 1. campo configurato come specie/taxon
        configured = None
        if self.mapping is not None:
            configured = getattr(self.mapping, 'scientific_name', None)
        value = self._get_attr(feature, configured)
        if value:
            return value

        # 2. fallback su nomi campo comuni nei tuoi dataset
        fallback_fields = [
            'taxon', 'Taxon', 'scientificName', 'scientific_name',
            'species', 'Species', 'TAXON', 'TAXON ACCEPTED',
            'Nome nella fonte', 'nome nella fonte', 'Nome della fonte', 'nome della fonte'
        ]
        field_names = feature.fields().names()
        lowered = {f.lower(): f for f in field_names}
        for name in fallback_fields:
            actual = name if name in field_names else lowered.get(name.lower())
            if actual:
                value = self._get_attr(feature, actual)
                if value:
                    return value
        return None

    def run_italic_lookup(self):
        if self.mapping is None:
            self._warn('Configura prima i campi input.')
            return
        layer = self._valid_input_or_active_layer()
        if layer is None or not self._layer_supports_fields(layer):
            self._warn('Nessun layer attivo compatibile')
            return
        self.active_layer = layer
        feature = self._selected_feature()
        if feature is None:
            self._warn('Seleziona una riga nella tabella.')
            return
        scientific_name = self._get_taxon_value(feature)
        if not scientific_name:
            self._warn('Il record non contiene un taxon/specie valida.')
            return
        profile = self.italic_service.fetch_profile(scientific_name)
        if not profile:
            self._warn('ITALIC non ha restituito un profilo.')
            return
        self.dock.set_italic_profile(profile)
        self.dock.set_status(f"Profilo ITALIC letto per: {scientific_name}")

    def _get_attr(self, feature, field_name):
        if field_name and field_name in feature.fields().names():
            value = feature[field_name]
            return str(value) if value not in [None, ''] else None
        return None

    def _geometry_to_canvas_crs(self, geometry):
        if geometry is None or geometry.isEmpty():
            return geometry
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        source_crs = QgsCoordinateReferenceSystem('EPSG:4326')
        if canvas_crs == source_crs:
            return QgsGeometry(geometry)
        transform = QgsCoordinateTransform(source_crs, canvas_crs, QgsProject.instance())
        transformed = QgsGeometry(geometry)
        transformed.transform(transform)
        return transformed

    def _zoom_to_geometry(self, geometry):
        if geometry is None or geometry.isEmpty():
            return
        canvas = self.iface.mapCanvas()
        geometry = self._geometry_to_canvas_crs(geometry)
        rect = geometry.boundingBox()
        if rect.isEmpty():
            return
        rect.scale(1.2)
        canvas.setExtent(rect)
        canvas.refresh()

    def _show_boundary_highlight(self, geometry):
        if geometry is None or geometry.isEmpty():
            return
        canvas = self.iface.mapCanvas()
        geometry = self._geometry_to_canvas_crs(geometry)
        if self.rubber_band is not None:
            try:
                canvas.scene().removeItem(self.rubber_band)
            except Exception:
                pass
            self.rubber_band = None
        geom_type = QgsWkbTypes.geometryType(geometry.wkbType())
        if geom_type == QgsWkbTypes.LineGeometry:
            rb_type = QgsWkbTypes.LineGeometry
        elif geom_type == QgsWkbTypes.PointGeometry:
            rb_type = QgsWkbTypes.PointGeometry
        else:
            rb_type = QgsWkbTypes.PolygonGeometry
        self.rubber_band = QgsRubberBand(canvas, rb_type)
        self.rubber_band.setColor(QColor(220, 30, 30, 180))
        self.rubber_band.setFillColor(QColor(220, 30, 30, 60))
        self.rubber_band.setWidth(2)
        self.rubber_band.setToGeometry(geometry, None)
        self.rubber_band.show()
