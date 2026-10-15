import math
import re
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

from ._shared_geo_utils import (
    to_float as _shared_to_float,
    local_metric_crs as _shared_local_metric_crs,
)
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsMapLayerType,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsSpatialIndex,
    QgsRasterLayer,
    QgsRaster,
    QgsSingleBandPseudoColorRenderer,
    QgsColorRampShader,
    QgsRasterShader,
    QgsMarkerSymbol,
    QgsRuleBasedRenderer,
)

try:
    from qgis.core import QgsHeatmapRenderer, Qgis
except Exception:
    QgsHeatmapRenderer = None
    Qgis = None

try:
    from qgis.PyQt.QtGui import QColor
    from qgis.core import QgsGradientColorRamp, QgsGradientStop
except Exception:
    QColor = None
    QgsGradientColorRamp = None
    QgsGradientStop = None
from qgis.PyQt.QtCore import QVariant

from .uncertainty_service import UncertaintyService
from .soil_service import SoilService
from .tree_service import TreeService
from .accessibility_engine import AccessibilityEngine
from .scoring_model import ScoringModel


@dataclass(frozen=True)
class EcologicalContext:
    """Contesto ecologico risolto e condiviso tra habitat e scoring.

    Il contesto non riclassifica il reperto: espone la decisione già prodotta
    dal resolver centrale e mantiene separate osservazioni del cartellino,
    profilo ITALIC ed evidenze GIS del singolo candidato.
    """

    substrate_group: str = "unknown"
    substrate_source: str = "unknown"
    substrate_locked: bool = False
    substrate_confidence: object = None
    substrate_resolution_reason: object = None
    rock_type: object = None
    tree_type: object = None
    soil_traits: object = None
    habitat_evidence: object = None
    italic_profile: object = None
    layer_decision: object = None
    primary_pipeline: str = "generic"
    record_substrate: object = None
    record_habitat: object = None
    record_notes: object = None

    def to_dict(self):
        return asdict(self)


