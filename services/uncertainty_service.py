"""Facade di compatibilita' per le due misure di incertezza GeoLichen.

Fase 4-5:
- ``ModelUncertaintyService`` calcola R55-S70 e confidence del modello;
- ``GbifGeoreferencingService`` calcola coordinateUncertaintyInMeters;
- questa classe mantiene la vecchia API per non alterare controller e ranking.
"""
import math

from ._shared_geo_utils import to_float as _shared_to_float
from .gbif_georeferencing_service import GbifGeoreferencingService
from .gbif_corrected_center_service import GbifCorrectedCenterService
from .model_uncertainty_service import ModelUncertaintyService
from .model_confidence_service import ModelConfidenceService
from .solution_stability_service import SolutionStabilityService
from .gbif_metadata_service import GbifMetadataService
from .gbif_locality_geometry_service import GbifLocalityGeometryService

from qgis.core import QgsDistanceArea, QgsGeometry, QgsPointXY, QgsRectangle, QgsWkbTypes


class UncertaintyService:
    def __init__(self):
        self.model_service = ModelUncertaintyService()
        self.gbif_service = GbifGeoreferencingService()
        self.corrected_center_service = GbifCorrectedCenterService()
        self.confidence_service = ModelConfidenceService()
        self.stability_service = SolutionStabilityService()
        self.gbif_metadata_service = GbifMetadataService()
        self.locality_geometry_service = GbifLocalityGeometryService()

    def estimate(
        self,
        buffer_geom,
        features_data,
        gbif_extent_geom=None,
        best_point=None,
        grid_step_m=100,
        selected_score=None,
        selected_rank=None,
        center_source="rank_1",
        source_error_m=0,
        coordinate_error_m=0,
        measurement_error_m=0,
        datum_error_m=0,
        locality_context=None,
        resolved_locality=None,
    ):
        features_data = features_data or []
        default_row = features_data[0] if features_data else {}
        center_point = best_point if best_point is not None else default_row.get("point")
        center_score = self._to_float(selected_score)
        center_rank = selected_rank
        center_row = None

        if center_point is not None and features_data:
            nearest = None
            nearest_distance = None
            for row in features_data:
                distance = self.model_service.distance_m(center_point, row.get("point"))
                if distance is None:
                    continue
                if nearest_distance is None or distance < nearest_distance:
                    nearest = row
                    nearest_distance = distance
            if nearest is not None:
                center_row = nearest
                if center_score is None:
                    center_score = self._to_float(nearest.get("score"))
                if center_rank is None:
                    center_rank = nearest.get("rank")

        if center_score is None:
            center_score = self._to_float(default_row.get("score")) or 0.0
        if center_rank is None:
            center_rank = default_row.get("rank", 1)
        if center_row is None:
            center_row = default_row

        model = self.model_service.estimate(
            buffer_geom=buffer_geom,
            features_data=features_data,
            center_point=center_point,
            center_score=center_score,
            center_row=center_row,
            grid_step_m=grid_step_m,
        )
        confidence = self.confidence_service.evaluate(
            center_score=center_score,
            score_gap=model.get("score_gap"),
            features_data=features_data,
            center_point=center_point,
            distance_func=self.model_service.distance_m,
            model_radius_m=model.get("model_radius_m"),
            buffer_radius_m=model.get("buffer_radius_m"),
            compatible_points=model.get("compatible_points", 0),
            center_row=center_row,
            locality_context=locality_context,
            selection_method=center_source,
        )
        stability = self.stability_service.evaluate(
            center_score=center_score,
            features_data=features_data,
            center_point=center_point,
            distance_func=self.model_service.distance_m,
            model_radius_m=model.get("model_radius_m"),
            grid_step_m=grid_step_m,
        )

        # Fase 12, Blocco C: la geometria documentale SLGE è la sola sorgente
        # ammessa per il point-radius GBIF. La search geometry resta confinata
        # al modello ecologico e non può restringere l'incertezza documentale.
        resolved = resolved_locality or getattr(locality_context, "resolved_locality", None)
        documented_model = getattr(resolved, "documented_geometry", None) if resolved is not None else None
        documented_geom = getattr(documented_model, "geometry", None) if documented_model is not None else None
        if documented_geom is not None:
            try:
                documented_available = not documented_geom.isEmpty()
            except Exception:
                documented_available = True
        else:
            documented_available = False

        # Ripristino della logica del 20 luglio. Le geometrie documentali con
        # estensione reale (LINE/POLYGON/ADMIN) restano la prima scelta. Quando
        # la SLGE restituisce un POINT privo di estensione, il Point-Radius viene
        # invece calcolato sull'area originale/operativa della località, cioè la
        # stessa area entro cui GeoLichen ha prodotto e valutato i candidati.
        # In questo modo i record storici puntuali non finiscono sistematicamente
        # con coordinateUncertaintyInMeters nullo.
        documented_type = str(getattr(documented_model, "geometry_type", "") or "").upper() if documented_model is not None else ""
        # Sprint 3.1: l'incertezza deve descrivere il buffer operativo
        # EFFETTIVAMENTE usato dal Candidate Engine, non il raggio nominale
        # codificato nella strategia SLGE. Per questo ``buffer_geom`` ha la
        # precedenza sulla SearchGeometry originaria del resolver.
        # Priorità:
        #   1) area operativa realmente usata per generare i candidati;
        #   2) SearchGeometry risolta dalla SLGE, come fallback;
        #   3) estensione GBIF esplicita, solo come ultimo fallback.
        resolved_search_model = getattr(resolved, "search_geometry", None) if resolved is not None else None
        resolved_search_geom = getattr(resolved_search_model, "geometry", None) if resolved_search_model is not None else None

        def _usable_geometry(value):
            try:
                return value is not None and not value.isEmpty()
            except Exception:
                return value is not None

        if _usable_geometry(buffer_geom):
            operational_extent = QgsGeometry(buffer_geom)
            operational_extent_source = "candidate_generation_effective_buffer"
        elif _usable_geometry(resolved_search_geom):
            operational_extent = QgsGeometry(resolved_search_geom)
            operational_extent_source = "slge_search_geometry_fallback"
        elif _usable_geometry(gbif_extent_geom):
            operational_extent = QgsGeometry(gbif_extent_geom)
            operational_extent_source = "explicit_gbif_extent_fallback"
        else:
            operational_extent = None
            operational_extent_source = "unavailable"

        manual_mode_name = str(getattr(locality_context, "search_geometry_mode", "") or "").casefold()
        manual_search_mode = bool(
            manual_mode_name.startswith("manual")
            and _usable_geometry(getattr(locality_context, "manual_search_geometry", None))
        )
        manual_line_mode = manual_mode_name == "manual_line"

        # Il buffer manuale è una geometria operativa esplicitamente definita
        # dall'operatore. In questa modalità il point-radius deve essere
        # calcolato dal centro manuale al bordo del buffer, senza promuovere il
        # Rank 1 a corrected center e senza dipendere dalla classificazione
        # documentale eventualmente precedente.
        if manual_search_mode:
            operational_extent = QgsGeometry(getattr(locality_context, "manual_search_geometry"))
            operational_extent_source = (
                "user_defined_manual_line_corridor" if manual_line_mode
                else "user_defined_manual_point_buffer"
            )
            use_operational_extent_for_point = True
            source_gbif_extent = operational_extent
        else:
            use_operational_extent_for_point = bool(
                documented_available and documented_type == "POINT" and _usable_geometry(operational_extent)
            )
            source_gbif_extent = (
                operational_extent if use_operational_extent_for_point
                else (documented_geom if documented_available else operational_extent)
            )
        geometry_result = self.locality_geometry_service.build(
            locality_context=locality_context,
            source_extent=source_gbif_extent,
        )
        gbif_extent = geometry_result.get("final_locality_extent") or source_gbif_extent

        # GBIF 14.1.2: when a point-like geocoder result carries a real bbox,
        # the bbox is the documentary spatial representation of the locality.
        # It must therefore become the footprint used for corrected-center and
        # point-radius calculations, rather than being added later as a generic
        # source error.
        bbox_geometry_applied = False
        if documented_model is not None and not use_operational_extent_for_point:
            try:
                documented_type = str(getattr(documented_model, "geometry_type", "") or "").upper()
                metadata = dict(getattr(documented_model, "metadata", {}) or {})
                source_bbox = metadata.get("source_bbox")
                if documented_type == "POINT" and source_bbox and len(source_bbox) == 4:
                    west, south, east, north = [float(v) for v in source_bbox]
                    if east > west and north > south:
                        gbif_extent = QgsGeometry.fromRect(QgsRectangle(west, south, east, north))
                        bbox_geometry_applied = True
            except Exception:
                bbox_geometry_applied = False

        if locality_context is not None:
            try:
                locality_context.final_locality_extent = gbif_extent
                locality_context.locality_geometry_method = geometry_result.get("locality_geometry_method", "")
                locality_context.locality_geometry_reason = geometry_result.get("locality_geometry_reason", "")
                locality_context.locality_geometry_applied = bool(geometry_result.get("locality_geometry_applied"))
                locality_context.locality_geometry_requires_verification = bool(geometry_result.get("locality_geometry_requires_verification"))
            except Exception:
                pass
        corrected = self.corrected_center_service.calculate(
            locality_context=locality_context,
            original_locality_extent=gbif_extent,
            selected_point=center_point,
        )
        corrected_center = corrected.get("corrected_center")
        if locality_context is not None and corrected_center is not None:
            try:
                locality_context.set_gbif_corrected_center(
                    corrected_center,
                    method=corrected.get("corrected_center_method"),
                    source=corrected.get("corrected_center_source"),
                    reason=corrected.get("corrected_center_reason"),
                )
            except Exception:
                pass

        # Dynamic documentary uncertainty is calculated for every geometry
        # type. The geometry itself supplies the point-radius component in
        # GbifGeoreferencingService; source metadata and semantic safeguards
        # are handled here without using the ecological SearchGeometry.
        geometry_components = self._geometry_uncertainty_components(
            documented_model=documented_model,
            resolved_locality=resolved,
            corrected_center=corrected_center,
            explicit_source_error_m=source_error_m,
        )
        effective_source_error_m = geometry_components.get("effective_source_error_m", 0.0)

        gbif = self.gbif_service.estimate(
            corrected_center=corrected_center,
            original_locality_extent=gbif_extent,
            grid_step_m=grid_step_m,
            source_error_m=effective_source_error_m,
            coordinate_error_m=coordinate_error_m,
            measurement_error_m=measurement_error_m,
            datum_error_m=datum_error_m,
        )

        # Convenzione GeoLichen per il corridoio manuale: su esplicita scelta
        # dell'operatore, l'incertezza lineare è la lunghezza totale dell'asse
        # disegnato. L'offset serve solo a costruire la Search Geometry.
        if manual_line_mode:
            line_length_m = self._to_float(getattr(locality_context, "manual_line_length_m", None))
            line_offset_m = self._to_float(getattr(locality_context, "manual_line_offset_m", None))
            if line_length_m is not None and line_length_m > 0:
                gbif["geometric_point_radius_m"] = gbif.get("geographic_radial_m")
                gbif["coordinate_uncertainty_m"] = round(line_length_m, 1)
                gbif["gbif_uncertainty_m"] = round(line_length_m, 1)
                gbif["manual_linear_uncertainty_m"] = round(line_length_m, 1)
                gbif["manual_line_length_m"] = round(line_length_m, 1)
                gbif["manual_line_offset_m"] = round(line_offset_m, 1) if line_offset_m is not None else None
                gbif["uncertainty_method"] = "manual_linear_locality_length"
                gbif["gbif_method"] = (
                    "GeoLichen manual linear-locality convention: uncertainty equals "
                    "the full user-drawn line length; lateral offset defines only the corridor"
                )
                gbif["gbif_extent_source"] = "manual_line_corridor"

        # Sprint 2.1: una bbox dichiarata come POLYGON può in realtà essere
        # degenerata o quasi puntuale. In quel caso il radial geografico vale
        # zero e il precedente limite tecnico di 1 m veniva mostrato come vera
        # incertezza GBIF. La geometria documentale resta prioritaria soltanto
        # quando produce un'estensione spaziale significativa; altrimenti si
        # usa la SearchGeometry operativa realmente impiegata per i candidati.
        geographic_radial = self._to_float(gbif.get("geographic_radial_m"))
        degenerate_documented_extent = bool(
            documented_available
            and not use_operational_extent_for_point
            and gbif.get("gbif_calculable")
            and geographic_radial is not None
            and geographic_radial <= 1.0
            and _usable_geometry(operational_extent)
        )
        if degenerate_documented_extent:
            fallback_extent = QgsGeometry(operational_extent)
            fallback_corrected = self.corrected_center_service.calculate(
                locality_context=locality_context,
                original_locality_extent=fallback_extent,
                selected_point=center_point,
            )
            fallback_center = fallback_corrected.get("corrected_center")
            fallback_gbif = self.gbif_service.estimate(
                corrected_center=fallback_center,
                original_locality_extent=fallback_extent,
                grid_step_m=grid_step_m,
                source_error_m=effective_source_error_m,
                coordinate_error_m=coordinate_error_m,
                measurement_error_m=measurement_error_m,
                datum_error_m=datum_error_m,
            )
            fallback_radial = self._to_float(fallback_gbif.get("geographic_radial_m"))
            if fallback_gbif.get("gbif_calculable") and fallback_radial is not None and fallback_radial > 1.0:
                gbif_extent = fallback_extent
                gbif = fallback_gbif
                corrected = fallback_corrected
                corrected_center = fallback_center
                use_operational_extent_for_point = True
                operational_extent_source = operational_extent_source or "candidate_generation_search_geometry"
                gbif["degenerate_documented_extent_fallback"] = True
                gbif["degenerate_documented_radial_m"] = geographic_radial
                gbif["gbif_extent_source"] = "operational_search_geometry_degenerate_documented_fallback"
                if locality_context is not None:
                    try:
                        locality_context.final_locality_extent = gbif_extent
                        locality_context.set_gbif_corrected_center(
                            corrected_center,
                            method=corrected.get("corrected_center_method"),
                            source=corrected.get("corrected_center_source"),
                            reason=corrected.get("corrected_center_reason"),
                        )
                    except Exception:
                        pass

        # Per le geometrie POINT prive di bbox/accuracy, l'estensione operativa
        # ripristinata sopra fornisce il radial geografico. Non forziamo quindi
        # il risultato a "non calcolabile".
        gbif["gbif_bbox_geometry_applied"] = bbox_geometry_applied
        gbif["gbif_operational_extent_used"] = use_operational_extent_for_point
        gbif["gbif_operational_extent_source"] = operational_extent_source
        if gbif.get("degenerate_documented_extent_fallback"):
            gbif["gbif_extent_source"] = "operational_search_geometry_degenerate_documented_fallback"
        else:
            gbif["gbif_extent_source"] = (
                ("manual_point_buffer" if manual_search_mode else "operational_search_geometry_for_point")
                if use_operational_extent_for_point
                else ("slge_documented_geometry" if documented_available else gbif.get("gbif_extent_source"))
            )
        gbif["uncertainty_geometry_source"] = gbif.get("gbif_extent_source")
        gbif["uncertainty_method"] = gbif.get("uncertainty_method") or "gbif_point_radius"

        # Sprint 3.1: nessun limite minimo viene più ricavato dal nome della
        # strategia (es. ``point_buffer_1000m``). Il radial misurato sulla
        # geometria operativa è il valore autorevole. In questo modo un buffer
        # effettivo di circa 650 m produce un'incertezza di circa 650 m, mentre
        # la risoluzione della griglia resta separata.
        effective_radial = self._to_float(gbif.get("geographic_radial_m"))
        gbif["effective_search_geometry_used"] = bool(use_operational_extent_for_point)
        gbif["effective_search_geometry_source"] = operational_extent_source
        gbif["effective_buffer_radius_m"] = (
            round(float(effective_radial), 1)
            if use_operational_extent_for_point and effective_radial is not None
            else None
        )

        # Sprint 3.3: diagnostica della geometria operativa finale. Questi
        # valori servono esclusivamente a GUI, report ed explainability e non
        # modificano GSS, ranking o coordinateUncertaintyInMeters.
        effective_geom = operational_extent if _usable_geometry(operational_extent) else None
        effective_geometry_type = None
        effective_vertex_count = None
        effective_area_ha = None
        if effective_geom is not None:
            try:
                effective_geometry_type = QgsWkbTypes.displayString(effective_geom.wkbType())
            except Exception:
                try:
                    effective_geometry_type = str(effective_geom.type())
                except Exception:
                    effective_geometry_type = None
            try:
                effective_vertex_count = sum(1 for _ in effective_geom.vertices())
            except Exception:
                effective_vertex_count = None
            try:
                distance_area = QgsDistanceArea()
                distance_area.setEllipsoid("WGS84")
                measured_area = float(distance_area.measureArea(effective_geom))
                if measured_area > 0:
                    effective_area_ha = round(measured_area / 10000.0, 2)
            except Exception:
                effective_area_ha = None

        gbif["effective_search_geometry_type"] = effective_geometry_type
        gbif["effective_search_geometry_vertex_count"] = effective_vertex_count
        gbif["effective_search_geometry_area_ha"] = effective_area_ha
        gbif["effective_search_geometry_clipped"] = bool(
            getattr(resolved_search_model, "clipped", False)
        ) if resolved_search_model is not None else False
        gbif["effective_search_geometry_expanded"] = bool(
            getattr(resolved_search_model, "expanded", False)
        ) if resolved_search_model is not None else False
        gbif["declared_operational_radius_floor_applied"] = False
        gbif["declared_operational_radius_m"] = None
        if use_operational_extent_for_point and gbif.get("gbif_calculable"):
            gbif["uncertainty_method"] = "gbif_point_radius_effective_buffer"
        # Canonical Sprint-2 field. The old grid_error_m alias remains readable,
        # but must never be interpreted as coordinate uncertainty.
        gbif["candidate_resolution_m"] = gbif.get("candidate_resolution_m")
        if gbif.get("candidate_resolution_m") is None:
            gbif["candidate_resolution_m"] = model.get("candidate_resolution_m")
        gbif.update(geometry_components)

        if locality_context is not None:
            for name, value in (
                ("candidate_resolution_m", gbif.get("candidate_resolution_m")),
                ("gbif_uncertainty_m", gbif.get("coordinate_uncertainty_m")),
                ("uncertainty_geometry_source", gbif.get("uncertainty_geometry_source")),
                ("uncertainty_method", gbif.get("uncertainty_method")),
                ("effective_buffer_radius_m", gbif.get("effective_buffer_radius_m")),
                ("effective_search_geometry_source", gbif.get("effective_search_geometry_source")),
                ("effective_search_geometry_type", gbif.get("effective_search_geometry_type")),
                ("effective_search_geometry_vertex_count", gbif.get("effective_search_geometry_vertex_count")),
                ("effective_search_geometry_area_ha", gbif.get("effective_search_geometry_area_ha")),
                ("effective_search_geometry_clipped", gbif.get("effective_search_geometry_clipped")),
                ("effective_search_geometry_expanded", gbif.get("effective_search_geometry_expanded")),
            ):
                try:
                    setattr(locality_context, name, value)
                except Exception:
                    pass

        dwc = self.gbif_metadata_service.build(
            corrected_center=corrected_center,
            original_locality_extent=gbif_extent,
            gbif_result=gbif,
            corrected_center_result=corrected,
            locality_context=locality_context,
            constraint_metadata=(center_row or {}).get("constraint_metadata") or [],
        )

        result = {}
        result.update(model)
        result.update(confidence)
        result.update(stability)
        result.update(gbif)
        result.update(corrected)
        result.update(geometry_result)
        result.update(dwc)
        slge_metadata = {}
        if resolved is not None:
            try:
                slge_metadata = resolved.as_dict()
            except Exception:
                slge_metadata = {}
        terrain_integration = {}
        terrain_documented_metadata = {}
        if resolved is not None:
            try:
                terrain_integration = dict((getattr(resolved, "provenance", {}) or {}).get("terrain_integration") or {})
            except Exception:
                terrain_integration = {}
        if documented_model is not None:
            try:
                terrain_documented_metadata = dict(getattr(documented_model, "metadata", {}) or {})
            except Exception:
                terrain_documented_metadata = {}

        result.update({
            # Alias storico: resta GBIF, mai il raggio del modello.
            "uncertainty_m": gbif.get("coordinate_uncertainty_m"),
            "gbif_uncertainty_m": gbif.get("coordinate_uncertainty_m"),
            "candidate_resolution_m": gbif.get("candidate_resolution_m"),
            "uncertainty_geometry_source": gbif.get("uncertainty_geometry_source"),
            "uncertainty_method": gbif.get("uncertainty_method"),
            "confidence": confidence.get("model_confidence"),
            "uncertainty_center_rank": center_rank,
            "uncertainty_center_score": round(float(center_score), 3),
            "uncertainty_center_source": center_source,
            "method": "gbif_corrected_center_point_radius_and_separate_model_R55_S65",
            "slge_active": bool(resolved is not None),
            "slge_documented_geometry_used": bool(documented_available),
            "slge_geometry_confidence": getattr(resolved, "geometry_confidence", None) if resolved is not None else None,
            "slge_geometry_confidence_class": getattr(resolved, "geometry_confidence_class", None) if resolved is not None else None,
            "slge_geometry_confidence_reasons": list(getattr(resolved, "geometry_confidence_reasons", ()) or ()) if resolved is not None else [],
            "slge_requires_review": getattr(resolved, "requires_review", False) if resolved is not None else False,
            "slge_feature_type": getattr(getattr(resolved, "interpretation", None), "feature_type", None) if resolved is not None else None,
            "slge_expected_geometry": getattr(getattr(resolved, "interpretation", None), "expected_geometry", None) if resolved is not None else None,
            "slge_semantic_confidence": getattr(getattr(resolved, "interpretation", None), "confidence", None) if resolved is not None else None,
            "slge_matched_rule": getattr(getattr(resolved, "interpretation", None), "matched_rule", None) if resolved is not None else None,
            "slge_documented_source": getattr(documented_model, "source", None) if documented_model is not None else None,
            "slge_documented_method": getattr(documented_model, "method", None) if documented_model is not None else None,
            "slge_documented_geometry_type": getattr(documented_model, "geometry_type", None) if documented_model is not None else None,
            "slge_documented_estimated": getattr(documented_model, "estimated", False) if documented_model is not None else False,
            "slge_documented_source_identifier": getattr(documented_model, "source_identifier", None) if documented_model is not None else None,
            "slge_documented_source_label": (getattr(documented_model, "metadata", {}) or {}).get("source_label") if documented_model is not None else None,
            "slge_documented_method_label": (getattr(documented_model, "metadata", {}) or {}).get("method_label") if documented_model is not None else None,
            "slge_unified": bool((getattr(documented_model, "metadata", {}) or {}).get("unified_slge")) if documented_model is not None else False,
            "slge_documented_available": bool(documented_available),
            "slge_search_strategy": getattr(getattr(resolved, "search_geometry", None), "strategy", None) if resolved is not None else None,
            "slge_search_source": getattr(getattr(resolved, "search_geometry", None), "source", None) if resolved is not None else None,
            "slge_search_expanded": bool(getattr(getattr(resolved, "search_geometry", None), "expanded", False)) if resolved is not None else False,
            "slge_search_clipped": bool(getattr(getattr(resolved, "search_geometry", None), "clipped", False)) if resolved is not None else False,
            "slge_search_filters": list(getattr(getattr(resolved, "search_geometry", None), "filters", []) or []) if resolved is not None else [],
            "slge_administrative_geometry_diagnostics": dict(
                ((getattr(getattr(resolved, "search_geometry", None), "metadata", {}) or {}).get("administrative_geometry_diagnostics") or {})
            ) if resolved is not None else {},
            "slge_provenance": slge_metadata,
            "gre_active": bool((getattr(resolved, "provenance", {}) or {}).get("geometry_resolution_engine")) if resolved is not None else False,
            "gre_resolver": (getattr(resolved, "provenance", {}) or {}).get("gre_resolver") if resolved is not None else None,
            "gre_decision": (getattr(resolved, "provenance", {}) or {}).get("gre_decision") if resolved is not None else None,
            "gre_source": (getattr(resolved, "provenance", {}) or {}).get("gre_source") if resolved is not None else None,
            "gre_method": (getattr(resolved, "provenance", {}) or {}).get("gre_method") if resolved is not None else None,
            "gre_geometry_type": (getattr(resolved, "provenance", {}) or {}).get("gre_geometry_type") if resolved is not None else None,
            "gre_confidence": (getattr(resolved, "provenance", {}) or {}).get("gre_confidence") if resolved is not None else None,
            "gre_fallback_used": bool((getattr(resolved, "provenance", {}) or {}).get("gre_fallback_used")) if resolved is not None else False,
            # Phase 13D.4 — diagnostica esplicita della ricostruzione terrain.
            "terrain_reconstruction_available": bool(
                terrain_integration and (
                    terrain_integration.get("applied")
                    or terrain_documented_metadata.get("terrain_validation_confidence") is not None
                    or terrain_documented_metadata.get("summit_elevation_m") is not None
                )
            ),
            "terrain_reconstruction_used": bool(terrain_integration.get("applied")),
            "terrain_selected_source": terrain_integration.get("selected_source") or getattr(documented_model, "source", None),
            "terrain_fallback_used": not bool(terrain_integration.get("applied")) if terrain_integration else False,
            "terrain_manual_review_required": bool(terrain_integration.get("manual_review_required")),
            "terrain_decision": terrain_integration.get("decision") or (terrain_integration.get("decision_summary") or {}).get("decision"),
            "terrain_decision_confidence": terrain_documented_metadata.get("terrain_decision_confidence"),
            "terrain_validation_confidence": terrain_documented_metadata.get("terrain_validation_confidence"),
            "terrain_polygon_area_m2": terrain_documented_metadata.get("terrain_area_m2"),
            "terrain_polygon_area_km2": terrain_documented_metadata.get("terrain_area_km2"),
            "terrain_polygon_compactness": terrain_documented_metadata.get("terrain_compactness"),
            "terrain_polygon_max_distance_m": terrain_documented_metadata.get("terrain_maximum_distance_m"),
            "terrain_summit_elevation_m": terrain_documented_metadata.get("summit_elevation_m"),
            "terrain_summit_prominence_m": terrain_documented_metadata.get("summit_prominence_m"),
            "terrain_summit_distance_from_anchor_m": terrain_documented_metadata.get("summit_distance_from_anchor_m"),
            "terrain_dem_layer_name": terrain_documented_metadata.get("dem_layer_name"),
            "terrain_dem_source": terrain_documented_metadata.get("dem_source"),
            "terrain_dem_resolution_m": terrain_documented_metadata.get("dem_resolution_m"),
            "terrain_dem_coverage_ratio": terrain_documented_metadata.get("dem_coverage_ratio"),
            "terrain_integration_provenance": terrain_integration,
            "gbif_extent_source": gbif.get("gbif_extent_source"),
            "gbif_operational_extent_used": use_operational_extent_for_point,
            "gbif_operational_extent_source": operational_extent_source,
        })
        return result

    def _distance_m(self, point_a, point_b):
        """Alias temporaneo usato dal controller per lo snap manuale."""
        return self.model_service.distance_m(point_a, point_b)

    @classmethod
    def _geometry_uncertainty_components(
        cls,
        documented_model=None,
        resolved_locality=None,
        corrected_center=None,
        explicit_source_error_m=0,
    ):
        """Return documented source errors and a separate semantic suggestion.

        The locality geometry supplies the geographic radial. A provider bbox
        is converted into documentary geometry upstream and is never added a
        second time as source error. Semantic minima are advisory only and are
        not written automatically to Darwin Core.
        """
        explicit_m = cls._nonnegative_value(explicit_source_error_m)
        if documented_model is None:
            return {
                "effective_source_error_m": explicit_m,
                "geometry_uncertainty_calculated": False,
                "point_uncertainty_calculated": False,
                "semantic_suggestion_applied": False,
            }

        geometry_type = str(getattr(documented_model, "geometry_type", "") or "UNKNOWN").upper()
        metadata = dict(getattr(documented_model, "metadata", {}) or {})
        provider_accuracy_m = max(
            cls._nonnegative_value(metadata.get("source_accuracy_m")),
            cls._nonnegative_value(metadata.get("accuracy_m")),
            cls._nonnegative_value(metadata.get("provider_accuracy_m")),
        )
        bbox_radius_m = cls._bbox_radius_m(metadata.get("source_bbox"), corrected_center)
        suggestion_m, suggestion_reason = cls._geometry_uncertainty_floor(
            documented_model=documented_model,
            resolved_locality=resolved_locality,
        )

        independent = {
            "accuratezza_fonte": provider_accuracy_m,
            "errore_fonte_esplicito": explicit_m,
        }
        dominant_key, dominant_value = max(independent.items(), key=lambda item: float(item[1] or 0.0))
        labels = {
            "accuratezza_fonte": "Accuratezza documentata dalla fonte",
            "errore_fonte_esplicito": "Errore della fonte fornito al calcolo",
        }
        result = {
            "effective_source_error_m": float(dominant_value or 0.0),
            "geometry_uncertainty_calculated": True,
            "geometry_uncertainty_geometry_type": geometry_type,
            "geometry_uncertainty_bbox_m": round(bbox_radius_m, 1),
            "geometry_uncertainty_bbox_used_as_source": False,
            "geometry_uncertainty_bbox_used_as_geometry": bool(geometry_type == "POINT" and bbox_radius_m > 0),
            "geometry_uncertainty_provider_accuracy_m": round(provider_accuracy_m, 1),
            "geometry_uncertainty_explicit_source_m": round(explicit_m, 1),
            "geometry_uncertainty_floor_m": round(suggestion_m, 1),
            "geometry_uncertainty_floor_reason": suggestion_reason,
            "semantic_suggestion_m": round(suggestion_m, 1),
            "semantic_suggestion_reason": suggestion_reason,
            "semantic_suggestion_applied": False,
            "geometry_uncertainty_dominant_component": dominant_key if dominant_value > 0 else "none",
            "geometry_uncertainty_dominant_label": labels.get(dominant_key, dominant_key) if dominant_value > 0 else "Nessun errore documentato aggiuntivo",
            "geometry_uncertainty_dominant_m": round(float(dominant_value or 0.0), 1),
            "geometry_uncertainty_method": "documentary geometry radial + documented independent errors; semantic suggestion not applied",
            "point_uncertainty_calculated": geometry_type == "POINT",
            "point_uncertainty_bbox_m": round(bbox_radius_m, 1),
            "point_uncertainty_provider_accuracy_m": round(provider_accuracy_m, 1),
            "point_uncertainty_explicit_source_m": round(explicit_m, 1),
            "point_uncertainty_floor_m": round(suggestion_m, 1),
            "point_uncertainty_floor_reason": suggestion_reason,
            "point_uncertainty_dominant_component": dominant_key if dominant_value > 0 else "none",
            "point_uncertainty_dominant_label": labels.get(dominant_key, dominant_key) if dominant_value > 0 else "Nessun errore documentato aggiuntivo",
            "point_uncertainty_dominant_m": round(float(dominant_value or 0.0), 1),
            "point_uncertainty_method": "bbox as documentary geometry; documented source errors only; semantic suggestion not applied",
        }
        return result

    # Compatibility alias for extensions that still call the old private API.
    _point_uncertainty_components = _geometry_uncertainty_components

    @staticmethod
    def _nonnegative_value(value):
        try:
            parsed = float(value)
            return parsed if parsed > 0 else 0.0
        except Exception:
            return 0.0

    @classmethod
    def _bbox_radius_m(cls, bbox, corrected_center):
        """Maximum geodesic distance from corrected centre to bbox corners."""
        if corrected_center is None or not bbox or len(bbox) != 4:
            return 0.0
        try:
            lon = float(corrected_center.x())
            lat = float(corrected_center.y())
            west, south, east, north = [float(v) for v in bbox]
        except Exception:
            return 0.0
        return max(
            cls._haversine_m(lon, lat, x, y)
            for x, y in ((west, south), (west, north), (east, south), (east, north))
        )

    @staticmethod
    def _haversine_m(lon1, lat1, lon2, lat2):
        radius = 6371000.0
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
        return 2.0 * radius * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))

    @classmethod
    def _geometry_uncertainty_floor(cls, documented_model=None, resolved_locality=None):
        """Return a conservative floor only when geometry cannot express extent.

        POINT localities need a semantic safety net because their documentary
        geometry has zero radius. LINE, POLYGON and ADMIN geometries already
        express their extent dynamically and therefore receive no fixed floor.
        """
        if documented_model is None:
            return 0.0, ""
        geometry_type = str(getattr(documented_model, "geometry_type", "") or "").upper()
        if geometry_type != "POINT":
            return 0.0, ""

        source = str(getattr(documented_model, "source", "") or "").lower()
        feature_type = str(getattr(documented_model, "feature_type", "") or "").lower()
        if resolved_locality is not None:
            feature_type = str(
                getattr(getattr(resolved_locality, "interpretation", None), "feature_type", feature_type)
                or feature_type
            ).lower()

        # Official/OSM points have a smaller source error than generic geocoder
        # anchors; point proxies for linear features remain deliberately broad.
        if source == "official_point":
            floor = 10.0
        elif source == "osm_point":
            floor = 20.0
        elif source == "point_proxy":
            floor = 150.0
        else:
            floor = {
                "pass": 100.0,
                "peak": 50.0,
                "refuge": 30.0,
                "church": 20.0,
                "generic_locality": 100.0,
                "unknown": 100.0,
            }.get(feature_type, 100.0)

        reason = (
            f"Soglia minima per geometria puntuale ({feature_type or 'località'}, "
            f"sorgente {source or 'non specificata'})"
        )
        return float(floor), reason

    _point_uncertainty_floor = _geometry_uncertainty_floor

    @staticmethod
    def _to_float(value):
        return _shared_to_float(value)