class HabitatSuitabilityService:
    """
    Cerca il punto ecologicamente più probabile dentro un buffer.

    Versione completa v1.8:
    - griglia punti dentro il buffer
    - Top 10 punti migliori
    - lettura litologia/suolo/alberi da layer vettoriali
    - quota da DEM
    - pendenza stimata da DEM
    - aspect/esposizione stimata da DEM
    - layer punti con attributi completi
    """

    def __init__(self, ecology_engine, grid_step_m=100, top_n=10, dem_min_tolerance_m=10):
        self.ecology_engine = ecology_engine
        self.grid_step_m = grid_step_m
        self.top_n = top_n
        self.dem_min_tolerance_m = dem_min_tolerance_m
        self.uncertainty_service = UncertaintyService()
        self.soil_service = SoilService()
        self.tree_service = TreeService()
        self.accessibility_engine = AccessibilityEngine()
        self.scoring_model = ScoringModel()

    def find_best_point(
        self,
        buffer_geom,
        profile,
        original_locality_extent=None,
        search_extent=None,
        constraint_metadata=None,
        geology_layer=None,
        geology_field=None,
        soil_layer=None,
        soil_field=None,
        trees_layer=None,
        trees_field=None,
        trail_layer=None,
        trail_layers=None,
        vegetation_belt_layer=None,
        vegetation_belt_field=None,
        dem_layer=None,
        dem_layers=None,
        dem_band=1,
        grid_step_m=None,
        top_n=None,
        create_layer=True,
        layer_name="Habitat suitability points",
        visualization_mode="points",
        heatmap_radius_mm=18,
        heatmap_opacity=0.60,
        context=None,
        context_point=None,
        locality_context=None,
        _candidate_points=None,
        _ranking_center=None,
        _adaptive_refinement=True,
    ):
        if buffer_geom is None or buffer_geom.isEmpty():
            raise ValueError("Buffer assente o vuoto")

        profile = profile or {}
        grid_step_m = grid_step_m or self.grid_step_m
        top_n = top_n or self.top_n

        try:
            grid_step_m = float(grid_step_m)
        except Exception:
            grid_step_m = self.grid_step_m
        if grid_step_m <= 0:
            grid_step_m = self.grid_step_m

        points = list(_candidate_points or [])
        if not points:
            points = self._generate_grid_points(buffer_geom, grid_step_m)
        if not points:
            centroid = buffer_geom.centroid()
            if centroid and not centroid.isEmpty():
                points = [centroid.asPoint()]
            else:
                raise ValueError("Impossibile generare punti nel buffer")

        if _ranking_center is not None:
            center = _ranking_center
        else:
            center = buffer_geom.centroid().asPoint() if buffer_geom.centroid() and not buffer_geom.centroid().isEmpty() else None

        self._current_context = getattr(self, "_current_context", {}) or {}
        try:
            self._current_context_point = context_point if context_point is not None else center
        except Exception:
            self._current_context_point = center

        # GeoLichen 1.8.1: contesto salvato sul servizio per evitare keyword
        # argument in _build_env_for_point e problemi di cache/reload QGIS.
        self._current_context = getattr(self, "_current_context", {}) or {}
        try:
            self._current_context_point = context_point if context_point is not None else center
        except Exception:
            self._current_context_point = center

        context = getattr(self, "_current_context", {}) or {}
        context_point_metric = None
        try:
            if context_point is not None:
                context_point_metric = context_point
            else:
                context_point_metric = center
        except Exception:
            context_point_metric = center

        # v1.7.1: indice/cache sentieri preparato una sola volta.
        if trail_layers is None:
            trail_layers = []
        try:
            if trail_layer is not None and trail_layer not in trail_layers:
                trail_layers = [trail_layer] + list(trail_layers)
        except Exception:
            pass
        trail_context = self._prepare_trail_context(trail_layer, buffer_geom)
        access_contexts = self._prepare_accessibility_contexts_v293(trail_layers, buffer_geom)

        features_data = []
        excluded_by_altitude = 0
        excluded_by_vegetation_belt = 0
        for idx, pt in enumerate(points, start=1):
            env = self._build_env_for_point(
                pt,
                geology_layer=geology_layer,
                geology_field=geology_field,
                soil_layer=soil_layer,
                soil_field=soil_field,
                trees_layer=trees_layer,
                trees_field=trees_field,
                trail_layer=trail_layer,
                trail_context=trail_context,
                access_contexts=access_contexts,
                vegetation_belt_layer=vegetation_belt_layer,
                vegetation_belt_field=vegetation_belt_field,
                dem_layer=dem_layer,
                dem_layers=dem_layers,
                dem_band=dem_band,
            )
            env["distance_to_center_m"] = self._distance_m(center, pt) if center else None

            env = self._refine_env_with_profile(env, profile)
            env = self._attach_record_altitude(env, profile)
            env = self._apply_lithology_soil_ph_proxy(env, profile)
            try:
                expected_ph = self.soil_service.infer_ph_preference(profile)
                if env.get("soil_ph_num") is not None:
                    ph_cls, ph_score, ph_reason = self.soil_service.numeric_ph_compatibility(env.get("soil_ph_num"), expected_ph)
                    env["soil_ph_class"] = ph_cls or env.get("soil_ph_class")
                    env["ph_score"] = ph_score
                    env["ph_reason"] = ph_reason
                    env["litho_soil_ph_score"] = ph_score
                    env["litho_soil_ph_match"] = "numeric_ph"
                    env["soil_confidence"] = "numeric"
                    env["soil_confidence_score"] = ph_score
                    env["soil_confidence_reason"] = ph_reason
            except Exception:
                pass
            env = self._apply_tree_match_proxy(env, profile)
            # GeoLichen 2.3 Stable: distanza bosco con profilo disponibile.
            try:
                env["forest_dist_score"] = max(0.0, float(self._forest_distance_score(profile, env.get("forest_dist_m")) or 0.0))
            except Exception:
                env["forest_dist_score"] = 0.0
            env = self._apply_record_aspect_preference(env, profile)

            altitude_decision = self._altitude_prefilter_decision(env, profile)
            env["altitude_filter_type"] = altitude_decision.get("type")
            env["altitude_tolerance_m"] = altitude_decision.get("tolerance_m")
            env["altitude_min_ok"] = altitude_decision.get("min_altitude")
            env["altitude_max_ok"] = altitude_decision.get("max_altitude")
            env["altitude_filter_reason"] = altitude_decision.get("reason")
            env["italic_altitude_class_min"] = profile.get("italic_altitude_class_min")
            env["italic_altitude_class_max"] = profile.get("italic_altitude_class_max")
            env["altitudinal_distribution_source"] = profile.get("altitudinal_distribution_source")

            # GeoLichen 14.0.7: ripristino del filtro altitudinale HARD.
            # Quando il cartellino contiene una quota esplicita, restano candidati
            # solo i punti DEM compresi nella tolleranza determinata dalla precisione
            # della quota. In mappa rimane quindi la fascia/isolinea compatibile.
            strict_altitude = self._strict_record_altitude_decision_v283(env)
            if strict_altitude.get("type") != "no_record_altitude":
                env["altitude_filter_type"] = strict_altitude.get("type")
                env["altitude_filter_reason"] = strict_altitude.get("reason")
                env["altitude_tolerance_m"] = strict_altitude.get("tolerance_m") or env.get("altitude_tolerance_m")
                env["altitude_min_ok"] = strict_altitude.get("min_altitude") or env.get("altitude_min_ok")
                env["altitude_max_ok"] = strict_altitude.get("max_altitude") or env.get("altitude_max_ok")
                if strict_altitude.get("delta_m") is not None:
                    env["alt_delta_m"] = strict_altitude.get("delta_m")
                if strict_altitude.get("exclude"):
                    excluded_by_altitude += 1
                    # Il filtro della quota esplicita è un vincolo HARD: il punto
                    # non entra né nello scoring, né nel ranking, né nel layer finale.
                    continue

            if altitude_decision.get("exclude"):
                excluded_by_altitude += 1
                env["altitude_flagged_implausible"] = True

            if self._exclude_by_vegetation_belt(env, profile):
                excluded_by_vegetation_belt += 1
                env["vegetation_belt_flagged_implausible"] = True

            terrain_decision = self._terrain_prefilter_v284(env, profile)
            env["terrain_score"] = terrain_decision.get("score")
            env["terrain_reason"] = terrain_decision.get("reason")
            # GeoLichen 2.9.1: la pendenza non elimina più candidati.
            # Eventuali pendenze elevate vengono gestite solo come penalità di ranking.
            score_result = self.ecology_engine.compute_score(profile, env)
            env["ecological_score"] = score_result.get("ecological_score")

            # GeoLichen 1.8 context-aware:
            # sostituisce l'accessibility_score basato solo sui sentieri con quello
            # contestuale, se calcolato da AccessibilityEngine.
            base_acc = env.get("accessibility_score")
            if base_acc is None:
                base_acc = score_result.get("accessibility_score")
                env["accessibility_score"] = base_acc

            try:
                eco_component = float(env.get("ecological_score") or 0.0)
                record_component = self._record_score_from_env_v282(env, profile)
                acc_component = float(env.get("accessibility_confidence") if env.get("accessibility_confidence") is not None else (env.get("accessibility_score") if env.get("accessibility_score") is not None else 50.0))
                geo_component = self._geography_score_from_env_v282(env)

                score = max(0, min(100, self._final_score_v282(
                    ecological_score=eco_component,
                    record_score=record_component,
                    accessibility_confidence=acc_component,
                    geography_score=geo_component,
                )))

                slope_penalty = self._slope_penalty_v291(env, profile)
                slope_penalty_value = float(slope_penalty.get("penalty") or 0.0)
                score = max(0, min(100, float(score) + slope_penalty_value))

                env["record_score"] = record_component
                env["accessibility_confidence"] = acc_component
                env["geography_score"] = geo_component
                env["slope_penalty"] = slope_penalty_value
                env["slope_penalty_reason"] = slope_penalty.get("reason")
                env["slope_context"] = slope_penalty.get("context")
                env["final_score"] = score

                score_result["score"] = int(round(score))
                score_result["raw_score"] = score
                score_result["record_score"] = record_component
                score_result["accessibility_score"] = acc_component
                score_result["accessibility_confidence"] = acc_component
                score_result["geography_score"] = geo_component
                score_result.setdefault("details", []).append(
                    "score finale = 0.50*ecologia({}) + 0.35*cartellino({}) + 0.10*accessibilità({}) + 0.05*geografia({}); penalità pendenza={}".format(
                        round(eco_component,1), round(record_component,1), round(acc_component,1), round(geo_component,1), round(slope_penalty_value,1)
                    )
                )
                score_result = self._append_ranking_diagnostics_v292(score_result, env)
            except Exception:
                score = score_result.get("score", 0)
                env["accessibility_score"] = score_result.get("accessibility_score")
            try:
                litho_soil_ph_score = float(env.get("litho_soil_ph_score") or 0.0)
                score = max(0, min(100, float(score) + litho_soil_ph_score))
                if litho_soil_ph_score:
                    score_result.setdefault("details", []).append(
                        f"pH/suolo: {env.get('soil_confidence')} ({round(litho_soil_ph_score,1)}); {env.get('soil_confidence_reason')}; soil_ph={env.get('soil_ph')}; soil_ph_num={env.get('soil_ph_num')}; litho_ph={env.get('litho_soil_ph')}"
                    )
            except Exception:
                pass
            try:
                tree_match_score = max(0.0, float(env.get("tree_match_score") or 0.0))
                env["tree_match_score"] = tree_match_score
                score = max(0, min(100, float(score) + tree_match_score))
                if env.get("tree_match_reason"):
                    score_result.setdefault("details", []).append(
                        f"forofita cartellino/foresta: {env.get('tree_match_reason')} ({round(tree_match_score,1)})"
                    )
            except Exception:
                pass

            try:
                forest_dist_score = max(0.0, float(env.get("forest_dist_score") or 0.0))
                env["forest_dist_score"] = forest_dist_score
                score = max(0, min(100, float(score) + forest_dist_score))
                if env.get("forest_dist_m") is not None:
                    score_result.setdefault("details", []).append(
                        f"distanza dal bosco più vicino: {round(float(env.get('forest_dist_m')))} m ({round(forest_dist_score,1)})"
                    )
            except Exception:
                pass

            try:
                aspect_bonus = float(env.get("aspect_bonus") or 0.0)
                score = max(0, min(100, float(score) + aspect_bonus))
                if aspect_bonus:
                    score_result.setdefault("details", []).append(
                        f"esposizione versante: {env.get('aspect_reason') or ''}"
                    )
            except Exception:
                pass
            # GeoLichen 1.8: l'accessibilità è già integrata nel motore ecologico
            # come accessibility_score separato. Qui manteniamo trail_bonus e
            # trail_penalty solo come attributi diagnostici, evitando doppio conteggio.
            try:
                if env.get("trail_dist_m") is not None:
                    score_result.setdefault("details", []).append(
                        f"accessibilità {env.get('trail_source') or 'layer'}: distanza {round(float(env.get('trail_dist_m')))} m; classe={env.get('trail_class') or '-'}; nome={env.get('trail_name') or '-'}; tipo={env.get('trail_type') or '-'}; contesto {env.get('context_type')} dist={round(float(env.get('context_dist_m') or 0))} m"
                    )
            except Exception:
                pass
            # GeoLichen 4.5a: un solo score ufficiale per ranking, output e GSS.
            # Il valore precedente viene conservato esclusivamente come raw_score diagnostico.
            legacy_raw_score = self._to_float(score)
            try:
                env = self.scoring_model.apply_to_env(env)
                official_score = self._to_float(env.get("final_score"))
                if official_score is None:
                    official_score = legacy_raw_score if legacy_raw_score is not None else 0.0
                official_score = max(0.0, min(100.0, float(official_score)))

                score = official_score
                env["score"] = official_score
                env["final_score"] = official_score
                env["norm_score"] = official_score
                env["heat_w"] = official_score

                score_result["score"] = int(round(official_score))
                score_result["raw_score"] = legacy_raw_score
                score_result["final_score"] = official_score

                diag = self.scoring_model.diagnostic_text(env)
                if diag:
                    score_result.setdefault("details", []).append(diag)
            except Exception:
                official_score = legacy_raw_score if legacy_raw_score is not None else 0.0
                score = official_score
                env["score"] = official_score
                env["final_score"] = official_score
                env["norm_score"] = official_score
                env["heat_w"] = official_score

            constraints = score_result.get("constraints") or self.ecology_engine.compute_constraints(profile)

            row = {
                "id": idx,
                "rank": None,
                "is_top10": False,
                "point": pt,
                "score": official_score,
                "raw_score": legacy_raw_score,
                "env": env,
                "constraints": constraints,
                "details": score_result.get("details", []),
                "distance_to_center_m": env.get("distance_to_center_m"),
                "alt_delta_m": env.get("alt_delta_m") if env.get("alt_delta_m") is not None else self._altitude_delta(env.get("altitude"), env.get("record_altitude")),
            }
            features_data.append(row)

        if not features_data:
            raise ValueError(
                "Nessun punto candidato compatibile dopo i pre-filtri. "
                f"Punti esclusi per quota: {excluded_by_altitude}; "
                f"punti esclusi per fascia vegetazionale: {excluded_by_vegetation_belt}. "
                "Verificare quota/DEM o layer fasce vegetazionali."
            )

        # Ordinamento: score desc; poi, se presente quota record, preferisce il punto
        # con delta altitudinale minore. Questo evita che un punto ecologicamente
        # simile ma molto più alto/basso prevalga solo per altri tie-break.
        # Ranking: a pari score, se è presente quota del cartellino,
        # privilegia il delta altitudinale minore prima dei tie-break secondari.
        def _rank_key(r):
            env = r.get("env") or {}
            score = self._to_float((r.get("env") or {}).get("final_score"))
            if score is None:
                score = self._to_float(r.get("score")) or 0
            raw = self._to_float(r.get("raw_score")) or score
            alt_delta = self._to_float(r.get("alt_delta_m"))
            has_record_altitude = self._to_float(env.get("record_altitude")) is not None
            raw_capped = min(100.0, float(raw))

            altitude_priority = 0
            if has_record_altitude:
                altitude_priority = -1 * (alt_delta if alt_delta is not None else 999999)

            return (
                score,
                self._to_float(env.get("accessibility_score")) or 0,
                self._to_float(env.get("context_score")) or 0,
                -1 * (self._to_float(env.get("context_dist_m")) or 999999),
                -1 * (self._to_float(env.get("trail_dist_m")) or 999999),
                altitude_priority,
                self._to_float(env.get("ecological_score")) or 0,
                raw_capped,
                self._to_float(env.get("litho_soil_ph_score")) or 0,
                self._to_float(env.get("aspect_bonus")) or 0,
                self._to_float(env.get("slope")) or 0,
                -1 * (self._to_float(r.get("distance_to_center_m")) or 999999),
            )

        features_data.sort(key=_rank_key, reverse=True)

        # GeoLichen 14.0.3: assegna subito il ranking alla griglia globale.
        # In precedenza i rank venivano assegnati solo dopo l'eventuale
        # raffinamento; di conseguenza i punti globali finivano nel layer con
        # rank NULL/0. Tutti i candidati della griglia iniziale devono invece
        # conservare un ranking diagnostico completo.
        audit_constraints = list(constraint_metadata or profile.get("constraint_metadata") or [])
        for rank, row in enumerate(features_data, start=1):
            row["rank"] = rank
            row["is_top10"] = rank <= top_n
            row["constraint_metadata"] = audit_constraints
            row["selected"] = False

        # Conserva sempre la griglia globale: alimenta la GSS/heatmap e rimane
        # visibile come contesto, mentre il raffinamento serve solo al Rank 1 finale.
        coarse_features = list(features_data)
        for row in coarse_features:
            row["grid_level"] = "global"

        refinement_info = {
            "enabled": bool(_adaptive_refinement),
            "applied": False,
            "initial_step_m": float(grid_step_m),
            "intermediate_step_m": None,
            "final_step_m": float(grid_step_m),
            "levels": 0,
            "coarse_points_count": len(features_data),
        }

        # GeoLichen 20 luglio: ricerca adattiva coarse-to-fine.
        # La griglia scelta dall'utente localizza le zone promettenti; solo quelle
        # vengono ricampionate a risoluzione maggiore. Ogni punto raffinato viene
        # rivalutato integralmente dal motore ecologico, evitando centroidi non valutati.
        if _adaptive_refinement and features_data:
            try:
                dem_res = self._best_dem_resolution_m(dem_layer, dem_layers)
                min_meaningful_step = max(5.0, (float(dem_res) / 2.0) if dem_res else 5.0)
                intermediate_step = max(min_meaningful_step, float(grid_step_m) / 5.0)
                final_step = min_meaningful_step

                # Il raffinamento è realmente adattivo: viene attivato soltanto
                # quando la griglia iniziale non separa chiaramente il migliore
                # dagli altri candidati. Un massimo netto non viene ricampionato.
                score_values = []
                for row in features_data:
                    score = self._to_float((row.get("env") or {}).get("final_score"))
                    if score is None:
                        score = self._to_float(row.get("score"))
                    if score is not None:
                        score_values.append(float(score))
                score_values.sort(reverse=True)
                maximum_score = score_values[0] if score_values else 0.0
                second_score = score_values[1] if len(score_values) > 1 else None
                score_gap = (maximum_score - second_score) if second_score is not None else None
                near_max_count = sum(1 for value in score_values if value >= maximum_score - 1.0 - 1e-9)
                relative_gap_pct = (100.0 * score_gap / maximum_score) if score_gap is not None and maximum_score > 0 else None

                ambiguous_maximum = bool(
                    second_score is not None
                    and (score_gap <= 1.0 + 1e-9 or near_max_count >= 3)
                )
                resolution_gain = intermediate_step < float(grid_step_m) - 0.5
                should_refine = bool(resolution_gain and ambiguous_maximum)

                refinement_info.update({
                    "decision": "refine" if should_refine else "skip",
                    "decision_reason": (
                        "ambiguous_or_flat_gss_maximum" if should_refine
                        else ("no_meaningful_resolution_gain" if not resolution_gain else "clear_gss_maximum")
                    ),
                    "initial_max_score": round(maximum_score, 6),
                    "initial_second_score": round(second_score, 6) if second_score is not None else None,
                    "initial_score_gap": round(score_gap, 6) if score_gap is not None else None,
                    "initial_relative_gap_pct": round(relative_gap_pct, 4) if relative_gap_pct is not None else None,
                    "initial_near_max_count_delta1": int(near_max_count),
                    "trigger_gap_threshold": 1.0,
                    "trigger_near_max_count": 3,
                })

                if should_refine:
                    refinement_info["applied"] = True
                    refinement_info["intermediate_step_m"] = round(intermediate_step, 3)
                    refinement_info["final_step_m"] = round(final_step, 3)

                    refined_points_1 = self._generate_refinement_points(
                        buffer_geom, features_data, float(grid_step_m), intermediate_step
                    )
                    if refined_points_1:
                        r1 = self.find_best_point(
                            buffer_geom=buffer_geom, profile=profile,
                            original_locality_extent=original_locality_extent, search_extent=search_extent,
                            constraint_metadata=constraint_metadata, geology_layer=geology_layer, geology_field=geology_field,
                            soil_layer=soil_layer, soil_field=soil_field, trees_layer=trees_layer, trees_field=trees_field,
                            trail_layer=trail_layer, trail_layers=trail_layers, vegetation_belt_layer=vegetation_belt_layer,
                            vegetation_belt_field=vegetation_belt_field, dem_layer=dem_layer, dem_layers=dem_layers,
                            dem_band=dem_band, grid_step_m=intermediate_step, top_n=top_n, create_layer=False,
                            visualization_mode="points", context=context, context_point=context_point,
                            locality_context=locality_context, _candidate_points=refined_points_1,
                            _ranking_center=center, _adaptive_refinement=False,
                        )
                        refinement_info["levels"] = 1
                        refinement_info["intermediate_points_count"] = len(r1.get("features") or [])
                        for row in (r1.get("features") or []):
                            row["grid_level"] = "refinement_1"
                        final_result = r1

                        if final_step < intermediate_step - 0.5:
                            refined_points_2 = self._generate_refinement_points(
                                buffer_geom, r1.get("features") or [], intermediate_step, final_step
                            )
                            if refined_points_2:
                                r2 = self.find_best_point(
                                    buffer_geom=buffer_geom, profile=profile,
                                    original_locality_extent=original_locality_extent, search_extent=search_extent,
                                    constraint_metadata=constraint_metadata, geology_layer=geology_layer, geology_field=geology_field,
                                    soil_layer=soil_layer, soil_field=soil_field, trees_layer=trees_layer, trees_field=trees_field,
                                    trail_layer=trail_layer, trail_layers=trail_layers, vegetation_belt_layer=vegetation_belt_layer,
                                    vegetation_belt_field=vegetation_belt_field, dem_layer=dem_layer, dem_layers=dem_layers,
                                    dem_band=dem_band, grid_step_m=final_step, top_n=top_n, create_layer=False,
                                    visualization_mode="points", context=context, context_point=context_point,
                                    locality_context=locality_context, _candidate_points=refined_points_2,
                                    _ranking_center=center, _adaptive_refinement=False,
                                )
                                for row in (r2.get("features") or []):
                                    row["grid_level"] = "refinement_2"
                                final_result = r2
                                refinement_info["levels"] = 2
                                refinement_info["final_points_count"] = len(r2.get("features") or [])

                        features_data = list(final_result.get("features") or features_data)
                        grid_step_m = float(final_result.get("grid_step_m") or final_step)
            except Exception as exc:
                refinement_info["error"] = str(exc)

        # Ranking finale della soluzione usata da SSI, top10 e selezione.
        # Se non è stato applicato il raffinamento, questi sono gli stessi
        # record della griglia globale già classificati sopra.
        for rank, row in enumerate(features_data, start=1):
            row["rank"] = rank
            row["is_top10"] = rank <= top_n
            row["constraint_metadata"] = audit_constraints
            row["selected"] = rank == 1

        # Layer cartografico composito: griglia globale + punti locali raffinati.
        # GeoLichen 14.0.6: il rank deve essere univoco anche quando coesistono
        # griglia globale e raffinamento. In precedenza entrambe le popolazioni
        # conservavano un proprio Rank 1; QGIS poteva quindi evidenziare un punto
        # globale diverso dal vero candidato finale. Il raffinamento mantiene i
        # rank 1..N, mentre la griglia globale viene accodata da N+1 in poi.
        if refinement_info.get("applied"):
            final_count = len(features_data)
            for offset, row in enumerate(coarse_features, start=final_count + 1):
                row["rank"] = offset
                row["is_top10"] = False
                row["selected"] = False
            # GeoLichen 14.5.2.3: inserisce prima i punti raffinati (Rank 1..N)
            # e successivamente la griglia globale (Rank N+1..). In precedenza
            # il layer conteneva tutti i punti, ma l'ordine interno iniziava dai
            # rank globali (es. 12, 13, ...), facendo apparire la tabella attributi
            # come se mancassero i primi candidati raffinati.
            display_features = list(features_data) + list(coarse_features)
        else:
            display_features = list(features_data)

        # Mantiene sempre l'ordine fisico delle feature coerente con il rank,
        # indipendentemente dall'ordine con cui le diverse griglie sono prodotte.
        display_features.sort(
            key=lambda row: int(row.get("rank"))
            if row.get("rank") not in (None, "")
            else 999999999
        )

        features_data = self._mark_plausible_alternatives_v295(features_data, score_window=5.0)
        ambiguity_info = self._ambiguity_index_v295(features_data)

        best = features_data[0] if features_data else None

        # GeoLichen 14.0.5: sincronizzazione definitiva del candidato selezionato.
        # Il verde deve identificare esclusivamente il vero Rank 1 finale.
        # In precedenza un flag ``selected`` obsoleto poteva restare associato
        # a una feature molto più in basso nella classifica (es. posizione 1791).
        # Azzera quindi ogni stato precedente e marca soltanto l'oggetto ``best``.
        for row in display_features:
            row["selected"] = False
        if best is not None:
            best["selected"] = True
        top_points = features_data[:top_n]
        selection = {
            "selection_method": "adaptive_multiresolution_rank_1" if refinement_info.get("applied") else "automatic_rank_1",
            "selected_rank": best.get("rank") if best else None,
            "selected_score": best.get("score") if best else None,
            "selected_raw_score": best.get("raw_score") if best else None,
            "selected_reason": "highest_geolichen_rank_after_gss_and_tie_breaks",
            "manual_snap_distance_m": None,
            "point_changed_by_gbif": False,
            "adaptive_refinement": refinement_info,
        }
        uncertainty = self.uncertainty_service.estimate(
            buffer_geom,
            features_data,
            gbif_extent_geom=original_locality_extent,
            best_point=best.get("point") if best else None,
            grid_step_m=grid_step_m,
            locality_context=locality_context,
        )
        # FASE 7.5: rende visibili nel layer di output i metadati della
        # classificazione e del corrected center, senza influenzare il ranking.
        if locality_context is not None:
            uncertainty.update({
                "locality_type": getattr(locality_context, "locality_type", "unknown") or "unknown",
                "geometry_type": getattr(locality_context, "geometry_type", "unknown") or "unknown",
                "classification_reason": getattr(locality_context, "classification_reason", "") or "",
                "classification_confidence": getattr(locality_context, "classification_confidence", 0.0) or 0.0,
                "primary_reference_type": getattr(locality_context, "primary_reference_type", "") or "",
                "primary_reference_name": getattr(locality_context, "primary_reference_name", "") or "",
            })

        result_layer = None
        heatmap_layer = None
        if create_layer:
            mode = str(visualization_mode or "points").lower()

            # La GSS globale deve restare quella della griglia iniziale, non una
            # somma di piccole heatmap locali prodotte dal raffinamento.
            if mode in ["heatmap", "both"]:
                heatmap_layer = self._create_heatmap_layer(
                    coarse_features,
                    layer_name="GeoLichen Suitability Surface - globale",
                    uncertainty=uncertainty,
                    radius_mm=heatmap_radius_mm,
                    opacity=heatmap_opacity,
                )

            # I punti restano sempre visibili anche in modalità heatmap. Vengono
            # creati dopo il raster, così QGIS li colloca sopra la superficie GSS.
            if mode in ["points", "heatmap", "both"]:
                result_layer = self._create_points_layer(
                    display_features, layer_name=layer_name, uncertainty=uncertainty
                )
            elif heatmap_layer is not None:
                result_layer = heatmap_layer

        return {
            "original_locality_extent": QgsGeometry(original_locality_extent) if original_locality_extent is not None else None,
            "gbif_corrected_center": uncertainty.get("corrected_center"),
            "gbif_corrected_center_lon": uncertainty.get("corrected_center_lon"),
            "gbif_corrected_center_lat": uncertainty.get("corrected_center_lat"),
            "gbif_corrected_center_method": uncertainty.get("corrected_center_method"),
            "gbif_corrected_center_source": uncertainty.get("corrected_center_source"),
            "search_extent": QgsGeometry(search_extent) if search_extent is not None else QgsGeometry(buffer_geom),
            "ecological_candidate_extent": QgsGeometry(buffer_geom),
            "constraint_metadata": list(constraint_metadata or profile.get("constraint_metadata") or []),
            "selection": selection,
            "selected_point": best.get("point") if best else None,
            "selected_candidate": best,
            "best_point": best.get("point") if best else None,
            "best_score": best.get("score") if best else None,
            "best_env": best.get("env") if best else {},
            "best_details": best.get("details") if best else [],
            "best_rank": best.get("rank") if best else None,
            "top_points": top_points,
            "points_count": len(features_data),
            "grid_step_m": grid_step_m,
            "initial_grid_step_m": refinement_info.get("initial_step_m"),
            "adaptive_refinement": refinement_info,
            "layer": result_layer,
            "heatmap_layer": heatmap_layer,
            "suitability_surface_layer": heatmap_layer,
            "features": features_data,
            "display_features": display_features,
            "global_features": coarse_features,
            "uncertainty": uncertainty,
            "ambiguity": ambiguity_info,
            "excluded_by_altitude": excluded_by_altitude,
            "excluded_by_vegetation_belt": excluded_by_vegetation_belt,
            "dem_min_tolerance_m": self.dem_min_tolerance_m,
            "heatmap_radius_mm": heatmap_radius_mm,
            "heatmap_opacity": heatmap_opacity,
            "context": context,
        }


    def _record_score_from_env_v282(self, env, profile):
        """Score del cartellino senza alterare la pipeline altitudinale 2.6."""
        env = env or {}
        profile = profile or {}
        score = 50.0

        # Quota: usa i campi già calcolati dalla pipeline 2.6
        try:
            alt_delta = self._to_float(env.get("alt_delta_m"))
            has_rec = env.get("record_altitude") not in [None, ""]
            if has_rec:
                tol = self._to_float(env.get("altitude_tolerance_m")) or self.dem_min_tolerance_m or 10.0
                if alt_delta is not None:
                    if alt_delta <= tol:
                        score += 25.0
                    elif alt_delta <= tol * 2:
                        score += 12.0
                    else:
                        score += 3.0
                else:
                    score += 8.0
        except Exception:
            pass

        # Substrato/roccia/forofita espliciti dal record resolver
        try:
            locks = profile.get("record_locks") or {}
            if locks.get("substrate") and profile.get("substrate"):
                wanted = str(profile.get("substrate") or "").lower()
                observed = str(env.get("substrate") or "").lower()
                score += 20.0 if (wanted == observed or wanted in observed or observed in wanted) else 5.0
            if locks.get("rock_type") and profile.get("rock_type"):
                wanted = str(profile.get("rock_type") or "").lower()
                observed = str(env.get("rock_type") or "").lower()
                score += 15.0 if (wanted == observed or observed == "misto") else 3.0
            if locks.get("tree_type") or locks.get("tree_group"):
                score += min(15.0, max(0.0, float(env.get("tree_match_score") or 0.0)) + max(0.0, float(env.get("forest_dist_score") or 0.0)))
            if profile.get("record_aspect") or env.get("record_aspect"):
                score += max(0.0, min(5.0, float(env.get("aspect_bonus") or 0.0)))
        except Exception:
            pass

        try:
            terrain = env.get("terrain_score")
            if terrain is not None:
                score += max(-5.0, min(5.0, (float(terrain) - 50.0) / 10.0))
        except Exception:
            pass

        return max(0.0, min(100.0, score))

    def _geography_score_from_env_v282(self, env):
        env = env or {}
        try:
            if env.get("context_score") is not None:
                return max(0.0, min(100.0, float(env.get("context_score"))))
        except Exception:
            pass
        return 50.0

    def _final_score_v282(self, ecological_score, record_score, accessibility_confidence, geography_score):
        try:
            eco = max(0.0, min(100.0, float(ecological_score if ecological_score is not None else 0.0)))
            rec = max(0.0, min(100.0, float(record_score if record_score is not None else 50.0)))
            acc = max(0.0, min(100.0, float(accessibility_confidence if accessibility_confidence is not None else 50.0)))
            geo = max(0.0, min(100.0, float(geography_score if geography_score is not None else 50.0)))
            return (0.50 * eco) + (0.35 * rec) + (0.10 * acc) + (0.05 * geo)
        except Exception:
            return 0.0



    def _strict_record_altitude_decision_v283(self, env):
        """Filtro HARD per quota esplicita del cartellino."""
        env = env or {}
        alt = self._parse_altitude_value(env.get("altitude"))
        if alt is None:
            return {"exclude": False, "reason": "DEM assente o quota punto non disponibile", "type": "record_altitude_no_dem"}

        rec_min = self._parse_altitude_value(env.get("record_altitude_min"))
        rec_max = self._parse_altitude_value(env.get("record_altitude_max"))
        if rec_min is not None and rec_max is not None:
            lo, hi = sorted([float(rec_min), float(rec_max)])
            tol = float(env.get("altitude_tolerance_m") or self.dem_min_tolerance_m or 10.0)
            exclude = not ((lo - tol) <= float(alt) <= (hi + tol))
            return {
                "exclude": exclude,
                "reason": f"quota record range {lo:g}-{hi:g} m; punto {float(alt):.1f} m; tolleranza ±{tol:g} m",
                "type": "record_altitude_range",
                "min_altitude": lo,
                "max_altitude": hi,
                "tolerance_m": tol,
            }

        rec_alt = self._parse_altitude_value(env.get("record_altitude"))
        if rec_alt is not None:
            tol = float(env.get("altitude_tolerance_m") or self._record_altitude_uncertainty(rec_alt))
            delta = abs(float(alt) - float(rec_alt))
            exclude = delta > tol
            return {
                "exclude": exclude,
                "reason": f"quota record {float(rec_alt):g} m; punto {float(alt):.1f} m; delta {delta:.1f} m; tolleranza ±{tol:g} m",
                "type": "record_altitude_single",
                "record_altitude": float(rec_alt),
                "delta_m": delta,
                "tolerance_m": tol,
                "min_altitude": float(rec_alt) - tol,
                "max_altitude": float(rec_alt) + tol,
            }

        return {"exclude": False, "reason": "quota cartellino assente", "type": "no_record_altitude"}



    def _substrate_context_for_terrain_v284(self, env, profile):
        resolved = str((profile or {}).get("substrate_group") or (env or {}).get("substrate_group") or "").strip().lower()
        if resolved in ("soil", "rock", "epiphyte", "lignicolous", "moss"):
            return resolved
        env = env or {}
        profile = profile or {}
        txt = " ".join([
            str(env.get("substrate") or ""),
            str(profile.get("substrate") or ""),
            str(profile.get("substrate_raw") or ""),
            str(profile.get("record_substrate") or ""),
        ]).lower()

        if any(t in txt for t in ["roccia", "rock", "sasso", "rup", "sax", "parete", "falesia", "rupe"]):
            return "rock"
        if any(t in txt for t in ["suolo", "soil", "terra", "terric", "humus", "torba"]):
            return "soil"
        if any(t in txt for t in ["scorza", "corteccia", "bark", "epif", "forofita", "tronco", "ramo"]):
            return "epiphyte"
        return "unknown"

    def _terrain_prefilter_v284(self, env, profile):
        env = env or {}
        try:
            slope = float(env.get("slope"))
        except Exception:
            return {"exclude": False, "score": 50.0, "reason": "pendenza non disponibile"}

        substrate_context = self._substrate_context_for_terrain_v284(env, profile)

        if substrate_context == "soil":
            if slope >= 45:
                return {"exclude": True, "score": 0.0, "reason": f"substrato suolo/terricolo ma pendenza {slope:.1f}° troppo elevata"}
            if slope >= 35:
                return {"exclude": False, "score": 20.0, "reason": f"substrato suolo/terricolo su pendenza alta {slope:.1f}°"}
            if slope >= 25:
                return {"exclude": False, "score": 55.0, "reason": f"substrato suolo/terricolo su pendenza media {slope:.1f}°"}
            return {"exclude": False, "score": 90.0, "reason": f"substrato suolo/terricolo su pendenza compatibile {slope:.1f}°"}

        if substrate_context == "rock":
            if slope >= 55:
                return {"exclude": False, "score": 80.0, "reason": f"sassicolo su parete/pendenza {slope:.1f}°"}
            if slope >= 35:
                return {"exclude": False, "score": 90.0, "reason": f"sassicolo su pendenza alta {slope:.1f}°"}
            return {"exclude": False, "score": 70.0, "reason": f"sassicolo su pendenza {slope:.1f}°"}

        if substrate_context == "epiphyte":
            if slope >= 55:
                return {"exclude": False, "score": 35.0, "reason": f"epifita in area molto ripida {slope:.1f}°"}
            return {"exclude": False, "score": 70.0, "reason": f"epifita: pendenza non determinante {slope:.1f}°"}

        if slope >= 55:
            return {"exclude": False, "score": 25.0, "reason": f"pendenza molto elevata {slope:.1f}°"}
        if slope >= 40:
            return {"exclude": False, "score": 45.0, "reason": f"pendenza elevata {slope:.1f}°"}
        return {"exclude": False, "score": 70.0, "reason": f"pendenza {slope:.1f}°"}



    def _substrate_context_for_slope_penalty_v291(self, env, profile):
        """Determina il contesto del substrato per la penalità di pendenza.

        Priorità corretta:
        1. substrato/forofita espliciti = epiphyte/soil/rock;
        2. solo se il substrato è assente, usa rock_type come fallback.
        """
        resolved = str((profile or {}).get("substrate_group") or (env or {}).get("substrate_group") or "").strip().lower()
        if resolved in ("soil", "rock", "epiphyte", "lignicolous", "moss"):
            return resolved

        env = env or {}
        profile = profile or {}

        substrate_txt = " ".join([
            str(env.get("substrate") or ""),
            str(profile.get("substrate") or ""),
            str(profile.get("substrate_raw") or ""),
            str(profile.get("record_substrate") or ""),
        ]).lower()

        tree_txt = " ".join([
            str(env.get("tree_type") or ""),
            str(env.get("tree_raw") or ""),
            str(profile.get("tree_type") or ""),
            str(profile.get("tree_raw") or ""),
            str(profile.get("tree_group") or ""),
        ]).lower()

        rock_txt = " ".join([
            str(env.get("rock_type") or ""),
            str(env.get("rock_raw") or ""),
            str(profile.get("rock_type") or ""),
            str(profile.get("rock_raw") or ""),
        ]).lower()

        ep_terms = ["epif", "scorza", "corteccia", "bark", "forofita", "phorophyte", "tronco", "ramo", "legno", "wood"]
        soil_terms = ["suolo", "soil", "terra", "terric", "humus", "torba"]
        rock_terms = ["roccia", "rock", "sasso", "masso", "rup", "sax", "silice", "calcare", "parete", "falesia", "rupe"]

        # PRIORITÀ ASSOLUTA: epifita/forofita batte qualsiasi informazione litologica.
        if any(t in substrate_txt for t in ep_terms) or any(t in tree_txt for t in ep_terms):
            return "epiphyte"

        # Se c'è un albero/forofita esplicito, è epifita anche se la litologia dice siliceo/calcareo.
        if tree_txt.strip():
            return "epiphyte"

        if any(t in substrate_txt for t in soil_terms):
            return "soil"

        if any(t in substrate_txt for t in rock_terms):
            return "rock"

        # Fallback litologico solo quando il substrato non fornisce indicazioni.
        if any(t in rock_txt for t in rock_terms):
            return "rock"

        return "unknown"


    def _slope_penalty_v291(self, env, profile):
        """Penalità morbida per pendenze troppo elevate.

        Non aggiunge mai punti e non elimina candidati.
        Serve solo a far scendere in ranking punti morfologicamente meno plausibili.
        """
        env = env or {}
        try:
            slope = float(env.get("slope"))
        except Exception:
            return {
                "penalty": 0.0,
                "reason": "pendenza non disponibile",
                "context": "unknown",
            }

        context = self._substrate_context_for_slope_penalty_v291(env, profile)
        penalty = 0.0

        if context == "soil":
            if slope > 45:
                penalty = -10.0
            elif slope > 35:
                penalty = -5.0
            elif slope > 25:
                penalty = -2.0
        elif context == "rock":
            if slope > 85:
                penalty = -6.0
            elif slope > 70:
                penalty = -4.0
            elif slope > 50:
                penalty = -2.0
        elif context == "epiphyte":
            if slope > 65:
                penalty = -4.0
            elif slope > 45:
                penalty = -2.0
        else:
            # Se il substrato è ignoto, penalità molto prudente.
            if slope > 70:
                penalty = -4.0
            elif slope > 55:
                penalty = -2.0

        # Se il punto è molto vicino a un sentiero/strada, riduci la penalità.
        # Un raccoglitore può campionare su pendii ripidi se sono accessibili.
        try:
            trail_d = env.get("trail_dist_m")
            if trail_d is not None and float(trail_d) <= 30 and penalty < 0:
                penalty = penalty / 2.0
        except Exception:
            pass

        if penalty == 0:
            reason = f"pendenza {slope:.1f}°: nessuna penalità ({context})"
        else:
            reason = f"pendenza {slope:.1f}°: penalità {penalty:g} ({context})"

        return {
            "penalty": penalty,
            "reason": reason,
            "context": context,
        }



    def _append_ranking_diagnostics_v292(self, score_result, env):
        try:
            details = score_result.setdefault("details", [])
            if env.get("vector_tile_access_layers"):
                details.append(
                    "accessibilità vector tile selezionata: {}; nota={}".format(
                        env.get("vector_tile_access_layers"),
                        env.get("vector_tile_access_note") or ""
                    )
                )
            if env.get("slope_penalty_reason"):
                details.append(
                    "pendenza: contesto={}; penalità={}; {}".format(
                        env.get("slope_context") or "-",
                        round(float(env.get("slope_penalty") or 0.0), 1),
                        env.get("slope_penalty_reason") or ""
                    )
                )
        except Exception:
            pass
        return score_result


    def _best_dem_resolution_m(self, dem_layer=None, dem_layers=None):
        """Restituisce la migliore (più piccola) risoluzione metrica dei DEM validi."""
        values = []
        layers = []
        try:
            layers.extend(list(dem_layers or []))
        except Exception:
            pass
        if dem_layer is not None and dem_layer not in layers:
            layers.insert(0, dem_layer)
        for layer in layers:
            try:
                value = self._dem_pixel_size_m(layer)
                if value is not None and float(value) > 0:
                    values.append(float(value))
            except Exception:
                pass
        return min(values) if values else None

    def _generate_refinement_points(self, buffer_geom, ranked_rows, source_step_m, target_step_m):
        """Genera una griglia fine compatta attorno al Rank 1.

        Il raffinamento è volutamente locale: usa un raggio pari al passo della
        griglia sorgente e limita il campionamento a circa 64 punti. Se il passo
        fine richiesto produrrebbe troppi nodi, viene aumentato soltanto per
        questa griglia locale, mantenendo invariati griglia globale e scoring.
        """
        if not ranked_rows:
            return []

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        try:
            center_wgs84 = buffer_geom.centroid().asPoint()
            metric = _shared_local_metric_crs(center_wgs84)
        except Exception:
            return []
        original_m = self._transform_geometry(buffer_geom, wgs84, metric)
        if original_m is None or original_m.isEmpty():
            return []

        # Raffina esclusivamente il massimo del livello precedente.
        best_point = None
        for row in ranked_rows:
            try:
                point = row.get("point")
                if point is None:
                    continue
                gm = self._transform_geometry(QgsGeometry.fromPointXY(point), wgs84, metric)
                if gm is not None and not gm.isEmpty():
                    best_point = gm.asPoint()
                    break
            except Exception:
                continue
        if best_point is None:
            return []

        source_step = max(1.0, float(source_step_m))
        requested_step = max(1.0, float(target_step_m))
        radius = max(source_step, requested_step * 2.0)
        local_m = QgsGeometry.fromPointXY(best_point).buffer(radius, 16)
        try:
            local_m = local_m.intersection(original_m)
        except Exception:
            pass
        local_wgs = self._transform_geometry(local_m, metric, wgs84)
        if local_wgs is None or local_wgs.isEmpty():
            return []

        max_points = 64
        points = self._generate_grid_points(local_wgs, requested_step)
        # Adatta il solo passo locale finché il numero di nodi resta controllato.
        # La correzione radice-quadrata preserva approssimativamente la copertura.
        effective_step = requested_step
        attempts = 0
        while len(points) > max_points and attempts < 4:
            effective_step *= (len(points) / float(max_points)) ** 0.5 * 1.02
            points = self._generate_grid_points(local_wgs, effective_step)
            attempts += 1
        return points

    def _generate_grid_points(self, geom_wgs84, step_m):
        """Genera una griglia con passo reale in metri in un CRS UTM locale.

        EPSG:3857 non viene usato perché le sue unità cartografiche non
        corrispondono alle distanze al suolo fuori dall'equatore.
        """
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        try:
            center_wgs84 = geom_wgs84.centroid().asPoint()
            metric = _shared_local_metric_crs(center_wgs84)
        except Exception:
            return []

        geom_m = self._transform_geometry(geom_wgs84, wgs84, metric)
        if geom_m is None or geom_m.isEmpty():
            return []

        bbox = geom_m.boundingBox()
        points = []

        x = bbox.xMinimum()
        while x <= bbox.xMaximum():
            y = bbox.yMinimum()
            while y <= bbox.yMaximum():
                p_m = QgsPointXY(x, y)
                g_m = QgsGeometry.fromPointXY(p_m)
                if geom_m.contains(g_m):
                    g_wgs = self._transform_geometry(g_m, metric, wgs84)
                    if g_wgs and not g_wgs.isEmpty():
                        points.append(g_wgs.asPoint())
                y += step_m
            x += step_m

        return points

    def _build_env_for_point(
        self,
        pt_wgs84,
        geology_layer=None,
        geology_field=None,
        soil_layer=None,
        soil_field=None,
        trees_layer=None,
        trees_field=None,
        trail_layer=None,
        trail_context=None,
        access_contexts=None,
        vegetation_belt_layer=None,
        vegetation_belt_field=None,
        dem_layer=None,
        dem_layers=None,
        dem_band=1,
    ):
        env = {
            "altitude": None,
            "dem_source": "",
            "dem_priority": None,
            "dem_valid_count": 0,
            "dem_fallback_used": False,
            "dem_spread_m": None,
            "rock_type": None,
            "substrate": None,
            "soil_ph": None,
            "soil_ph_raw": "",
            "soil_ph_num": None,
            "soil_ph_field": "",
            "soil_ph_class": "",
            "ph_score": 0.0,
            "ph_reason": "",
            "slope": None,
            "aspect": None,
            "aspect_class": None,
            "record_aspect": None,
            "aspect_difference_deg": None,
            "aspect_bonus": 0.0,
            "aspect_match": "",
            "exposure": None,
            "humidity": None,
            "tree_type": None,
            "tree_traits": {},
            "tree_match_score": 0.0,
            "tree_match_reason": "",
            "expected_tree": "",
            "observed_tree": "",
            "forest_category": "",
            "forest_lithology": "",
            "forest_dist_m": None,
            "forest_dist_score": 0.0,
            "vegetation_belt": None,
            "vegetation_belt_raw": "",
            "vegetation_belt_match": None,
            "trail_dist_m": None,
            "trail_bonus": 0.0,
            "trail_penalty": 0.0,
            "context_type": "",
            "context_dist_m": None,
            "context_score": None,
            "context_weight": None,
            "trail_accessibility_score": None,
            "litho_soil_ph": None,
            "litho_soil_ph_score": 0.0,
            "litho_soil_ph_match": "",
            "soil_confidence": "",
            "soil_confidence_score": 0.0,
            "soil_confidence_reason": "",
        }

        if geology_layer and geology_field:
            val = self._value_at_point(geology_layer, geology_field, pt_wgs84)
            env["rock_type"] = self._normalize_rock_type(val)
            env["rock_raw"] = str(val) if val not in [None, ""] else ""

        if soil_layer and soil_field:
            soil_feat = self._feature_at_point(soil_layer, pt_wgs84)
            val = self._value_at_point(soil_layer, soil_field, pt_wgs84)
            env["soil_raw"] = str(val) if val not in [None, ""] else ""

            # GeoLichen 3.1: pH numerico generico da qualunque campo del layer suolo.
            try:
                ph_num, ph_field, ph_raw = self.soil_service.extract_numeric_ph_from_feature(soil_feat)
            except Exception:
                ph_num, ph_field, ph_raw = None, "", ""

            if ph_num is not None:
                env["soil_ph_num"] = ph_num
                env["soil_ph_field"] = ph_field
                env["soil_ph_raw"] = ph_raw
                env["soil_ph"] = self.soil_service.ph_class_from_numeric(ph_num)
                env["soil_ph_class"] = env.get("soil_ph")
                env["substrate"] = "suolo"
            else:
                # Se il campo suolo contiene valori come "acida", "basica", "neutra",
                # questi sono pH/proprietà chimiche, non substrati.
                soil_ph = self.soil_service.normalize_soil_ph(val)
                if soil_ph:
                    env["soil_ph"] = soil_ph
                    env["soil_ph_class"] = soil_ph
                    env["soil_ph_raw"] = str(val)
                    env["substrate"] = "suolo"
                else:
                    env["substrate"] = self._normalize_substrate(val)

        if trees_layer and trees_field:
            val = self._value_at_point(trees_layer, trees_field, pt_wgs84)
            if val:
                env["tree_type"] = str(val)
                env["tree_raw"] = str(val)
                try:
                    env["tree_traits"] = self.tree_service.traits_from_layer_value(val)
                    env["observed_tree"] = str((env.get("tree_traits") or {}).get("tree_type") or "")
                    env["forest_category"] = str((env.get("tree_traits") or {}).get("forest_category") or "")
                    env["forest_lithology"] = str((env.get("tree_traits") or {}).get("soil_lithology") or "")
                except Exception:
                    env["tree_traits"] = {}
                    env["observed_tree"] = ""
                if env.get("substrate") is None:
                    env["substrate"] = "bosco"
            else:
                env["tree_raw"] = ""
                env["tree_traits"] = {}
                env["observed_tree"] = ""
                env["tree_match_reason"] = "tipo forestale assente nel punto; valutata la distanza dal bosco più vicino"

        try:
            if trees_layer:
                env["forest_dist_m"] = self._distance_to_nearest_feature_m(trees_layer, pt_wgs84)
                env["forest_dist_score"] = 0.0  # calcolato dopo, quando il profilo è disponibile
        except Exception:
            pass

        if vegetation_belt_layer and vegetation_belt_field:
            val = self._value_at_point(vegetation_belt_layer, vegetation_belt_field, pt_wgs84)
            if val not in [None, ""]:
                env["vegetation_belt_raw"] = str(val)
                env["vegetation_belt"] = self._normalize_vegetation_belt(val)
            else:
                env["vegetation_belt_raw"] = ""

        nearest_access = self._nearest_accessibility_v293(pt_wgs84, access_contexts=access_contexts)
        try:
            vt_names = [c.get("layer_name") for c in (access_contexts or []) if c.get("vector_tile")]
            if vt_names:
                env["vector_tile_access_layers"] = ",".join([str(v) for v in vt_names if v])
                env["vector_tile_access_note"] = "VectorTile selezionato ma non usato per distanza in modalità sicura"
        except Exception:
            pass
        if nearest_access:
            env["trail_dist_m"] = nearest_access.get("distance_m")
            env["trail_source"] = nearest_access.get("source")
            env["trail_name"] = nearest_access.get("name")
            env["trail_type"] = nearest_access.get("type")
            env["trail_priority"] = nearest_access.get("priority")
            env["trail_osm_id"] = nearest_access.get("osm_id")
            env["trail_class_osm"] = nearest_access.get("trail_class_osm")
            env["trail_surface"] = nearest_access.get("surface")
            env["trail_sac_scale"] = nearest_access.get("sac_scale")
            env["trail_bonus"] = self._trail_bonus(env.get("trail_dist_m"))
            env["trail_penalty"] = self._trail_penalty(env.get("trail_dist_m"))
        elif trail_layer:
            env["trail_dist_m"] = self._distance_to_nearest_feature(
                trail_layer,
                pt_wgs84,
                trail_context=trail_context
            )
            env["trail_source"] = trail_layer.name() if hasattr(trail_layer, "name") else ""
            env["trail_bonus"] = self._trail_bonus(env.get("trail_dist_m"))
            env["trail_penalty"] = self._trail_penalty(env.get("trail_dist_m"))

        # Context-aware accessibility: distanza dal riferimento principale
        # del cartellino (passo, cima, lago, rifugio...), non solo dal sentiero.
        try:
            env["context_type"] = str((getattr(self, "_current_context", {}) or {}).get("type") or "")
            if getattr(self, "_current_context_point", None) is not None:
                env["context_dist_m"] = self._distance_m(getattr(self, "_current_context_point", None), pt_wgs84)
            acc = self.accessibility_engine.final_accessibility_score(
                trail_dist_m=env.get("trail_dist_m"),
                context_dist_m=env.get("context_dist_m"),
                context=getattr(self, "_current_context", {}) or {},
            )
            env["accessibility_score"] = acc.get("accessibility_score")
            env["trail_accessibility_score"] = acc.get("trail_accessibility_score")
            env["trail_class"] = acc.get("trail_class")
            env["context_score"] = acc.get("context_score")
            env["context_weight"] = acc.get("context_weight")
            env["accessibility_rule"] = acc.get("rule")
        except Exception:
            pass

        candidate_dems = []
        for layer in (dem_layers or []):
            if self._is_raster_layer(layer) and layer not in candidate_dems:
                candidate_dems.append(layer)
        if self._is_raster_layer(dem_layer) and dem_layer not in candidate_dems:
            candidate_dems.insert(0, dem_layer)

        valid_samples = []
        selected_dem = None
        selected_altitude = None
        selected_priority = None
        for index, layer in enumerate(candidate_dems):
            try:
                value = float(self._sample_raster_value(layer, pt_wgs84, band=dem_band))
                if math.isfinite(value):
                    valid_samples.append((layer, value, index + 1))
                    if selected_dem is None:
                        selected_dem = layer
                        selected_altitude = value
                        selected_priority = index + 1
            except Exception:
                continue

        env["dem_valid_count"] = len(valid_samples)
        if selected_dem is not None:
            env["altitude"] = selected_altitude
            env["dem_source"] = selected_dem.name()
            env["dem_priority"] = selected_priority
            env["dem_selection_rule"] = "spatial_extent"
            env["dem_fallback_used"] = bool(selected_priority and selected_priority > 1)
            env["slope"] = self._estimate_slope_from_dem(selected_dem, pt_wgs84, band=dem_band)
            env["aspect"] = self._estimate_aspect_from_dem(selected_dem, pt_wgs84, band=dem_band)
            env["aspect_class"] = self._aspect_to_class(env.get("aspect"))
            env["exposure"] = self._aspect_to_exposure(env.get("aspect"))
            values = [v for _, v, _ in valid_samples]
            env["dem_spread_m"] = (max(values) - min(values)) if len(values) > 1 else 0.0

        return env



    def _is_vector_tile_layer_v294(self, layer):
        try:
            return layer is not None and layer.__class__.__name__ == "QgsVectorTileLayer"
        except Exception:
            return False


    def _mark_plausible_alternatives_v295(self, features_data, score_window=5.0):
        """Marca alternative plausibili tra candidati con score simile.

        Non cambia il vincitore. Serve a supportare la decisione esperta.
        """
        features_data = features_data or []
        if not features_data:
            return features_data

        best = features_data[0]
        try:
            best_score = float(best.get("score") or 0.0)
        except Exception:
            best_score = 0.0
        best_env = best.get("env") or {}
        best_trail = self._to_float(best_env.get("trail_dist_m"))
        best_dist = self._to_float(best.get("distance_to_center_m"))

        for row in features_data:
            env = row.get("env") or {}
            row["plausible_alt"] = "no"
            row["alt_reason"] = ""
            row["score_delta"] = None

            try:
                delta = best_score - float(row.get("score") or 0.0)
                row["score_delta"] = round(delta, 2)
            except Exception:
                delta = 999.0

            if row is best:
                continue
            if delta < 0 or delta > float(score_window):
                continue

            reasons = []
            trail = self._to_float(env.get("trail_dist_m"))
            dist = self._to_float(row.get("distance_to_center_m"))

            if trail is not None and best_trail is not None:
                if trail <= 10 and best_trail > 30:
                    reasons.append(f"sentiero molto più vicino ({round(trail,1)} m vs {round(best_trail,1)} m)")
                elif trail + 50 < best_trail:
                    reasons.append(f"accessibilità migliore ({round(trail,1)} m vs {round(best_trail,1)} m)")

            try:
                alt_delta = abs(float(env.get("alt_delta_m"))) if env.get("alt_delta_m") is not None else None
                best_alt_delta = abs(float(best_env.get("alt_delta_m"))) if best_env.get("alt_delta_m") is not None else None
                if alt_delta is not None and best_alt_delta is not None and alt_delta + 5 < best_alt_delta:
                    reasons.append(f"quota più vicina al cartellino (Δ {round(alt_delta,1)} m vs {round(best_alt_delta,1)} m)")
            except Exception:
                pass

            if dist is not None and best_dist is not None and dist + 25 < best_dist:
                reasons.append(f"più vicino al riferimento ({round(dist,1)} m vs {round(best_dist,1)} m)")

            try:
                if float(env.get("aspect_bonus") or 0.0) > float(best_env.get("aspect_bonus") or 0.0):
                    reasons.append("esposizione più coerente")
            except Exception:
                pass

            if reasons:
                row["plausible_alt"] = "yes"
                row["alt_reason"] = "; ".join(reasons)[:250]
                try:
                    env["plausible_alt"] = "yes"
                    env["alt_reason"] = row["alt_reason"]
                    env["score_delta"] = row["score_delta"]
                except Exception:
                    pass

        return features_data

    def _ambiguity_index_v295(self, features_data):
        features_data = features_data or []
        if len(features_data) < 2:
            return {"ambiguity": "low", "near_candidates": 0}
        try:
            best = float(features_data[0].get("score") or 0.0)
            near = [r for r in features_data[1:] if best - float(r.get("score") or 0.0) <= 5.0]
            if len(near) >= 10:
                label = "high"
            elif len(near) >= 3:
                label = "medium"
            else:
                label = "low"
            return {"ambiguity": label, "near_candidates": len(near)}
        except Exception:
            return {"ambiguity": "unknown", "near_candidates": 0}


    def _prepare_maptile_accessibility_context_v294(self, layer, buffer_geom_wgs84):
        """Adattatore sperimentale per Vector Tile/MapTiler.

        QGIS non espone getFeatures() sui QgsVectorTileLayer come sui layer vettoriali.
        Per non compromettere il plugin, il layer viene riconosciuto e tracciato
        diagnostically, ma se l'estrazione non è disponibile il motore continua
        con i layer vettoriali classici.
        """
        try:
            return {
                "vector_tile": True,
                "layer_name": layer.name() if hasattr(layer, "name") else "VectorTile",
                "count": 0,
                "index": None,
                "geoms_m": {},
                "attrs": {},
                "warning": "VectorTile riconosciuto; estrazione geometrie non disponibile in modalità sicura",
            }
        except Exception:
            return None


    def _prepare_accessibility_contexts_v293(self, layers, buffer_geom_wgs84, margin_m=1200):
        """Prepara indici spaziali per più layer di accessibilità.

        GeoLichen 2.9.4:
        - supporta layer vettoriali classici;
        - riconosce VectorTile/MapTiler senza bloccare il plugin.
        """
        contexts = []
        if not layers:
            return contexts
        for priority, layer in enumerate(layers, start=1):
            try:
                if self._is_vector_tile_layer_v294(layer):
                    ctx = self._prepare_maptile_accessibility_context_v294(layer, buffer_geom_wgs84)
                    if ctx:
                        ctx["priority"] = priority
                        contexts.append(ctx)
                    continue
            except Exception:
                pass

            ctx = self._prepare_trail_context(layer, buffer_geom_wgs84, margin_m=margin_m)
            if ctx:
                try:
                    ctx["layer_name"] = layer.name()
                except Exception:
                    ctx["layer_name"] = f"access_layer_{priority}"
                ctx["priority"] = priority
                contexts.append(ctx)
        return contexts


    def _nearest_accessibility_v293(self, pt_wgs84, access_contexts=None):
        """Distanza minima su più layer di accessibilità, con sorgente diagnostica."""
        access_contexts = access_contexts or []
        if not access_contexts:
            return None

        best = None
        try:
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            metric = _shared_local_metric_crs(pt_wgs84)
            pt_geom_wgs = QgsGeometry.fromPointXY(pt_wgs84)
            pt_geom_m = self._transform_geometry(pt_geom_wgs, wgs84, metric)
            if pt_geom_m is None or pt_geom_m.isEmpty():
                return None

            for ctx in access_contexts:
                index = ctx.get("index")
                geoms_m = ctx.get("geoms_m") or {}
                attrs = ctx.get("attrs") or {}
                if index is None or not geoms_m:
                    continue
                try:
                    candidate_ids = index.nearestNeighbor(pt_geom_m.asPoint(), 12)
                except Exception:
                    candidate_ids = []

                for fid in candidate_ids:
                    geom_m = geoms_m.get(fid)
                    if geom_m is None or geom_m.isEmpty():
                        continue
                    d = float(pt_geom_m.distance(geom_m))
                    rec = attrs.get(fid) or {}
                    item = {
                        "distance_m": d,
                        "source": ctx.get("layer_name") or "",
                        "priority": int(ctx.get("priority") or 999),
                        "name": rec.get("name") or rec.get("ref") or rec.get("codice") or "",
                        "type": rec.get("highway") or rec.get("tipo") or rec.get("class") or "",
                        "osm_id": rec.get("osm_id"),
                        "trail_class_osm": rec.get("trail_class") or "",
                        "surface": rec.get("surface") or "",
                        "sac_scale": rec.get("sac_scale") or "",
                    }
                    if best is None:
                        best = item
                    else:
                        # distanza minima; se quasi uguale, priorità più alta
                        if d < (best["distance_m"] - 5.0):
                            best = item
                        elif abs(d - best["distance_m"]) <= 5.0 and item["priority"] < best.get("priority", 999):
                            best = item
            return best
        except Exception:
            return None


    def _prepare_trail_context(self, trail_layer, buffer_geom_wgs84, margin_m=1000):
        """Prepara indice spaziale dei sentieri una sola volta."""
        if trail_layer is None or buffer_geom_wgs84 is None or buffer_geom_wgs84.isEmpty():
            return None

        try:
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            metric = _shared_local_metric_crs(buffer_geom_wgs84.centroid().asPoint())

            buffer_m = self._transform_geometry(buffer_geom_wgs84, wgs84, metric)
            if buffer_m is None or buffer_m.isEmpty():
                return None

            search_m = buffer_m.buffer(float(margin_m), 16)
            search_layer = self._transform_geometry(search_m, metric, trail_layer.crs())
            if search_layer is None or search_layer.isEmpty():
                return None

            request = QgsFeatureRequest().setFilterRect(search_layer.boundingBox())

            index = QgsSpatialIndex()
            geoms_m = {}
            attrs = {}
            count = 0

            for feat in trail_layer.getFeatures(request):
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue

                try:
                    if not geom.intersects(search_layer):
                        continue
                except Exception:
                    pass

                geom_m = self._transform_geometry(geom, trail_layer.crs(), metric)
                if geom_m is None or geom_m.isEmpty():
                    continue

                temp_feat = QgsFeature()
                temp_feat.setId(feat.id())
                temp_feat.setGeometry(geom_m)
                index.addFeature(temp_feat)

                geoms_m[feat.id()] = geom_m
                try:
                    attrs[feat.id()] = {name: feat[name] for name in feat.fields().names() if name in ["name", "ref", "codice", "highway", "tipo", "class", "osm_id", "trail_class", "surface", "sac_scale"]}
                except Exception:
                    attrs[feat.id()] = {}
                count += 1

            if count == 0:
                return None

            return {
                "index": index,
                "geoms_m": geoms_m,
                "attrs": attrs,
                "count": count,
            }
        except Exception:
            return None

    def _distance_to_nearest_feature(self, layer, pt_wgs84, search_radius_m=1200, trail_context=None):
        """Distanza minima in metri dal sentiero più vicino."""
        if layer is None:
            return None

        try:
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            metric = _shared_local_metric_crs(pt_wgs84)

            pt_geom_wgs = QgsGeometry.fromPointXY(pt_wgs84)
            pt_geom_m = self._transform_geometry(pt_geom_wgs, wgs84, metric)
            if pt_geom_m is None or pt_geom_m.isEmpty():
                return None

            if trail_context and trail_context.get("index") is not None and trail_context.get("geoms_m"):
                try:
                    candidate_ids = trail_context["index"].nearestNeighbor(pt_geom_m.asPoint(), 12)
                except Exception:
                    candidate_ids = []

                min_dist = None
                for fid in candidate_ids:
                    geom_m = trail_context["geoms_m"].get(fid)
                    if geom_m is None or geom_m.isEmpty():
                        continue
                    d = pt_geom_m.distance(geom_m)
                    if min_dist is None or d < min_dist:
                        min_dist = d

                return float(min_dist) if min_dist is not None else None

            search_geom_m = pt_geom_m.buffer(float(search_radius_m), 12)
            search_geom_layer = self._transform_geometry(search_geom_m, metric, layer.crs())
            if search_geom_layer is None or search_geom_layer.isEmpty():
                return None

            request = QgsFeatureRequest().setFilterRect(search_geom_layer.boundingBox())

            min_dist = None
            for feat in layer.getFeatures(request):
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue

                geom_m = self._transform_geometry(geom, layer.crs(), metric)
                if geom_m is None or geom_m.isEmpty():
                    continue

                d = pt_geom_m.distance(geom_m)
                if min_dist is None or d < min_dist:
                    min_dist = d

            return float(min_dist) if min_dist is not None else None
        except Exception:
            return None

    def _trail_bonus(self, distance_m):
        """Bonus forte per accessibilità: preferisce punti vicini ai sentieri."""
        try:
            if distance_m is None:
                return 0.0
            d = float(distance_m)
            if d <= 25:
                return 20.0
            if d <= 75:
                return 16.0
            if d <= 150:
                return 12.0
            if d <= 300:
                return 8.0
            if d <= 600:
                return 3.0
            if d <= 1000:
                return 1.0
            return 0.0
        except Exception:
            return 0.0

    def _trail_penalty(self, distance_m):
        """Penalità per punti molto lontani dai sentieri.

        Serve perché, se molti punti arrivano già a score=100, il solo bonus non
        basta a far emergere i punti accessibili.
        """
        try:
            if distance_m is None:
                return 0.0
            d = float(distance_m)
            if d <= 300:
                return 0.0
            if d <= 600:
                return 4.0
            if d <= 1000:
                return 10.0
            if d <= 1500:
                return 16.0
            return 22.0
        except Exception:
            return 0.0


    def _build_ecological_context(self, profile):
        """Costruisce un contesto read-only dalla decisione ecologica persistita.

        Nessun campo GIS, nota libera o tratto ITALIC può sovrascrivere un
        ``substrate_group`` risolto. ITALIC rimane disponibile come supporto o
        fallback soltanto quando il resolver centrale restituisce ``unknown``.
        """
        profile = profile or {}
        locks = profile.get("record_locks") or {}
        layer_decision = profile.get("layer_decision") or {}
        if not isinstance(layer_decision, dict):
            layer_decision = {}

        group = str(
            profile.get("substrate_group")
            or layer_decision.get("substrate_group")
            or "unknown"
        ).strip().lower()
        aliases = {
            "suolo": "soil", "terricolo": "soil", "terricolous": "soil",
            "roccia": "rock", "saxicolo": "rock", "saxicolous": "rock",
            "epifita": "epiphyte", "epiphytic": "epiphyte",
            "lignicolo": "lignicolous", "lignicolous": "lignicolous",
            "muschio": "moss", "muscicolo": "moss",
        }
        group = aliases.get(group, group)
        if group not in {"soil", "rock", "epiphyte", "lignicolous", "moss", "unknown"}:
            group = "unknown"

        pipeline_map = {
            "soil": "soil", "moss": "soil", "rock": "geology",
            "epiphyte": "trees", "lignicolous": "trees", "unknown": "generic",
        }
        primary = (
            layer_decision.get("primary_pipeline")
            or layer_decision.get("primary_layer")
            or profile.get("primary_pipeline")
            or profile.get("environmental_pipeline")
            or pipeline_map[group]
        )

        record_substrate = (
            profile.get("record_substrate")
            or profile.get("substrate_raw")
            or locks.get("substrate_raw")
            or locks.get("substrate")
        )
        habitat_evidence = {
            "observed": profile.get("record_habitat_raw") or profile.get("habitat_raw"),
            "interpreted": profile.get("interpreted_habitat") or profile.get("habitat_interpreted"),
            "notes": profile.get("record_notes") or profile.get("notes"),
        }

        return EcologicalContext(
            substrate_group=group,
            substrate_source=str(profile.get("substrate_source") or "unknown"),
            substrate_locked=bool(profile.get("substrate_locked") or locks.get("substrate")),
            substrate_confidence=profile.get("substrate_confidence"),
            substrate_resolution_reason=profile.get("substrate_resolution_reason"),
            rock_type=profile.get("rock_type"),
            tree_type=profile.get("tree_type") or profile.get("tree_group"),
            soil_traits=profile.get("soil_traits") or {
                "soil_ph_preference": layer_decision.get("soil_ph_preference")
                    or profile.get("soil_ph_preference")
            },
            habitat_evidence=habitat_evidence,
            italic_profile={
                "substrata": profile.get("substrata"),
                "habitat": profile.get("habitat"),
                "ecology_raw": profile.get("ecology_raw"),
            },
            layer_decision=layer_decision,
            primary_pipeline=str(primary),
            record_substrate=record_substrate,
            record_habitat=habitat_evidence.get("observed"),
            record_notes=habitat_evidence.get("notes"),
        )

    def _refine_env_with_profile(self, env, profile):
        """Propaga il contesto risolto senza riclassificare il reperto.

        Le osservazioni GIS del punto restano nei campi ``substrate``,
        ``rock_type`` e ``tree_type``. La classe ecologica autorevole resta in
        ``substrate_group`` e non viene dedotta da tali osservazioni.
        """
        env = env or {}
        profile = profile or {}
        context = self._build_ecological_context(profile)
        context_dict = context.to_dict()

        env["ecological_context"] = context_dict
        env["substrate_group"] = context.substrate_group
        env["resolved_substrate_group"] = context.substrate_group
        env["substrate_source"] = context.substrate_source
        env["substrate_locked"] = context.substrate_locked
        env["substrate_confidence"] = context.substrate_confidence
        env["substrate_resolution_reason"] = context.substrate_resolution_reason
        env["layer_decision"] = context.layer_decision or {}
        env["primary_pipeline"] = context.primary_pipeline
        env["environmental_pipeline"] = context.primary_pipeline
        env["record_substrate"] = context.record_substrate
        env["record_substrate_raw"] = context.record_substrate
        env["record_habitat_raw"] = context.record_habitat
        env["record_notes"] = context.record_notes
        env["habitat_evidence"] = context.habitat_evidence
        env["italic_profile_used"] = bool(context.italic_profile)
        env["italic_role"] = (
            "fallback" if context.substrate_source == "italic_profile"
            else "ecological_support"
        )

        # Normalizzazione esclusivamente descrittiva dei valori GIS. Non modifica
        # mai il gruppo risolto e non trasforma presenza di bosco in substrato.
        if env.get("rock_type") and env.get("rock_type") not in ["siliceo", "calcareo", "misto"]:
            env["rock_type"] = self._normalize_rock_type(env.get("rock_type"))
        if not env.get("rock_type") and env.get("rock_raw"):
            env["rock_type"] = self._normalize_rock_type(env.get("rock_raw"))

        try:
            env["substrate_context"] = self._substrate_context_for_slope_penalty_v291(env, profile)
        except Exception:
            env["substrate_context"] = context.substrate_group

        return env



    def _distance_to_nearest_feature_m(self, layer, pt_wgs84, max_distance_m=1500.0):
        """Distanza in metri dal punto alla feature più vicina del layer."""
        if layer is None or pt_wgs84 is None:
            return None
        try:
            from qgis.core import (
                QgsCoordinateReferenceSystem,
                QgsCoordinateTransform,
                QgsProject,
                QgsGeometry,
                QgsPointXY,
                QgsFeatureRequest,
            )
            src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            metric_crs = _shared_local_metric_crs(pt_wgs84)

            point_geom = QgsGeometry.fromPointXY(QgsPointXY(pt_wgs84))
            point_metric = QgsGeometry(point_geom)
            point_metric.transform(QgsCoordinateTransform(src_crs, metric_crs, QgsProject.instance()))

            search_geom_metric = point_metric.buffer(float(max_distance_m), 16)
            search_geom_layer = QgsGeometry(search_geom_metric)
            search_geom_layer.transform(QgsCoordinateTransform(metric_crs, layer.crs(), QgsProject.instance()))
            req = QgsFeatureRequest().setFilterRect(search_geom_layer.boundingBox())

            to_metric = QgsCoordinateTransform(layer.crs(), metric_crs, QgsProject.instance())

            best = None
            for feat in layer.getFeatures(req):
                try:
                    geom = feat.geometry()
                    if geom is None or geom.isEmpty():
                        continue
                    g = QgsGeometry(geom)
                    g.transform(to_metric)
                    d = float(g.distance(point_metric))
                    if best is None or d < best:
                        best = d
                        if best <= 0.01:
                            return 0.0
                except Exception:
                    continue
            return best
        except Exception:
            return None

    def _record_allows_substrate_buffer_reduction(self, profile):
        """Il buffer può essere sgrossato per substrato solo nei sassicoli.

        Ritorna True esclusivamente quando il record/profilo indica in modo
        esplicito roccia, sassicolo, saxicolo o rupicolo.
        Epifiti, terricoli, muscicoli e casi incerti non devono subire
        riduzioni del buffer iniziale basate sul substrato.
        """
        profile = profile or {}
        values = [
            profile.get("substrate"),
            profile.get("rock_type"),
            profile.get("substrata"),
            (profile.get("record_locks") or {}).get("substrate"),
        ]
        text = " ".join(str(v or "").lower() for v in values)
        rock_terms = (
            "roccia",
            "rock",
            "sassicol",
            "saxicol",
            "rupicol",
            "rupestre",
        )
        return any(term in text for term in rock_terms)

    def _forest_distance_score(self, profile, forest_dist_m):
        """Score continuo 0–100 della prossimità forestale per epifiti.

        Il valore è diagnostico e viene anche letto dal nuovo modello GSS. Per
        taxa non epifiti/lignicoli resta 0 e non modifica il ranking.
        """
        try:
            if not self.tree_service.is_epiphytic_or_lignicolous(profile):
                return 0.0
        except Exception:
            return 0.0
        try:
            if forest_dist_m is None:
                return 0.0
            d = max(0.0, float(forest_dist_m))
            if d <= 25.0:
                return 100.0
            if d <= 100.0:
                return 100.0 - ((d - 25.0) / 75.0) * 15.0
            if d <= 250.0:
                return 85.0 - ((d - 100.0) / 150.0) * 35.0
            if d <= 500.0:
                return 50.0 - ((d - 250.0) / 250.0) * 30.0
            if d <= 1000.0:
                return 20.0 - ((d - 500.0) / 500.0) * 15.0
            return 5.0
        except Exception:
            return 0.0


    def _apply_tree_match_proxy(self, env, profile):
        """Compila sempre diagnostica forestale/forofita."""
        env = env or {}
        profile = profile or {}

        layer_value = env.get("tree_raw") or env.get("tree_type")
        try:
            result = self.tree_service.tree_match_score(profile, layer_value)
        except Exception as e:
            result = {
                "score": 0.0,
                "reason": f"errore valutazione forestale/cartellino: {e}",
                "expected_traits": {},
                "observed_traits": {},
                "used": False,
            }

        expected = result.get("expected_traits") or {}
        observed = result.get("observed_traits") or {}

        if not observed and layer_value not in [None, "", [], {}]:
            try:
                observed = self.tree_service.traits_from_layer_value(layer_value) or {}
            except Exception:
                observed = {}

        env["tree_match_score"] = result.get("score", 0.0) if result.get("score") is not None else 0.0
        env["tree_match_reason"] = result.get("reason") or "non valutato"
        env["expected_tree"] = str(expected.get("tree_type") or "")
        env["observed_tree"] = str(observed.get("tree_type") or env.get("observed_tree") or "")
        env["forest_category"] = str(observed.get("forest_category") or env.get("forest_category") or "")
        env["forest_lithology"] = str(observed.get("soil_lithology") or env.get("forest_lithology") or "")
        env["tree_traits"] = observed or env.get("tree_traits") or {}

        return env



    def _apply_lithology_soil_ph_proxy(self, env, profile):
        """Valuta coerenza pH suolo/litologia solo per terricoli-muscicoli.

        Non viene applicata ai saxicoli e non cambia il substrato.
        """
        env = env or {}
        profile = profile or {}

        try:
            constraints = self.ecology_engine.compute_constraints(profile)
        except Exception:
            constraints = {}

        wanted = str(constraints.get("substrate") or "").lower()
        if wanted not in ["suolo", "muschio"]:
            env["soil_confidence"] = "not_used"
            env["soil_confidence_score"] = 0.0
            env["soil_confidence_reason"] = "non applicato: substrato non terricolo/muscicolo"
            return env

        soil_ph = env.get("soil_ph")
        if not soil_ph and env.get("soil_raw"):
            try:
                soil_ph = self.soil_service.normalize_soil_ph(env.get("soil_raw"))
                env["soil_ph"] = soil_ph
                if soil_ph:
                    env["soil_ph_raw"] = env.get("soil_raw")
                    env["substrate"] = "suolo"
            except Exception:
                soil_ph = None

        try:
            confidence, score, litho_ph, reason = self.soil_service.soil_confidence_from_ph_and_lithology(
                soil_ph,
                env.get("rock_type")
            )
        except Exception:
            confidence, score, litho_ph, reason = "unknown", 0.0, None, "errore nella valutazione pH/litologia"

        env["litho_soil_ph"] = litho_ph
        env["litho_soil_ph_score"] = score
        env["litho_soil_ph_match"] = confidence
        env["soil_confidence"] = confidence
        env["soil_confidence_score"] = score
        env["soil_confidence_reason"] = reason
        return env



    def _normalize_record_aspect(self, value):
        """Normalizza l'esposizione del versante dal cartellino.

        Supporta sia 8 direzioni principali sia combinazioni intermedie:
        N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW/SO, WSW/OSO,
        W/O, WNW/ONO, NW/NO, NNW/NNO.

        Supporta anche forme testuali:
        nord-est, est-nord-est, sud-sud-ovest, settentrionale,
        meridionale, orientale, occidentale, esposto a sud, ecc.
        """
        if value in [None, "", [], {}]:
            return None

        txt = str(value).strip().lower()
        txt = txt.replace("–", "-").replace("—", "-").replace("_", " ").replace("/", " ")
        txt = re.sub(r"\b(esposizione|versante|esposto|esposta|a|ad|verso|pendio|slope|aspect)\b", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()

        # Normalizza parole italiane in sigle, preservando le combinazioni.
        repl = {
            "settentrionale": "nord",
            "meridionale": "sud",
            "orientale": "est",
            "occidentale": "ovest",
            "northern": "north",
            "southern": "south",
            "eastern": "east",
            "western": "west",
            "north": "nord",
            "south": "sud",
            "east": "est",
            "west": "ovest",
        }
        for k, v in repl.items():
            txt = txt.replace(k, v)

        compact = txt.upper().replace(" ", "").replace("-", "")
        compact = compact.replace("OVEST", "O").replace("NORD", "N").replace("SUD", "S").replace("EST", "E")
        compact = compact.replace("O", "W")  # output internazionale: W

        aliases = {
            "N": "N", "NNE": "NNE", "NEN": "NNE",
            "NE": "NE", "ENE": "ENE", "EEN": "ENE",
            "E": "E", "ESE": "ESE", "EES": "ESE",
            "SE": "SE", "SSE": "SSE", "SES": "SSE",
            "S": "S", "SSW": "SSW", "SSO": "SSW", "SOS": "SSW",
            "SW": "SW", "SO": "SW", "WSW": "WSW", "OSO": "WSW", "WOW": "WSW",
            "W": "W", "O": "W", "WNW": "WNW", "ONO": "WNW", "WOW": "WNW",
            "NW": "NW", "NO": "NW", "NNW": "NNW", "NNO": "NNW", "NON": "NNW",
        }
        if compact in aliases:
            return aliases[compact]

        # Se sono citate due direzioni ma non in forma standard.
        has_n = "nord" in txt
        has_s = "sud" in txt
        has_e = "est" in txt
        has_w = "ovest" in txt or re.search(r"\bo\b", txt) is not None

        # Cerca combinazioni intermedie testuali tipo est-nord-est.
        if "est nord est" in txt or "est-nord-est" in txt:
            return "ENE"
        if "nord nord est" in txt or "nord-nord-est" in txt:
            return "NNE"
        if "est sud est" in txt or "est-sud-est" in txt:
            return "ESE"
        if "sud sud est" in txt or "sud-sud-est" in txt:
            return "SSE"
        if "sud sud ovest" in txt or "sud-sud-ovest" in txt:
            return "SSW"
        if "ovest sud ovest" in txt or "ovest-sud-ovest" in txt:
            return "WSW"
        if "ovest nord ovest" in txt or "ovest-nord-ovest" in txt:
            return "WNW"
        if "nord nord ovest" in txt or "nord-nord-ovest" in txt:
            return "NNW"

        if has_n and has_e:
            return "NE"
        if has_s and has_e:
            return "SE"
        if has_s and has_w:
            return "SW"
        if has_n and has_w:
            return "NW"
        if has_n:
            return "N"
        if has_e:
            return "E"
        if has_s:
            return "S"
        if has_w:
            return "W"

        return None

    def _aspect_class_to_degrees(self, aspect_cls):
        aspect_cls = self._normalize_record_aspect(aspect_cls)
        mapping = {
            "N": 0.0,
            "NNE": 22.5,
            "NE": 45.0,
            "ENE": 67.5,
            "E": 90.0,
            "ESE": 112.5,
            "SE": 135.0,
            "SSE": 157.5,
            "S": 180.0,
            "SSW": 202.5,
            "SW": 225.0,
            "WSW": 247.5,
            "W": 270.0,
            "WNW": 292.5,
            "NW": 315.0,
            "NNW": 337.5,
        }
        return mapping.get(aspect_cls)

    def _aspect_circular_diff(self, a, b):
        try:
            diff = abs(float(a) - float(b)) % 360.0
            return min(diff, 360.0 - diff)
        except Exception:
            return None


    def _apply_record_aspect_preference(self, env, profile):
        """Peso controllato dell'esposizione del versante.

        Regole:
        - se il cartellino indica esposizione: peso forte ma limitato (+4 / -4);
        - se manca il cartellino, usa ecologia/ITALIC come preferenza media (+2 / -2);
        - non filtra mai candidati.
        """
        env = env or {}
        profile = profile or {}

        record_aspect = (
            env.get("record_aspect")
            or profile.get("record_aspect")
            or profile.get("aspect")
            or profile.get("esposizione")
            or profile.get("esposizione_versante")
        )

        if not record_aspect:
            for ck in ["record", "raw_record", "record_constraints", "fields", "row"]:
                container = profile.get(ck)
                if isinstance(container, dict):
                    for k, v in container.items():
                        kk = str(k).lower()
                        if any(term in kk for term in ["espos", "versante", "aspect"]):
                            record_aspect = v
                            break
                if record_aspect:
                    break

        rec_cls = self._normalize_record_aspect(record_aspect)
        env["record_aspect"] = rec_cls or ""
        env["record_aspect_raw"] = str(record_aspect or "")
        env["aspect_score"] = 0.0
        env["aspect_bonus"] = 0.0
        env["aspect_match"] = ""
        env["aspect_reason"] = ""

        dem_aspect = env.get("aspect")
        dem_cls = env.get("aspect_class")
        diff = None

        # 1) Esposizione esplicita del cartellino: criterio forte.
        if rec_cls:
            env["aspect_match"] = "unknown"
            rec_deg = self._aspect_class_to_degrees(rec_cls)
            if dem_aspect not in [None, ""]:
                diff = self._aspect_circular_diff(rec_deg, dem_aspect)

            if diff is not None:
                env["aspect_difference_deg"] = diff
                if diff <= 22.5:
                    score = 4.0
                    match = "exact"
                elif diff <= 45:
                    score = 2.5
                    match = "near"
                elif diff <= 90:
                    score = 0.5
                    match = "broad"
                elif diff <= 135:
                    score = -2.0
                    match = "mismatch"
                else:
                    score = -4.0
                    match = "opposite"
            else:
                if dem_cls and self._normalize_record_aspect(dem_cls) == rec_cls:
                    score = 3.0
                    match = "class_match"
                else:
                    score = 0.0
                    match = "not_evaluated"

            env["aspect_score"] = score
            env["aspect_bonus"] = score
            env["aspect_match"] = match
            env["aspect_reason"] = f"esposizione cartellino {rec_cls}; DEM {dem_cls or dem_aspect}; match={match}; score={round(score,1)}"
            return env

        # 2) Preferenza ecologica/ITALIC: criterio medio.
        eco_pref = self._ecological_aspect_preference_v295(env, profile)
        if not eco_pref:
            return env

        preferred = eco_pref.get("classes") or []
        pref_label = eco_pref.get("label") or ""
        dem_norm = self._normalize_record_aspect(dem_cls)
        if not dem_norm and dem_aspect not in [None, ""]:
            dem_norm = self._aspect_degrees_to_class(float(dem_aspect))

        if not dem_norm:
            env["aspect_reason"] = f"preferenza ecologica {pref_label}; aspect DEM non disponibile"
            return env

        if dem_norm in preferred:
            score = 2.0
            match = "eco_preferred"
        elif self._aspect_is_adjacent_v295(dem_norm, preferred):
            score = 1.0
            match = "eco_near"
        elif self._aspect_is_opposite_v295(dem_norm, preferred):
            score = -2.0
            match = "eco_opposite"
        else:
            score = 0.0
            match = "eco_neutral"

        env["aspect_score"] = score
        env["aspect_bonus"] = score
        env["aspect_match"] = match
        env["aspect_reason"] = f"preferenza ecologica {pref_label}; DEM {dem_norm}; score={round(score,1)}"
        return env

    def _ecological_aspect_preference_v295(self, env, profile):
        """Deduce preferenza di esposizione da umidità/aridità/note ecologiche."""
        txt = " ".join([
            str(env.get("humidity") or ""),
            str(profile.get("humidity") or ""),
            str(profile.get("ecology_traits") or ""),
            str(profile.get("notes") or ""),
            str(profile.get("habitat") or ""),
        ]).lower()

        dry_terms = ["secco", "xeric", "xerof", "arid", "eliofil", "sun", "dry", "bassa"]
        humid_terms = ["umido", "fresco", "ombro", "shade", "shaded", "hygro", "igro", "mesic", "alta"]

        if any(t in txt for t in dry_terms):
            return {"label": "secco/xerico/eliofilo", "classes": ["S", "SW", "W"]}
        if any(t in txt for t in humid_terms):
            return {"label": "umido/fresco/ombrofilo", "classes": ["N", "NE", "NW"]}
        return None

    def _aspect_is_adjacent_v295(self, dem_cls, preferred):
        order = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        try:
            i = order.index(dem_cls)
            pref_idx = [order.index(p) for p in preferred if p in order]
            return any(min(abs(i-j), 8-abs(i-j)) == 1 for j in pref_idx)
        except Exception:
            return False

    def _aspect_is_opposite_v295(self, dem_cls, preferred):
        order = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        try:
            i = order.index(dem_cls)
            pref_idx = [order.index(p) for p in preferred if p in order]
            return any(min(abs(i-j), 8-abs(i-j)) >= 3 for j in pref_idx)
        except Exception:
            return False

    def _aspect_degrees_to_class(self, deg):
        try:
            d = float(deg) % 360.0
            dirs = [
                ("N", 337.5, 360.0), ("N", 0.0, 22.5),
                ("NE", 22.5, 67.5), ("E", 67.5, 112.5),
                ("SE", 112.5, 157.5), ("S", 157.5, 202.5),
                ("SW", 202.5, 247.5), ("W", 247.5, 292.5),
                ("NW", 292.5, 337.5),
            ]
            for label, lo, hi in dirs:
                if lo <= d < hi:
                    return label
        except Exception:
            pass
        return ""


    def _aspect_to_class(self, aspect):
        try:
            if aspect is None:
                return None
            a = float(aspect) % 360.0
        except Exception:
            return None

        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        idx = int(((a + 22.5) % 360) / 45.0)
        return dirs[idx]

    def _normalize_aspect_class(self, value):
        return self._normalize_record_aspect(value)

    def _aspect_class_difference_deg(self, a, b):
        da = self._aspect_class_to_degrees(a)
        db = self._aspect_class_to_degrees(b)
        if da is None or db is None:
            return None
        d = abs(da - db) % 360
        return float(min(d, 360 - d))



    def _altitude_prefilter_decision(self, env, profile):
        env = env or {}
        profile = profile or {}
        dem_altitude = self._parse_altitude_value(env.get("altitude"))

        rec_min = self._parse_altitude_value(env.get("record_altitude_min"))
        rec_max = self._parse_altitude_value(env.get("record_altitude_max"))
        if rec_min is not None and rec_max is not None:
            lo, hi = sorted([float(rec_min), float(rec_max)])
            tolerance = max(float(self.dem_min_tolerance_m), 10.0)
            min_ok = lo - tolerance
            max_ok = hi + tolerance
            exclude = False
            if dem_altitude is not None:
                exclude = not (min_ok <= float(dem_altitude) <= max_ok)
            return {
                "type": "record_altitude_range",
                "source": "record",
                "tolerance_m": tolerance,
                "min_altitude": min_ok,
                "max_altitude": max_ok,
                "exclude": exclude,
                "reason": f"quota record range {lo:g}-{hi:g} m ± {tolerance:g} m",
            }

        record_altitude = self._parse_altitude_value(env.get("record_altitude"))
        if record_altitude is not None:
            tolerance = self._record_altitude_uncertainty(record_altitude)
            min_alt = float(record_altitude) - float(tolerance)
            max_alt = float(record_altitude) + float(tolerance)
            exclude = False
            if dem_altitude is not None:
                exclude = not (min_alt <= float(dem_altitude) <= max_alt)
            return {
                "type": "record_altitude",
                "source": "record",
                "tolerance_m": tolerance,
                "min_altitude": min_alt,
                "max_altitude": max_alt,
                "exclude": exclude,
                "reason": f"quota record {record_altitude:g} ± {tolerance:g} m",
            }

        ad_min, ad_max = self._italic_altitudinal_distribution(profile)
        return {
            "type": "italic_altitudinal_distribution" if (ad_min is not None or ad_max is not None) else "none",
            "source": "ITALIC" if (ad_min is not None or ad_max is not None) else None,
            "tolerance_m": None,
            "min_altitude": ad_min,
            "max_altitude": ad_max,
            "exclude": False,
            "reason": "quota assente; uso distribuzione altitudinale ITALIC con layer fasce" if (ad_min is not None or ad_max is not None) else "nessun filtro quota",
        }



    def _exclude_by_record_altitude(self, env):
        return bool(self._altitude_prefilter_decision(env, {}).get("exclude"))

    def _record_altitude_uncertainty(self, altitude):
        try:
            a = abs(int(round(float(altitude))))
            if a % 100 == 0:
                return 100.0
            if a % 10 == 0:
                return 10.0
            return float(self.dem_min_tolerance_m)
        except Exception:
            return float(self.dem_min_tolerance_m)

    def _italic_altitudinal_distribution(self, profile):
        profile = profile or {}

        def parse(v):
            try:
                if v in [None, "", [], {}]:
                    return None
                x = float(str(v).replace(",", "."))
                if x <= 0 or x > 9000:
                    return None
                return x
            except Exception:
                return None

        amin = parse(profile.get("altitudinal_distribution_min"))
        amax = parse(profile.get("altitudinal_distribution_max"))
        raw = profile.get("ecology_raw") or {}
        if isinstance(raw, dict):
            if amin is None:
                amin = parse(raw.get("altitudinal_distribution_min"))
            if amax is None:
                amax = parse(raw.get("altitudinal_distribution_max"))
        if amin is not None and amax is not None and amin > amax:
            amin, amax = amax, amin
        return amin, amax

    def _exclude_by_vegetation_belt(self, env, profile):
        env = env or {}
        profile = profile or {}

        if self._parse_altitude_value(env.get("record_altitude")) is not None:
            env["vegetation_belt_match"] = "not_used_record_altitude_present"
            return False

        ad_min, ad_max = self._italic_altitudinal_distribution(profile)
        if ad_min is None and ad_max is None:
            env["vegetation_belt_match"] = "not_used_no_italic_range"
            return False

        belt_range = self._vegetation_belt_altitude_range(env.get("vegetation_belt") or env.get("vegetation_belt_raw"))
        if belt_range is None:
            env["vegetation_belt_match"] = "not_used_no_belt_layer_or_unmapped"
            return False

        bmin, bmax = belt_range
        compatible = self._ranges_overlap(ad_min, ad_max, bmin, bmax)
        env["vegetation_belt_match"] = "yes" if compatible else "no"
        env["vegetation_belt_min"] = bmin
        env["vegetation_belt_max"] = bmax
        env["italic_altitudinal_distribution_min"] = ad_min
        env["italic_altitudinal_distribution_max"] = ad_max
        return not compatible

    def _ranges_overlap(self, amin, amax, bmin, bmax):
        amin = float("-inf") if amin is None else float(amin)
        amax = float("inf") if amax is None else float(amax)
        bmin = float("-inf") if bmin is None else float(bmin)
        bmax = float("inf") if bmax is None else float(bmax)
        return max(amin, bmin) <= min(amax, bmax)

    def _normalize_vegetation_belt(self, value):
        txt = self._clean_text(value)
        if not txt:
            return None
        if any(k in txt for k in ["planiz", "basal", "collin", "collinare"]):
            return "collinare"
        if "montan" in txt:
            return "montana"
        if "subalpin" in txt:
            return "subalpina"
        if "alpin" in txt or "alpina" in txt:
            return "alpina"
        if "nival" in txt:
            return "nivale"
        return txt

    def _vegetation_belt_altitude_range(self, belt):
        belt = self._normalize_vegetation_belt(belt)
        if not belt:
            return None
        ranges = {
            "collinare": (0, 800),
            "montana": (800, 1600),
            "subalpina": (1600, 2200),
            "alpina": (2200, 3000),
            "nivale": (3000, 9000),
        }
        return ranges.get(belt)


    def _attach_record_altitude(self, env, profile):
        env = env or {}
        profile = profile or {}

        if env.get("record_altitude_min") not in [None, ""] and env.get("record_altitude_max") not in [None, ""]:
            return env

        # 1. Range già passato dal controller.
        try:
            mn = self._parse_altitude_value(profile.get("record_altitude_min"))
            mx = self._parse_altitude_value(profile.get("record_altitude_max"))
            if mn is not None and mx is not None:
                lo, hi = sorted([mn, mx])
                env["record_altitude_min"] = lo
                env["record_altitude_max"] = hi
                env["record_altitude"] = (lo + hi) / 2.0
                env["record_altitude_raw"] = str(profile.get("record_altitude_raw") or "")
                env["record_altitude_is_range"] = True
                return env
        except Exception:
            pass

        keys = [
            "record_altitude", "label_altitude", "altitude_record",
            "quota_record", "quota", "Quota", "altitudine", "Altitudine",
            "elevation_record", "record_elevation"
        ]

        # 2. Cerca range in profilo e record grezzo.
        containers = [profile]
        for ck in ["record", "raw_record", "record_constraints", "label_data", "fields", "row"]:
            if isinstance(profile.get(ck), dict):
                containers.append(profile.get(ck))

        for container in containers:
            for key, value in container.items():
                kk = str(key).lower()
                if key in keys or any(t in kk for t in ["quota", "alt", "elev"]):
                    mn, mx, mid = self._parse_altitude_range(value)
                    if mid is not None:
                        env["record_altitude_min"] = mn
                        env["record_altitude_max"] = mx
                        env["record_altitude"] = mid
                        env["record_altitude_raw"] = str(value)
                        env["record_altitude_is_range"] = True
                        return env

        # 3. Valore singolo.
        if env.get("record_altitude") not in [None, ""]:
            return env

        for key in keys:
            value = profile.get(key)
            parsed = self._parse_altitude_value(value)
            if parsed is not None:
                env["record_altitude"] = parsed
                env["record_altitude_raw"] = str(value)
                env["record_altitude_is_range"] = False
                return env

        return env



    def _parse_altitude_range(self, value):
        if value in [None, "", [], {}]:
            return None, None, None
        try:
            text = str(value).lower().replace(",", ".")
            text = text.replace("–", "-").replace("—", "-").replace("−", "-")
            text = text.replace("/", "-")
            patterns = [
                r"(?:tra|fra)\s+(\d{2,4}(?:\.\d+)?)\s*(?:e|-|a|to)\s*(\d{2,4}(?:\.\d+)?)",
                r"(?:da)\s+(\d{2,4}(?:\.\d+)?)\s*(?:a|-|to)\s*(\d{2,4}(?:\.\d+)?)",
                r"(\d{2,4}(?:\.\d+)?)\s*-\s*(\d{2,4}(?:\.\d+)?)",
            ]
            for pat in patterns:
                m = re.search(pat, text)
                if m:
                    a, b = float(m.group(1)), float(m.group(2))
                    if -500 <= a <= 9000 and -500 <= b <= 9000:
                        lo, hi = sorted([a, b])
                        if 0 < hi - lo <= 3000:
                            return lo, hi, (lo + hi) / 2.0
            return None, None, None
        except Exception:
            return None, None, None


    def _parse_altitude_value(self, value):
        if value in [None, "", [], {}]:
            return None
        try:
            if isinstance(value, (int, float)):
                if -500 <= float(value) <= 9000:
                    return float(value)
                return None
            import re
            text = str(value).lower().replace(",", ".")
            nums = re.findall(r"-?\d+(?:\.\d+)?", text)
            for n in nums:
                v = float(n)
                if -500 <= v <= 9000:
                    return v
        except Exception:
            return None
        return None


    def _feature_at_point(self, layer, pt_wgs84):
        """Ritorna la prima feature che contiene/interseca il punto."""
        if layer is None or pt_wgs84 is None:
            return None
        try:
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            pt_geom = QgsGeometry.fromPointXY(pt_wgs84)
            pt_layer = self._transform_geometry(pt_geom, wgs84, layer.crs())
            if pt_layer is None or pt_layer.isEmpty():
                return None
            req = QgsFeatureRequest().setFilterRect(pt_layer.boundingBox())
            for feat in layer.getFeatures(req):
                try:
                    geom = feat.geometry()
                    if geom is None or geom.isEmpty():
                        continue
                    if geom.contains(pt_layer) or geom.intersects(pt_layer):
                        return feat
                except Exception:
                    continue
        except Exception:
            return None
        return None


    def _value_at_point(self, layer, field_name, pt_wgs84):
        """Legge il valore al punto usando un filtro spaziale veloce."""
        try:
            if layer is None or field_name not in [f.name() for f in layer.fields()]:
                return None

            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            pt_geom = QgsGeometry.fromPointXY(pt_wgs84)
            pt_layer = self._transform_geometry(pt_geom, wgs84, layer.crs())
            if pt_layer is None or pt_layer.isEmpty():
                return None

            bbox = pt_layer.boundingBox()
            try:
                dx = max(bbox.width(), 0.000001)
                dy = max(bbox.height(), 0.000001)
                bbox.setXMinimum(bbox.xMinimum() - dx)
                bbox.setXMaximum(bbox.xMaximum() + dx)
                bbox.setYMinimum(bbox.yMinimum() - dy)
                bbox.setYMaximum(bbox.yMaximum() + dy)
            except Exception:
                pass

            request = QgsFeatureRequest().setFilterRect(bbox)
            for feat in layer.getFeatures(request):
                g = feat.geometry()
                if g is None or g.isEmpty():
                    continue
                if g.contains(pt_layer) or g.intersects(pt_layer):
                    return feat[field_name]
        except Exception:
            return None
        return None


    # ------------------------------------------------------------------
    # DEM helpers
    # ------------------------------------------------------------------
    def _is_raster_layer(self, layer):
        if layer is None:
            return False
        try:
            return layer.type() == QgsMapLayerType.RasterLayer and layer.isValid()
        except Exception:
            return False

    def _sample_raster_value(self, raster_layer, pt_wgs84, band=1):
        try:
            provider = raster_layer.dataProvider()
            if provider is None:
                return None

            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            pt_geom = QgsGeometry.fromPointXY(pt_wgs84)
            pt_raster = self._transform_geometry(pt_geom, wgs84, raster_layer.crs())
            if pt_raster is None or pt_raster.isEmpty():
                return None

            sample_point = QgsPointXY(pt_raster.asPoint())
            extent = raster_layer.extent()
            if extent is None or extent.isEmpty() or not extent.contains(sample_point):
                return None

            value = None
            try:
                identified = provider.identify(sample_point, QgsRaster.IdentifyFormatValue)
                if identified is not None and identified.isValid():
                    value = (identified.results() or {}).get(int(band))
            except Exception:
                value = None

            if value is None:
                try:
                    sampled = provider.sample(sample_point, int(band))
                    if isinstance(sampled, tuple):
                        value, ok = sampled[0], bool(sampled[1])
                    else:
                        value, ok = sampled, sampled is not None
                    if not ok:
                        value = None
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

    def _estimate_slope_from_dem(self, raster_layer, pt_wgs84, band=1):
        try:
            vals = self._dem_neighbour_values(raster_layer, pt_wgs84, band=band)
            if vals is None:
                return None
            z_left, z_right, z_down, z_up, step = vals

            dzdx = (z_right - z_left) / (2.0 * step)
            dzdy = (z_up - z_down) / (2.0 * step)

            import math
            slope_rad = math.atan((dzdx * dzdx + dzdy * dzdy) ** 0.5)
            return float(math.degrees(slope_rad))
        except Exception:
            return None

    def _estimate_aspect_from_dem(self, raster_layer, pt_wgs84, band=1):
        """
        Stima aspect in gradi 0-360.
        0/360 = nord, 90 = est, 180 = sud, 270 = ovest.
        """
        try:
            vals = self._dem_neighbour_values(raster_layer, pt_wgs84, band=band)
            if vals is None:
                return None
            z_left, z_right, z_down, z_up, step = vals

            dzdx = (z_right - z_left) / (2.0 * step)
            dzdy = (z_up - z_down) / (2.0 * step)

            import math

            # Aspect classico: direzione di massima discesa.
            aspect_rad = math.atan2(dzdx, dzdy)
            aspect_deg = 180.0 + math.degrees(aspect_rad)
            aspect_deg = aspect_deg % 360.0
            return float(aspect_deg)
        except Exception:
            return None

    def _dem_neighbour_values(self, raster_layer, pt_wgs84, band=1):
        try:
            if not self._is_raster_layer(raster_layer):
                return None

            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            metric = _shared_local_metric_crs(pt_wgs84)

            pt_geom_wgs = QgsGeometry.fromPointXY(pt_wgs84)
            pt_metric = self._transform_geometry(pt_geom_wgs, wgs84, metric)
            if pt_metric is None or pt_metric.isEmpty():
                return None

            p = pt_metric.asPoint()
            step = self._dem_pixel_size_m(raster_layer)
            if step is None or step <= 0:
                step = 30.0

            left_m = QgsGeometry.fromPointXY(QgsPointXY(p.x() - step, p.y()))
            right_m = QgsGeometry.fromPointXY(QgsPointXY(p.x() + step, p.y()))
            down_m = QgsGeometry.fromPointXY(QgsPointXY(p.x(), p.y() - step))
            up_m = QgsGeometry.fromPointXY(QgsPointXY(p.x(), p.y() + step))

            z_left = self._sample_raster_value(raster_layer, self._geom_to_wgs_point(left_m, metric, wgs84), band)
            z_right = self._sample_raster_value(raster_layer, self._geom_to_wgs_point(right_m, metric, wgs84), band)
            z_down = self._sample_raster_value(raster_layer, self._geom_to_wgs_point(down_m, metric, wgs84), band)
            z_up = self._sample_raster_value(raster_layer, self._geom_to_wgs_point(up_m, metric, wgs84), band)

            if any(v is None for v in [z_left, z_right, z_down, z_up]):
                return None

            return z_left, z_right, z_down, z_up, float(step)
        except Exception:
            return None

    def _aspect_to_exposure(self, aspect):
        if aspect is None:
            return None
        try:
            a = float(aspect) % 360.0
        except Exception:
            return None

        if 135 <= a <= 225:
            return "south"
        if a >= 315 or a <= 45:
            return "north"
        if 45 < a < 135:
            return "east"
        if 225 < a < 315:
            return "west"
        return "flat"

    def _dem_pixel_size_m(self, raster_layer):
        try:
            extent = raster_layer.extent()
            width = raster_layer.width()
            height = raster_layer.height()
            if width <= 0 or height <= 0:
                return None

            src = raster_layer.crs()
            center_src = QgsGeometry.fromPointXY(QgsPointXY(extent.center()))
            center_wgs = self._transform_geometry(
                center_src, src, QgsCoordinateReferenceSystem("EPSG:4326")
            )
            if center_wgs is None or center_wgs.isEmpty():
                return None
            metric = _shared_local_metric_crs(center_wgs.asPoint())
            g1 = QgsGeometry.fromPointXY(QgsPointXY(extent.xMinimum(), extent.yMinimum()))
            g2 = QgsGeometry.fromPointXY(QgsPointXY(extent.xMaximum(), extent.yMaximum()))
            g1m = self._transform_geometry(g1, src, metric)
            g2m = self._transform_geometry(g2, src, metric)
            if not g1m or not g2m:
                return None

            p1 = g1m.asPoint()
            p2 = g2m.asPoint()
            px = abs(p2.x() - p1.x()) / float(width)
            py = abs(p2.y() - p1.y()) / float(height)
            return max(px, py)
        except Exception:
            return None

    def _geom_to_wgs_point(self, geom, src_crs, wgs84):
        g = self._transform_geometry(geom, src_crs, wgs84)
        if g is None or g.isEmpty():
            return None
        return g.asPoint()

    # ------------------------------------------------------------------
    # Normalizers / output
    # ------------------------------------------------------------------
    def _normalize_rock_type(self, value):
        if value in [None, ""]:
            return None
        text = str(value).lower()

        # Siliceo/acido/metamorfico: includo singolare/plurale e termini comuni
        # dei layer geologici lombardi.
        siliceous_terms = [
            "silice", "siliceo", "silicea",
            "granito", "graniti", "granodiorite", "granodioriti",
            "tonalite", "tonaliti", "diorite", "dioriti",
            "gneiss", "ortogneiss", "paragneiss",
            "quarz", "quarzo", "quarzite", "quarziti",
            "micascisto", "micascisti", "scisto", "scisti",
            "fillade", "filladi",
            "porfido", "porfidi", "rioliti", "riolite",
            "arenaria", "arenarie", "sandstone",
            "siltite", "siltiti", "argillite", "argilliti",
            "conglomerato", "conglomerati"
        ]

        # Carbonatico/basico.
        calcareous_terms = [
            "calcare", "calcari", "calcareo", "calcarea",
            "dolomia", "dolomie", "dolomit", "dolomitico", "dolomitica",
            "carbonat", "marmo", "marmi",
            "marna", "marne"
        ]

        has_siliceous = any(k in text for k in siliceous_terms)
        has_calcareous = any(k in text for k in calcareous_terms)

        # Unità miste tipo "arenarie, marne, siltiti, argilliti, calcari".
        if has_siliceous and has_calcareous:
            return "misto"
        if has_siliceous:
            return "siliceo"
        if has_calcareous:
            return "calcareo"
        if any(k in text for k in ["misto", "alternanza", "complesso", "flysch"]):
            return "misto"
        return str(value).strip().lower()


    def _normalize_substrate(self, value):
        if value in [None, ""]:
            return None
        text = str(value).lower()

        if any(k in text for k in ["rocc", "rock", "sasso", "pietra", "parete", "rup"]):
            return "roccia"
        if any(k in text for k in ["suolo", "soil", "terra", "terric"]):
            return "suolo"
        if any(k in text for k in ["bosco", "alber", "tree", "forest"]):
            return "bosco"
        if any(k in text for k in ["musch", "moss"]):
            return "muschio"
        return str(value).strip().lower()

    def _create_heatmap_layer(self, features_data, layer_name="GeoLichen Suitability Surface", uncertainty=None, radius_mm=18, opacity=0.60):
        """GeoLichen Suitability Surface (GSS) v4.2.

        Non è una heatmap di densità.
        Crea un raster GeoTIFF 0-100 basato sugli score dei candidati.

        Novità 4.2:
        - usa una GeoLichen Weight Function logistica, non score^1.4;
        - mantiene visibile anche la bassa suitability con azzurro chiaro;
        - usa tutti i candidati come supporto spaziale, ma i punti bassi pesano poco;
        - NoData solo fuori dall'area analizzata/supportata.
        """
        try:
            import os
            import tempfile
            import math
            import numpy as np
            from osgeo import gdal
            from qgis.core import (
                QgsRasterLayer,
    QgsRaster,
                QgsCoordinateReferenceSystem,
                QgsColorRampShader,
                QgsRasterShader,
                QgsSingleBandPseudoColorRenderer,
            )
            try:
                from qgis.PyQt.QtGui import QColor
            except Exception:
                QColor = None

            if not features_data:
                raise ValueError("nessun punto candidato")

            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

            # Usa lo stesso CRS metrico locale impiegato da buffer e griglia.
            # Il centro viene determinato dai candidati in WGS84 prima della
            # trasformazione, evitando la deformazione di EPSG:3857.
            valid_wgs_points = [row.get("point") for row in features_data if row.get("point") is not None]
            if not valid_wgs_points:
                raise ValueError("nessun punto candidato valido")
            mean_lon = sum(float(p.x()) for p in valid_wgs_points) / len(valid_wgs_points)
            mean_lat = sum(float(p.y()) for p in valid_wgs_points) / len(valid_wgs_points)
            metric = _shared_local_metric_crs(QgsPointXY(mean_lon, mean_lat))

            all_pts = []
            all_scores = []
            for row in features_data:
                try:
                    pt = row.get("point")
                    env = row.get("env") or {}
                    s = env.get("norm_score")
                    if s in [None, ""]:
                        s = row.get("raw_score")
                    if s in [None, ""]:
                        s = row.get("score")
                    s = max(0.0, min(100.0, float(s)))
                    if s <= 0:
                        continue

                    geom = QgsGeometry.fromPointXY(pt)
                    geom_m = self._transform_geometry(geom, wgs84, metric)
                    if geom_m is None or geom_m.isEmpty():
                        continue
                    p = geom_m.asPoint()
                    all_pts.append((float(p.x()), float(p.y())))
                    all_scores.append(s)
                except Exception:
                    continue

            if len(all_pts) < 3:
                raise ValueError("punti insufficienti per GSS")

            xs = np.array([p[0] for p in all_pts], dtype=float)
            ys = np.array([p[1] for p in all_pts], dtype=float)
            zs = np.array(all_scores, dtype=float)

            xmin, xmax = float(xs.min()), float(xs.max())
            ymin, ymax = float(ys.min()), float(ys.max())
            span_x = max(1.0, xmax - xmin)
            span_y = max(1.0, ymax - ymin)

            unique_x = np.unique(np.round(xs, 3))
            unique_y = np.unique(np.round(ys, 3))
            dxs = np.diff(np.sort(unique_x)); dxs = dxs[dxs > 0.5]
            dys = np.diff(np.sort(unique_y)); dys = dys[dys > 0.5]
            inferred = []
            if dxs.size:
                inferred.append(float(np.median(dxs)))
            if dys.size:
                inferred.append(float(np.median(dys)))
            # Raster più fine della griglia: con passo 30 m usa normalmente
            # pixel da 7.5 m. Il maggiore dettaglio riguarda solo la resa della
            # superficie e non crea nuova informazione ecologica.
            inferred_spacing = (
                float(np.median(inferred))
                if inferred
                else max(10.0, min(span_x, span_y) / 160.0)
            )
            cell = inferred_spacing / 4.0
            cell = max(3.0, min(15.0, cell))

            # Limite prudente per aree estese; la dimensione viene adattata senza
            # alterare i punti o il ranking.
            max_dim = 1400
            width0 = int(math.ceil(span_x / cell)) + 8
            height0 = int(math.ceil(span_y / cell)) + 8
            if width0 > max_dim or height0 > max_dim:
                factor = max(width0 / max_dim, height0 / max_dim)
                cell *= factor

            # Kernel gaussiano continuo: il bandwidth è proporzionale al passo
            # originale e fonde le impronte dei punti adiacenti, eliminando il tipico
            # effetto "a pallini" dell'IDW centrato sui candidati.
            bandwidth = max(inferred_spacing * 1.10, cell * 4.0)
            support_radius = min(240.0, max(bandwidth * 3.0, inferred_spacing * 2.5))
            xmin -= support_radius
            xmax += support_radius
            ymin -= support_radius
            ymax += support_radius

            width = int(math.ceil((xmax - xmin) / cell))
            height = int(math.ceil((ymax - ymin) / cell))

            # GeoLichen Weight Function logistica: conserva il significato del
            # GSS, mentre il kernel gaussiano produce una superficie omogenea.
            gwf_center = 55.0
            gwf_k = 0.17
            score_weight = 1.0 / (1.0 + np.exp(-gwf_k * (zs - gwf_center)))
            score_weight = np.clip(score_weight, 0.03, 1.0)

            arr = np.full((height, width), -9999.0, dtype=np.float32)
            grid_x = xmin + (np.arange(width, dtype=float) + 0.5) * cell
            two_sigma2 = 2.0 * bandwidth * bandwidth

            for r in range(height):
                y = ymax - (r + 0.5) * cell
                gx = grid_x[:, None]
                dy = y - ys[None, :]
                dx = gx - xs[None, :]
                d2 = dx * dx + dy * dy

                nearest_d = np.sqrt(d2.min(axis=1))
                mask = nearest_d <= support_radius
                if not np.any(mask):
                    continue

                # Tutti i punti entro tre sigma contribuiscono. Non viene imposto
                # il valore esatto del candidato nel centro della cella: questo evita
                # anelli e macchie circolari isolate.
                kernel = np.exp(-d2 / max(two_sigma2, 1e-9))
                kernel[d2 > support_radius * support_radius] = 0.0
                w = kernel * score_weight[None, :]
                sum_w = w.sum(axis=1)
                vals = (w * zs[None, :]).sum(axis=1) / np.maximum(sum_w, 1e-9)
                valid_row = mask & (sum_w > 1e-8)
                arr[r, valid_row] = np.clip(vals[valid_row], 0.0, 100.0).astype(np.float32)

            # Curva di contrasto robusta.
            valid_mask = arr != -9999.0
            valid = arr[valid_mask]
            if valid.size > 0:
                lo = float(np.percentile(valid, 2))
                hi = float(np.percentile(valid, 98))
                if hi > lo:
                    scaled = (arr - lo) / (hi - lo)
                    scaled = np.clip(scaled, 0.0, 1.0)
                    gamma = 0.95
                    contrasted = np.power(scaled, gamma) * 100.0
                    contrasted = np.where(valid_mask, np.maximum(contrasted, 4.0), -9999.0)
                    arr = np.where(valid_mask, np.clip(contrasted, 0.0, 100.0), -9999.0).astype(np.float32)

            out_dir = Path(tempfile.gettempdir()) / "geolichen_surfaces"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / ("geolichen_gss_logistic_%s.tif" % os.getpid())

            driver = gdal.GetDriverByName("GTiff")
            ds = driver.Create(str(out_path), width, height, 1, gdal.GDT_Float32, options=["COMPRESS=LZW"])
            ds.SetGeoTransform((xmin, cell, 0.0, ymax, 0.0, -cell))
            try:
                ds.SetProjection(metric.toWkt())
            except Exception:
                pass
            band = ds.GetRasterBand(1)
            band.WriteArray(arr)
            band.SetNoDataValue(-9999)
            band.SetDescription("GeoLichen Suitability Surface logistic 0-100")
            band.FlushCache()
            ds.FlushCache()
            ds = None

            raster = QgsRasterLayer(str(out_path), layer_name)
            if not raster.isValid():
                raise ValueError("raster GSS non valido")

            try:
                shader = QgsRasterShader()
                ramp = QgsColorRampShader()
                ramp.setColorRampType(QgsColorRampShader.Interpolated)
                if QColor is not None:
                    items = [
                        QgsColorRampShader.ColorRampItem(0, QColor(220, 242, 255, 135), "molto bassa"),
                        QgsColorRampShader.ColorRampItem(15, QColor(180, 230, 255, 145), "bassa"),
                        QgsColorRampShader.ColorRampItem(35, QColor(95, 210, 220, 165), "medio-bassa"),
                        QgsColorRampShader.ColorRampItem(55, QColor(85, 205, 135, 185), "media"),
                        QgsColorRampShader.ColorRampItem(72, QColor(245, 225, 80, 205), "alta"),
                        QgsColorRampShader.ColorRampItem(88, QColor(245, 145, 45, 225), "molto alta"),
                        QgsColorRampShader.ColorRampItem(100, QColor(210, 35, 30, 240), "massima"),
                    ]
                    ramp.setColorRampItemList(items)
                    shader.setRasterShaderFunction(ramp)
                    renderer = QgsSingleBandPseudoColorRenderer(raster.dataProvider(), 1, shader)
                    raster.setRenderer(renderer)
            except Exception:
                pass

            try:
                opacity = float(opacity)
                if opacity > 1:
                    opacity = opacity / 100.0
                opacity = max(0.05, min(1.0, opacity))
                if hasattr(raster, "setOpacity"):
                    raster.setOpacity(opacity)
            except Exception:
                pass

            QgsProject.instance().addMapLayer(raster)
            return raster

        except Exception:
            return self._create_points_layer(
                features_data,
                layer_name=layer_name + " - fallback points",
                uncertainty=uncertainty,
                add_to_project=True,
            )


    def _create_suitability_surface_idw_v34(self, features_data, layer_name="Habitat suitability surface", opacity=0.60):
        """Genera un GeoTIFF temporaneo interpolando gli score con IDW.

        Implementazione autonoma:
        - trasforma i punti nella zona UTM locale;
        - stima la risoluzione dalla griglia dei candidati;
        - usa solo candidati con score valido;
        - interpola con IDW sui punti vicini.
        """
        if not features_data:
            return None

        try:
            import numpy as np
            from osgeo import gdal, osr
        except Exception:
            return None

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        valid_points = [row.get("point") for row in features_data if row.get("point") is not None]
        if not valid_points:
            return None
        mean_point = QgsPointXY(
            sum(float(pt.x()) for pt in valid_points) / len(valid_points),
            sum(float(pt.y()) for pt in valid_points) / len(valid_points),
        )
        metric = _shared_local_metric_crs(mean_point)

        pts = []
        scores = []
        for row in features_data:
            try:
                pt = row.get("point")
                env = row.get("env") or {}
                if pt is None:
                    continue
                # GeoLichen 4.5a: la GSS usa lo stesso final_score del ranking.
                sc = env.get("final_score")
                if sc in [None, ""]:
                    sc = row.get("score")
                sc = float(sc)
                if sc < 0:
                    continue

                g = QgsGeometry.fromPointXY(pt)
                gm = self._transform_geometry(g, wgs84, metric)
                if gm is None or gm.isEmpty():
                    continue
                pm = gm.asPoint()
                pts.append((float(pm.x()), float(pm.y())))
                scores.append(max(0.0, min(100.0, sc)))
            except Exception:
                continue

        if len(pts) < 3:
            return None

        pts = np.asarray(pts, dtype=float)
        scores = np.asarray(scores, dtype=float)

        minx, miny = pts.min(axis=0)
        maxx, maxy = pts.max(axis=0)

        # Stima cella dalla griglia: evita raster troppo grandi.
        cell = self._estimate_surface_cell_size_v34(pts)
        if cell is None:
            cell = 25.0
        cell = max(5.0, min(100.0, float(cell)))

        pad = cell * 3.0
        minx -= pad
        miny -= pad
        maxx += pad
        maxy += pad

        width = int(max(20, min(900, round((maxx - minx) / cell))))
        height = int(max(20, min(900, round((maxy - miny) / cell))))
        if width <= 0 or height <= 0:
            return None

        # Se il raster sarebbe troppo denso, aumenta cell size.
        max_cells = 450000
        if width * height > max_cells:
            factor = ((width * height) / max_cells) ** 0.5
            cell *= factor
            width = int(max(20, round((maxx - minx) / cell)))
            height = int(max(20, round((maxy - miny) / cell)))

        xs = minx + (np.arange(width) + 0.5) * cell
        ys = maxy - (np.arange(height) + 0.5) * cell

        arr = np.full((height, width), -9999.0, dtype=np.float32)

        # IDW locale: considera solo i candidati vicini.
        radius = max(cell * 5.0, self._estimate_surface_radius_v34(pts, cell))
        power = 2.0

        for iy, y in enumerate(ys):
            dy = pts[:, 1] - y
            for ix, x in enumerate(xs):
                dx = pts[:, 0] - x
                d2 = dx * dx + dy * dy
                mask = d2 <= radius * radius
                if not np.any(mask):
                    # fallback ai 8 più vicini se nessun punto entra nel raggio
                    k = min(8, len(d2))
                    idx = np.argpartition(d2, k-1)[:k]
                else:
                    idx = np.where(mask)[0]

                local_d2 = d2[idx]
                local_scores = scores[idx]
                if np.any(local_d2 < 0.01):
                    arr[iy, ix] = float(local_scores[np.argmin(local_d2)])
                else:
                    w = 1.0 / np.power(local_d2, power / 2.0)
                    arr[iy, ix] = float(np.sum(w * local_scores) / np.sum(w))

        tmp_dir = Path(tempfile.gettempdir()) / "geolichen_surfaces"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        out_path = tmp_dir / (re.sub(r"[^A-Za-z0-9_]+", "_", layer_name)[:80] + ".tif")

        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(str(out_path), width, height, 1, gdal.GDT_Float32, options=["COMPRESS=LZW"])
        if ds is None:
            return None

        gt = (minx, cell, 0.0, maxy, 0.0, -cell)
        ds.SetGeoTransform(gt)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3857)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(-9999.0)
        band.WriteArray(arr)
        band.FlushCache()
        ds.FlushCache()
        ds = None

        raster = QgsRasterLayer(str(out_path), layer_name)
        if raster is None or not raster.isValid():
            return None

        self._style_suitability_raster_v34(raster)

        try:
            opacity = float(opacity)
            if opacity > 1:
                opacity = opacity / 100.0
            opacity = max(0.05, min(1.0, opacity))
            if hasattr(raster, "setOpacity"):
                raster.setOpacity(opacity)
        except Exception:
            pass

        QgsProject.instance().addMapLayer(raster)
        return raster

    def _estimate_surface_cell_size_v34(self, pts):
        """Stima passo griglia dai punti candidati."""
        try:
            import numpy as np
            if len(pts) < 2:
                return None
            # campiona per evitare costo eccessivo
            sample = pts
            if len(sample) > 500:
                idx = np.linspace(0, len(sample)-1, 500).astype(int)
                sample = sample[idx]
            dists = []
            for i, p in enumerate(sample[:250]):
                d2 = np.sum((sample - p) ** 2, axis=1)
                d2 = d2[d2 > 0.01]
                if len(d2):
                    dists.append(float(np.sqrt(np.min(d2))))
            if not dists:
                return None
            return float(np.median(dists))
        except Exception:
            return None

    def _estimate_surface_radius_v34(self, pts, cell):
        try:
            c = float(cell or 25.0)
            return max(c * 4.0, min(250.0, c * 8.0))
        except Exception:
            return 150.0

    def _style_suitability_raster_v34(self, raster):
        """Applica palette blu-verde-giallo-rosso 0-100 al raster."""
        try:
            if QColor is None:
                return
            shader = QgsRasterShader()
            color_ramp = QgsColorRampShader()
            color_ramp.setColorRampType(QgsColorRampShader.Interpolated)
            items = [
                QgsColorRampShader.ColorRampItem(0, QColor(60, 100, 220), "0"),
                QgsColorRampShader.ColorRampItem(40, QColor(50, 200, 180), "40"),
                QgsColorRampShader.ColorRampItem(60, QColor(180, 220, 80), "60"),
                QgsColorRampShader.ColorRampItem(80, QColor(245, 190, 60), "80"),
                QgsColorRampShader.ColorRampItem(100, QColor(220, 40, 40), "100"),
            ]
            color_ramp.setColorRampItemList(items)
            shader.setRasterShaderFunction(color_ramp)
            renderer = QgsSingleBandPseudoColorRenderer(raster.dataProvider(), 1, shader)
            raster.setRenderer(renderer)
            raster.triggerRepaint()
        except Exception:
            pass


    def _suitability_color_ramp(self):
        """Color ramp per la heat map di suitability.

        Blu = basso, verde/giallo = medio, rosso = alto.
        """
        if QColor is None or QgsGradientColorRamp is None:
            return None
        try:
            ramp = QgsGradientColorRamp(QColor(30, 70, 220), QColor(220, 30, 30))
            if QgsGradientStop is not None and hasattr(ramp, "setStops"):
                stops = [
                    QgsGradientStop(0.25, QColor(0, 180, 220)),
                    QgsGradientStop(0.50, QColor(40, 190, 90)),
                    QgsGradientStop(0.75, QColor(245, 210, 40)),
                ]
                ramp.setStops(stops)
            return ramp
        except Exception:
            try:
                return QgsGradientColorRamp(QColor(30, 70, 220), QColor(220, 30, 30))
            except Exception:
                return None

    def _create_points_layer(self, features_data, layer_name="Habitat suitability points", uncertainty=None, add_to_project=True):
        layer = QgsVectorLayer("Point?crs=EPSG:4326", layer_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("rank", QVariant.Int),
            QgsField("grid_lvl", QVariant.String),
            QgsField("top10", QVariant.String),
            QgsField("selected", QVariant.String),
            QgsField("sel_method", QVariant.String),
            QgsField("sel_reason", QVariant.String),
            QgsField("score", QVariant.Int),
            QgsField("raw_score", QVariant.Double),
            QgsField("heat_w", QVariant.Double),
            QgsField("eco_score", QVariant.Double),
            QgsField("acc_score", QVariant.Double),
            QgsField("record_score", QVariant.Double),
            QgsField("access_conf", QVariant.Double),
            QgsField("geo_score", QVariant.Double),
            QgsField("final_score", QVariant.Double),
            QgsField("terrain_s", QVariant.Double),
            QgsField("terrain_r", QVariant.String),
            QgsField("slope_pen", QVariant.Double),
            QgsField("slope_ctx", QVariant.String),
            QgsField("slope_r", QVariant.String),
            QgsField("ctx_type", QVariant.String),
            QgsField("ctx_dist_m", QVariant.Double),
            QgsField("ctx_score", QVariant.Double),
            QgsField("trail_acc", QVariant.Double),
            QgsField("trail_src", QVariant.String),
            QgsField("trail_name", QVariant.String),
            QgsField("trail_type", QVariant.String),
            QgsField("trail_cls", QVariant.String),
            QgsField("vt_access", QVariant.String),
            QgsField("rock_type", QVariant.String),
            QgsField("rock_raw", QVariant.String),
            QgsField("litho_ph", QVariant.String),
            QgsField("litho_ph_s", QVariant.Double),
            QgsField("litho_ph_m", QVariant.String),
            QgsField("substrate", QVariant.String),
            QgsField("soil_raw", QVariant.String),
            QgsField("soil_ph", QVariant.String),
            QgsField("soil_ph_raw", QVariant.String),
            QgsField("soil_conf", QVariant.String),
            QgsField("soil_conf_s", QVariant.Double),
            QgsField("soil_reason", QVariant.String),
            QgsField("soil_ph_num", QVariant.Double),
            QgsField("soil_ph_f", QVariant.String),
            QgsField("soil_ph_cls", QVariant.String),
            QgsField("ph_score", QVariant.Double),
            QgsField("ph_reason", QVariant.String),
            QgsField("tree_type", QVariant.String),
            QgsField("tree_raw", QVariant.String),
            QgsField("expected_tree", QVariant.String),
            QgsField("observed_tree", QVariant.String),
            QgsField("forest_cat", QVariant.String),
            QgsField("forest_lit", QVariant.String),
            QgsField("forest_dist_m", QVariant.Double),
            QgsField("forest_dist_s", QVariant.Double),
            QgsField("tree_score", QVariant.Double),
            QgsField("tree_reason", QVariant.String),
            QgsField("trail_dist_m", QVariant.Double),
            QgsField("trail_bonus", QVariant.Double),
            QgsField("trail_pen", QVariant.Double),
            QgsField("veget_belt", QVariant.String),
            QgsField("belt_match", QVariant.String),
            QgsField("belt_min", QVariant.Double),
            QgsField("belt_max", QVariant.Double),
            QgsField("humidity", QVariant.String),
            QgsField("altitude", QVariant.Double),
            QgsField("dem_source", QVariant.String),
            QgsField("dem_priority", QVariant.Int),
            QgsField("dem_valid_n", QVariant.Int),
            QgsField("dem_fallback", QVariant.String),
            QgsField("dem_spread_m", QVariant.Double),
            QgsField("record_altitude", QVariant.Double),
            QgsField("alt_delta_m", QVariant.Double),
            QgsField("alt_min_ok", QVariant.Double),
            QgsField("alt_max_ok", QVariant.Double),
            QgsField("alt_filter", QVariant.String),
            QgsField("alt_tol_m", QVariant.Double),
            QgsField("italic_alt_min", QVariant.Double),
            QgsField("italic_alt_max", QVariant.Double),
            QgsField("it_alt_cls", QVariant.String),
            QgsField("it_alt_src", QVariant.String),
            QgsField("slope", QVariant.Double),
            QgsField("aspect", QVariant.Double),
            QgsField("aspect_cls", QVariant.String),
            QgsField("record_asp", QVariant.String),
            QgsField("asp_diff", QVariant.Double),
            QgsField("asp_bonus", QVariant.Double),
            QgsField("asp_match", QVariant.String),
            QgsField("exposure", QVariant.String),
            QgsField("dist_m", QVariant.Double),
            QgsField("constraints", QVariant.String),
            QgsField("constraint_sources", QVariant.String),
            QgsField("gbif_constraints", QVariant.String),
            QgsField("gss_constraints", QVariant.String),
            QgsField("details", QVariant.String),
            QgsField("uncert_m", QVariant.Double),
            QgsField("gbif_unc_m", QVariant.Double),
            QgsField("model_r_m", QVariant.Double),
            QgsField("geo_rad_m", QVariant.Double),
            QgsField("grid_err_m", QVariant.Double),
            QgsField("confidence", QVariant.String),
            QgsField("mci", QVariant.Double),
            QgsField("mci_class", QVariant.String),
            QgsField("mci_reason", QVariant.String),
            QgsField("cand_spread", QVariant.Double),
            QgsField("data_comp", QVariant.Double),
            QgsField("eco_unique", QVariant.Double),
            QgsField("equiv_cand", QVariant.Int),
            QgsField("score_gap", QVariant.Double),
            QgsField("ssi", QVariant.Double),
            QgsField("ssi_class", QVariant.String),
            QgsField("ssi_reason", QVariant.String),
            QgsField("loo_dist_m", QVariant.Double),
            QgsField("ssi_spread", QVariant.Double),
            QgsField("ssi_alt_n", QVariant.Int),
            QgsField("ssi_cl_n", QVariant.Int),
            QgsField("ssi_main_n", QVariant.Int),
            QgsField("ssi_share", QVariant.Double),
            QgsField("ssi_rad_m", QVariant.Double),
            QgsField("ssi_med_m", QVariant.Double),
            QgsField("ssi_eps_m", QVariant.Double),
            QgsField("ssi_near_m", QVariant.Double),
            QgsField("gbif_lon", QVariant.Double),
            QgsField("gbif_lat", QVariant.Double),
            QgsField("gbif_ctr_m", QVariant.String),
            QgsField("gbif_ctr_s", QVariant.String),
            QgsField("decimalLatitude", QVariant.Double),
            QgsField("decimalLongitude", QVariant.Double),
            QgsField("geodeticDatum", QVariant.String),
            QgsField("coordinateUncertaintyInMeters", QVariant.Double),
            QgsField("coordinatePrecision", QVariant.Double),
            QgsField("pointRadiusSpatialFit", QVariant.Double),
            QgsField("footprintWKT", QVariant.String),
            QgsField("footprintSRS", QVariant.String),
            QgsField("georeferencedBy", QVariant.String),
            QgsField("georeferencedDate", QVariant.String),
            QgsField("georeferenceProtocol", QVariant.String),
            QgsField("georeferenceSources", QVariant.String),
            QgsField("georeferenceVerificationStatus", QVariant.String),
            QgsField("georeferenceRemarks", QVariant.String),
            QgsField("gbif_dwc_complete", QVariant.String),
            QgsField("loc_type", QVariant.String),
            QgsField("geom_type", QVariant.String),
            QgsField("loc_cls_cf", QVariant.Double),
            QgsField("loc_cls_r", QVariant.String),
            QgsField("loc_ref_t", QVariant.String),
            QgsField("loc_ref_n", QVariant.String),
            QgsField("plaus_alt", QVariant.String),
            QgsField("alt_reason", QVariant.String),
            QgsField("score_dlt", QVariant.Double),
            QgsField("aspect_sc", QVariant.Double),
            QgsField("aspect_r", QVariant.String),
            QgsField("aspect_deg", QVariant.Double),
            QgsField("aspect_dir", QVariant.String),
            QgsField("record_aspect", QVariant.String),
            QgsField("aspect_diff_deg", QVariant.Double),
            QgsField("aspect_score", QVariant.Double),
            QgsField("eco_exposure", QVariant.String),
            QgsField("norm_score", QVariant.Double),
            QgsField("norm_w", QVariant.String),
            QgsField("score_comp", QVariant.String),
            QgsField("alt_score", QVariant.Double),
            QgsField("sub_score", QVariant.Double),
            QgsField("lith_score", QVariant.Double),
            QgsField("italic_score", QVariant.Double),
            QgsField("access_score", QVariant.Double),
            QgsField("slope_score", QVariant.Double),
            QgsField("geo_macro", QVariant.Double),
            QgsField("terrain_m", QVariant.Double),
            QgsField("env_macro", QVariant.Double),
            QgsField("access_m", QVariant.Double),
            QgsField("score_arch", QVariant.String),
            QgsField("env_group", QVariant.String),
            QgsField("env_sub_s", QVariant.Double),
            QgsField("env_lith_s", QVariant.Double),
            QgsField("env_ph_s", QVariant.Double),
            QgsField("env_hab_s", QVariant.Double),
            QgsField("env_tree_s", QVariant.Double),
            QgsField("env_parts", QVariant.String),
            QgsField("env_w", QVariant.String),
        ])
        layer.updateFields()

        uncertainty = uncertainty or {}
        feats = []
        for row in features_data:
            env = row.get("env") or {}
            constraints = row.get("constraints") or {}
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(row["point"]))
            feat["rank"] = int(row.get("rank") or 0)
            feat["grid_lvl"] = str(row.get("grid_level") or "final")[:30]
            feat["top10"] = "yes" if row.get("is_top10") else "no"
            # La selezione è determinata dal motore di ranking, non dal tipo
            # di griglia. Questo consente al Rank 1 globale di essere selezionato
            # quando il raffinamento adattivo non viene applicato.
            selected_value = row.get("selected")
            if isinstance(selected_value, str):
                is_selected = selected_value.strip().lower() in {"yes", "true", "1"}
            else:
                is_selected = bool(selected_value)
            feat["selected"] = "yes" if is_selected else "no"
            feat["sel_method"] = "automatic_rank_1" if is_selected else ""
            feat["sel_reason"] = "highest_geolichen_rank_after_gss_and_tie_breaks" if is_selected else ""
            official_score = self._to_float(env.get("final_score"))
            if official_score is None:
                official_score = self._to_float(row.get("score")) or 0.0
            feat["score"] = int(round(official_score))
            feat["raw_score"] = self._to_float(row.get("raw_score"))
            feat["heat_w"] = official_score
            feat["eco_score"] = self._to_float(env.get("ecological_score"))
            feat["acc_score"] = self._to_float(env.get("accessibility_score"))
            feat["record_score"] = self._to_float(env.get("record_score"))
            feat["access_conf"] = self._to_float(env.get("accessibility_confidence"))
            feat["geo_score"] = self._to_float(env.get("geography_score"))
            feat["final_score"] = official_score
            feat["terrain_s"] = self._to_float(env.get("terrain_score"))
            feat["terrain_r"] = str(env.get("terrain_reason") or "")[:120]
            feat["slope_pen"] = self._to_float(env.get("slope_penalty"))
            feat["slope_ctx"] = str(env.get("slope_context") or "")[:40]
            feat["slope_r"] = str(env.get("slope_penalty_reason") or "")[:160]
            feat["ctx_type"] = str(env.get("context_type") or "")[:40]
            feat["ctx_dist_m"] = self._to_float(env.get("context_dist_m"))
            feat["ctx_score"] = self._to_float(env.get("context_score"))
            feat["trail_acc"] = self._to_float(env.get("trail_accessibility_score"))
            feat["trail_src"] = str(env.get("trail_source") or "")[:80]
            feat["trail_name"] = str(env.get("trail_name") or "")[:120]
            feat["trail_type"] = str(env.get("trail_type") or "")[:60]
            feat["trail_cls"] = str(env.get("trail_class") or "")[:40]
            feat["vt_access"] = str(env.get("vector_tile_access_layers") or "")[:120]
            feat["rock_type"] = str(env.get("rock_type") or "")
            feat["rock_raw"] = str(env.get("rock_raw") or "")[:250]
            feat["litho_ph"] = str(env.get("litho_soil_ph") or "")
            feat["litho_ph_s"] = self._to_float(env.get("litho_soil_ph_score"))
            feat["litho_ph_m"] = str(env.get("litho_soil_ph_match") or "")
            feat["substrate"] = str(env.get("substrate") or "")
            feat["soil_raw"] = str(env.get("soil_raw") or "")[:250]
            feat["soil_ph"] = str(env.get("soil_ph") or "")
            feat["soil_ph_raw"] = str(env.get("soil_ph_raw") or "")[:250]
            feat["soil_conf"] = str(env.get("soil_confidence") or "")
            feat["soil_conf_s"] = self._to_float(env.get("soil_confidence_score"))
            feat["soil_reason"] = str(env.get("soil_confidence_reason") or "")[:250]
            feat["soil_ph_num"] = self._to_float(env.get("soil_ph_num"))
            feat["soil_ph_f"] = str(env.get("soil_ph_field") or "")[:60]
            feat["soil_ph_cls"] = str(env.get("soil_ph_class") or "")[:40]
            feat["ph_score"] = self._to_float(env.get("ph_score"))
            feat["ph_reason"] = str(env.get("ph_reason") or "")[:250]
            feat["tree_type"] = str(env.get("tree_type") or "")
            feat["tree_raw"] = str(env.get("tree_raw") or "")[:250]
            feat["expected_tree"] = str(env.get("expected_tree") or "")[:80]
            feat["observed_tree"] = str(env.get("observed_tree") or "")[:80]
            feat["forest_cat"] = str(env.get("forest_category") or "")[:80]
            feat["forest_lit"] = str(env.get("forest_lithology") or "")[:80]
            feat["forest_dist_m"] = self._to_float(env.get("forest_dist_m"))
            feat["forest_dist_s"] = self._to_float(env.get("forest_dist_score")) or 0.0
            try:
                feat["tree_score"] = float(env.get("tree_match_score") or 0.0)
            except Exception:
                feat["tree_score"] = 0.0
            feat["tree_reason"] = str(env.get("tree_match_reason") or "")[:220]
            feat["trail_dist_m"] = self._to_float(env.get("trail_dist_m"))
            feat["trail_bonus"] = self._to_float(env.get("trail_bonus"))
            feat["trail_pen"] = self._to_float(env.get("trail_penalty"))
            feat["veget_belt"] = str(env.get("vegetation_belt") or env.get("vegetation_belt_raw") or "")
            feat["belt_match"] = str(env.get("vegetation_belt_match") or "")
            feat["belt_min"] = self._to_float(env.get("vegetation_belt_min"))
            feat["belt_max"] = self._to_float(env.get("vegetation_belt_max"))
            feat["humidity"] = str(env.get("humidity") or "")
            feat["altitude"] = self._to_float(env.get("altitude"))
            feat["dem_source"] = str(env.get("dem_source") or "")[:120]
            feat["dem_priority"] = int(env.get("dem_priority") or 0)
            feat["dem_valid_n"] = int(env.get("dem_valid_count") or 0)
            feat["dem_fallback"] = "yes" if env.get("dem_fallback_used") else "no"
            feat["dem_spread_m"] = self._to_float(env.get("dem_spread_m"))
            feat["record_altitude"] = self._to_float(env.get("record_altitude"))
            feat["alt_delta_m"] = self._to_float(row.get("alt_delta_m")) if row.get("alt_delta_m") is not None else self._altitude_delta(env.get("altitude"), env.get("record_altitude"))
            feat["alt_min_ok"] = self._to_float(env.get("altitude_min_ok"))
            feat["alt_max_ok"] = self._to_float(env.get("altitude_max_ok"))
            feat["alt_filter"] = str(env.get("altitude_filter_type") or "")
            feat["alt_tol_m"] = self._to_float(env.get("altitude_tolerance_m"))
            feat["italic_alt_min"] = self._to_float(env.get("italic_altitudinal_distribution_min") or constraints.get("altitude_min"))
            feat["italic_alt_max"] = self._to_float(env.get("italic_altitudinal_distribution_max") or constraints.get("altitude_max"))
            try:
                cmin = env.get("italic_altitude_class_min")
                cmax = env.get("italic_altitude_class_max")
                feat["it_alt_cls"] = (f"{cmin}-{cmax}" if cmin not in [None, ""] or cmax not in [None, ""] else "")
                feat["it_alt_src"] = str(env.get("altitudinal_distribution_source") or "")[:80]
            except Exception:
                feat["it_alt_cls"] = ""
                feat["it_alt_src"] = ""
            feat["slope"] = self._to_float(env.get("slope"))
            feat["aspect"] = self._to_float(env.get("aspect"))
            feat["aspect_cls"] = str(env.get("aspect_class") or "")
            feat["record_asp"] = str(env.get("record_aspect") or "")
            feat["asp_diff"] = self._to_float(env.get("aspect_difference_deg"))
            feat["asp_bonus"] = self._to_float(env.get("aspect_bonus"))
            feat["asp_match"] = str(env.get("aspect_match") or "")
            feat["exposure"] = str(env.get("exposure") or "")
            feat["dist_m"] = self._to_float(row.get("distance_to_center_m"))
            feat["constraints"] = self._constraints_to_text(constraints)[:250]
            metadata = row.get("constraint_metadata") or []
            feat["constraint_sources"] = "; ".join(sorted({str(x.get("source") or "") for x in metadata if x.get("source")}))[:250]
            feat["gbif_constraints"] = "; ".join(
                f"{x.get('name')}={x.get('value')}" for x in metadata if x.get("affects_gbif_extent")
            )[:250]
            feat["gss_constraints"] = "; ".join(
                f"{x.get('name')}={x.get('value')}" for x in metadata if x.get("affects_gss")
            )[:250]
            feat["details"] = "; ".join(row.get("details") or [])[:250]
            feat["uncert_m"] = self._to_float(uncertainty.get("coordinate_uncertainty_m") or uncertainty.get("uncertainty_m"))
            feat["gbif_unc_m"] = self._to_float(uncertainty.get("coordinate_uncertainty_m"))
            feat["model_r_m"] = self._to_float(uncertainty.get("model_radius_m"))
            feat["geo_rad_m"] = self._to_float(uncertainty.get("geographic_radial_m"))
            feat["grid_err_m"] = self._to_float(uncertainty.get("grid_error_m"))
            feat["confidence"] = str(uncertainty.get("model_confidence_class") or uncertainty.get("confidence") or "")
            feat["mci"] = self._to_float(uncertainty.get("model_confidence_index"))
            feat["mci_class"] = str(uncertainty.get("model_confidence_class") or "")[:30]
            feat["mci_reason"] = "; ".join(uncertainty.get("model_confidence_reasons") or [])[:250]
            feat["cand_spread"] = self._to_float(uncertainty.get("candidate_spread_m"))
            feat["data_comp"] = self._to_float(uncertainty.get("data_completeness"))
            feat["eco_unique"] = self._to_float(uncertainty.get("ecological_uniqueness"))
            feat["equiv_cand"] = int(uncertainty.get("equivalent_candidates") or 0)
            feat["score_gap"] = self._to_float(uncertainty.get("score_gap"))
            feat["ssi"] = self._to_float(uncertainty.get("solution_stability_index"))
            feat["ssi_class"] = str(uncertainty.get("solution_stability_class") or "")[:30]
            feat["ssi_reason"] = "; ".join(uncertainty.get("solution_stability_reasons") or [])[:250]
            feat["loo_dist_m"] = self._to_float(uncertainty.get("leave_one_out_distance_m"))
            feat["ssi_spread"] = self._to_float(uncertainty.get("plausible_alternative_spread_m"))
            feat["ssi_alt_n"] = int(uncertainty.get("plausible_alternative_count") or 0)
            feat["ssi_cl_n"] = int(uncertainty.get("ssi_cluster_count") or 0)
            feat["ssi_main_n"] = int(uncertainty.get("ssi_main_cluster_count") or 0)
            feat["ssi_share"] = self._to_float(uncertainty.get("ssi_main_cluster_share"))
            feat["ssi_rad_m"] = self._to_float(uncertainty.get("ssi_main_cluster_radius_m"))
            feat["ssi_med_m"] = self._to_float(uncertainty.get("ssi_main_cluster_median_m"))
            feat["ssi_eps_m"] = self._to_float(uncertainty.get("ssi_cluster_eps_m"))
            feat["ssi_near_m"] = self._to_float(uncertainty.get("ssi_nearest_competing_cluster_m"))
            feat["gbif_lon"] = self._to_float(uncertainty.get("corrected_center_lon"))
            feat["gbif_lat"] = self._to_float(uncertainty.get("corrected_center_lat"))
            feat["gbif_ctr_m"] = str(uncertainty.get("corrected_center_method") or "")[:120]
            feat["gbif_ctr_s"] = str(uncertainty.get("corrected_center_source") or "")[:120]
            feat["decimalLatitude"] = self._to_float(uncertainty.get("decimalLatitude"))
            feat["decimalLongitude"] = self._to_float(uncertainty.get("decimalLongitude"))
            feat["geodeticDatum"] = str(uncertainty.get("geodeticDatum") or "")[:80]
            feat["coordinateUncertaintyInMeters"] = self._to_float(uncertainty.get("coordinateUncertaintyInMeters"))
            feat["coordinatePrecision"] = self._to_float(uncertainty.get("coordinatePrecision"))
            feat["pointRadiusSpatialFit"] = self._to_float(uncertainty.get("pointRadiusSpatialFit"))
            feat["footprintWKT"] = str(uncertainty.get("footprintWKT") or "")[:10000]
            feat["footprintSRS"] = str(uncertainty.get("footprintSRS") or "")[:80]
            feat["georeferencedBy"] = str(uncertainty.get("georeferencedBy") or "")[:250]
            feat["georeferencedDate"] = str(uncertainty.get("georeferencedDate") or "")[:40]
            feat["georeferenceProtocol"] = str(uncertainty.get("georeferenceProtocol") or "")[:250]
            feat["georeferenceSources"] = str(uncertainty.get("georeferenceSources") or "")[:1000]
            feat["georeferenceVerificationStatus"] = str(uncertainty.get("georeferenceVerificationStatus") or "")[:120]
            feat["georeferenceRemarks"] = str(uncertainty.get("georeferenceRemarks") or "")[:4000]
            feat["gbif_dwc_complete"] = "yes" if uncertainty.get("gbif_dwc_complete") else "no"
            feat["loc_type"] = str(uncertainty.get("locality_type") or "unknown")[:60]
            feat["geom_type"] = str(uncertainty.get("geometry_type") or "unknown")[:60]
            feat["loc_cls_cf"] = self._to_float(uncertainty.get("classification_confidence"))
            feat["loc_cls_r"] = str(uncertainty.get("classification_reason") or "")[:250]
            feat["loc_ref_t"] = str(uncertainty.get("primary_reference_type") or "")[:80]
            feat["loc_ref_n"] = str(uncertainty.get("primary_reference_name") or "")[:160]
            feat["plaus_alt"] = str(row.get("plausible_alt") or env.get("plausible_alt") or "no")
            feat["alt_reason"] = str(row.get("alt_reason") or env.get("alt_reason") or "")[:250]
            feat["score_dlt"] = self._to_float(row.get("score_delta") if row.get("score_delta") is not None else env.get("score_delta"))
            feat["aspect_sc"] = self._to_float(env.get("aspect_bonus"))
            feat["aspect_r"] = str(env.get("aspect_reason") or "")[:200]
            feat["aspect_deg"] = self._to_float(env.get("aspect"))
            feat["aspect_dir"] = str(env.get("aspect_class") or "")
            feat["record_aspect"] = str(env.get("record_aspect") or "")
            feat["aspect_diff_deg"] = self._to_float(env.get("aspect_difference_deg"))
            feat["aspect_score"] = self._to_float(env.get("aspect_bonus"))
            feat["eco_exposure"] = str(env.get("exposure") or "")
            feat["norm_score"] = official_score
            feat["norm_w"] = str(env.get("norm_weights") or "")[:250]
            feat["score_comp"] = str(env.get("score_components") or "")[:250]
            feat["alt_score"] = self._to_float(env.get("altitude_score"))
            feat["sub_score"] = self._to_float(env.get("substrate_score"))
            feat["lith_score"] = self._to_float(env.get("lithology_score"))
            feat["italic_score"] = self._to_float(env.get("italic_score"))
            feat["access_score"] = self._to_float(env.get("accessibility_score_norm"))
            feat["slope_score"] = self._to_float(env.get("slope_score"))
            feat["geo_macro"] = self._to_float(env.get("geographic_score"))
            feat["terrain_m"] = self._to_float(env.get("terrain_macro_score"))
            feat["env_macro"] = self._to_float(env.get("environmental_score"))
            feat["access_m"] = self._to_float(env.get("accessibility_macro_score"))
            feat["score_arch"] = str(env.get("scoring_architecture") or "")[:40]
            feat["env_group"] = str(env.get("environmental_group") or "")[:30]
            feat["env_sub_s"] = self._to_float(env.get("environmental_substrate_score"))
            feat["env_lith_s"] = self._to_float(env.get("environmental_lithology_score"))
            feat["env_ph_s"] = self._to_float(env.get("environmental_ph_score"))
            feat["env_hab_s"] = self._to_float(env.get("environmental_habitat_score"))
            feat["env_tree_s"] = self._to_float(env.get("environmental_tree_score"))
            feat["env_parts"] = str(env.get("environmental_components") or "")[:220]
            feat["env_w"] = str(env.get("environmental_weights") or "")[:220]
            feats.append(feat)

        provider.addFeatures(feats)
        layer.updateExtents()
        self._apply_clear_candidate_style(layer)
        if add_to_project:
            QgsProject.instance().addMapLayer(layer)
        return layer

    def _apply_clear_candidate_style(self, layer):
        """Simbologia chiara e leggibile per i candidati, con dimensione per rank."""
        try:
            root = QgsRuleBasedRenderer.Rule(None)
            # Dimensioni volutamente compatte per lasciare leggibile la basemap.
            # I valori sono in millimetri (circa 8, 7, 6 e 4 px a 96 dpi).
            # Il colore dipende esclusivamente dal rank. In precedenza le regole
            # richiedevano anche grid_lvl <> 'global': quando il raffinamento non
            # veniva generato, tutti i candidati rimanevano global e apparivano
            # quindi con il solo simbolo grigio della griglia globale.
            rules = [
                # Il Rank 1 finale è sempre verde e cerchiato in rosso.
                ("\"rank\" = 1", 'Rank 1 finale', '124,255,107,255', '#ff1744', 0.75, 2.8),
                ("\"rank\" >= 2 AND \"rank\" <= 10", 'Rank 2-10', '255,241,118,255', '#555555', 0.30, 1.9),
                ("\"rank\" >= 11 AND \"rank\" <= 50", 'Rank 11-50', '255,183,77,255', '#555555', 0.30, 1.6),
                ("\"rank\" > 50", 'Rank >50', '255,255,255,210', '#555555', 0.30, 1.1),
            ]
            for expression, label, fill, outline, outline_width, size in rules:
                symbol = QgsMarkerSymbol.createSimple({
                    'name': 'circle',
                    'color': fill,
                    'outline_color': outline,
                    'outline_width': str(outline_width),
                    'size': str(size),
                    'size_unit': 'MM',
                })
                rule = QgsRuleBasedRenderer.Rule(symbol, 0, 0, expression, label)
                root.appendChild(rule)
            layer.setRenderer(QgsRuleBasedRenderer(root))
            try:
                layer.setDisplayExpression(
                    "concat('Rank ', to_string(\"rank\"), ' — ', coalesce(\"grid_lvl\", ''))"
                )
            except Exception:
                pass
            layer.triggerRepaint()
        except Exception:
            pass

    def _constraints_to_text(self, constraints):
        constraints = constraints or {}
        parts = []
        for k in ["rock_type", "substrate", "humidity", "slope", "altitude_min", "altitude_max"]:
            if constraints.get(k) not in [None, "", [], {}]:
                parts.append(f"{k}={constraints.get(k)}")
        habitat = constraints.get("habitat")
        if habitat:
            if isinstance(habitat, (list, tuple)):
                parts.append("habitat=" + ",".join(str(x) for x in habitat))
            else:
                parts.append("habitat=" + str(habitat))
        return "; ".join(parts)

    def _distance_m(self, pt1_wgs84, pt2_wgs84):
        if not pt1_wgs84 or not pt2_wgs84:
            return None
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        midpoint = QgsPointXY(
            (float(pt1_wgs84.x()) + float(pt2_wgs84.x())) / 2.0,
            (float(pt1_wgs84.y()) + float(pt2_wgs84.y())) / 2.0,
        )
        metric = _shared_local_metric_crs(midpoint)
        g1 = self._transform_geometry(QgsGeometry.fromPointXY(pt1_wgs84), wgs84, metric)
        g2 = self._transform_geometry(QgsGeometry.fromPointXY(pt2_wgs84), wgs84, metric)
        if not g1 or not g2:
            return None
        return g1.distance(g2)

    def _altitude_delta(self, altitude, record_altitude):
        try:
            if altitude in [None, "", [], {}] or record_altitude in [None, "", [], {}]:
                return None
            return abs(float(altitude) - float(record_altitude))
        except Exception:
            return None

    def _clean_text(self, value):
        try:
            if value in [None, "", [], {}]:
                return ""
            return str(value).strip().lower()
        except Exception:
            return ""

    def _to_float(self, value):
        return _shared_to_float(value)

    def _transform_geometry(self, geom, src_crs, dst_crs):
        if geom is None or geom.isEmpty():
            return geom
        if not src_crs.isValid() or not dst_crs.isValid() or src_crs == dst_crs:
            return QgsGeometry(geom)
        transformed = QgsGeometry(geom)
        transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
        transformed.transform(transform)
        return transformed
