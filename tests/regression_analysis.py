"""Score corrections and exact performance invariants (QGIS Python, -B).

Synthetic, local fixtures only. Scientific accuracy requires independent
known-coordinate records; these checks validate the implemented rules.
"""

import copy
import importlib.util
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from osgeo import gdal, osr
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsDistanceArea, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsRasterLayer, QgsVectorLayer,
)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("geolichen", ROOT / "__init__.py",
                                             submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules["geolichen"] = package
spec.loader.exec_module(package)

from geolichen.services._shared_geo_utils import local_metric_crs
from geolichen.services.accessibility_engine import AccessibilityEngine
from geolichen.services.ecology_engine import EcologyEngine
from geolichen.services.environmental_evidence_service import EnvironmentalEvidenceService
from geolichen.services.habitat_suitability_service import HabitatSuitabilityService
from geolichen.services.model_uncertainty_service import ModelUncertaintyService
from geolichen.services.scoring_model import ScoringModel
from geolichen.services.solution_stability_service import SolutionStabilityService


class FullStability(SolutionStabilityService):
    """Independent all-pairs reference; no compact-cluster shortcut."""

    def _dbscan(self, nodes, distance_func, eps_m, min_samples=2):
        neighbours = []
        for node in nodes:
            near = []
            for j, other in enumerate(nodes):
                distance = distance_func(node["point"], other["point"])
                if distance is not None and distance <= eps_m:
                    near.append(j)
            neighbours.append(near)
        labels = [None] * len(nodes)
        cluster = 0
        for i in range(len(nodes)):
            if labels[i] is not None:
                continue
            if len(neighbours[i]) < min_samples:
                labels[i] = -1
                continue
            pending = [i]
            while pending:
                index = pending.pop()
                if labels[index] is not None and labels[index] != -1:
                    continue
                labels[index] = cluster
                if len(neighbours[index]) >= min_samples:
                    pending.extend(j for j in neighbours[index] if labels[j] in (None, -1))
            cluster += 1
        return labels


class UnoptimizedHabitat(HabitatSuitabilityService):
    """Same corrected model, with repeated work restored for comparison."""

    def _build_env_for_point(self, *args, **kwargs):
        kwargs.pop("_altitude_profile", None)
        kwargs.pop("_forest_geometry_cache", None)
        return super()._build_env_for_point(*args, **kwargs)

    def _dem_neighbour_values(self, *args, **kwargs):
        first = super()._dem_neighbour_values(*args, **kwargs)
        super()._dem_neighbour_values(*args, **kwargs)
        return first


class ScoreCorrections(unittest.TestCase):
    def setUp(self):
        self.service = HabitatSuitabilityService(EcologyEngine())
        self.model = ScoringModel()

    def test_accessibility_does_not_borrow_locality_evidence(self):
        engine = AccessibilityEngine()
        for context in ("pass", "trail", "summit", "valley", "locality"):
            near = engine.final_accessibility_score(100, 0, {"type": context})
            far = engine.final_accessibility_score(100, 2000, {"type": context})
            self.assertEqual(near["accessibility_score"], far["accessibility_score"])
            self.assertEqual(near["context_weight"], 0.0)
            self.assertEqual(near["trail_weight"], 1.0)
            self.assertEqual(engine.final_accessibility_score(None, 0, {"type": context})["accessibility_score"], 50)

    def test_locality_distance_only_changes_geography_in_gss(self):
        engine = AccessibilityEngine()
        near = engine.final_accessibility_score(None, 0, {"type": "pass"})
        far = engine.final_accessibility_score(None, 2000, {"type": "pass"})
        a, b = self.model.final_score(near), self.model.final_score(far)
        self.assertAlmostEqual(a["score"] - b["score"],
                               (near["context_score"] - far["context_score"]) * 0.25)

    def test_summit_type_aliases_share_geographic_rules(self):
        engine = AccessibilityEngine()
        scores = [engine.context_confidence(150, {"type": name})
                  for name in ("summit", "summit_peak", "peak", "cima")]
        self.assertEqual(scores, [90.0] * 4)

    def test_observed_low_accessibility_is_not_clipped_to_missing_neutral(self):
        for distance, expected in ((0, 100), (100, 50), (200, 30), (300, 10), (None, 50)):
            env = AccessibilityEngine().final_accessibility_score(distance)
            self.assertEqual(self.model.macro_scores(env)["accessibility"], expected)
        self.assertEqual(self.model.accessibility_score({"accessibility_score": 0.0}), 0)

    def test_zero_distances_win_ties_and_missing_values_do_not(self):
        for field in ("context_dist_m", "trail_dist_m", "distance_to_center_m"):
            def row(value):
                return {"score": 70, "env": {field: value}, field: value}
            self.assertGreater(self.service._rank_key(row(0)), self.service._rank_key(row(1)))
            self.assertGreater(self.service._rank_key(row(1)), self.service._rank_key(row(None)))

    def test_legacy_bonuses_cannot_break_a_gss_tie(self):
        row = {"id": 1, "score": 70, "env": {"final_score": 70}}
        other = copy.deepcopy(row)
        other["raw_score"] = 100
        other["env"].update(ecological_score=100, litho_soil_ph_score=20, aspect_bonus=5, slope=80)
        self.assertEqual(self.service._rank_key(row), self.service._rank_key(other))

    def test_altitude_precedes_secondary_distance_ties(self):
        near_alt = {"score": 70, "alt_delta_m": 0, "env": {"record_altitude": 1500, "context_dist_m": 100}}
        near_place = {"score": 70, "alt_delta_m": 10, "env": {"record_altitude": 1500, "context_dist_m": 0}}
        self.assertGreater(self.service._rank_key(near_alt), self.service._rank_key(near_place))

    def test_single_altitude_is_gradual_and_hard_filter_is_preserved(self):
        values = []
        for delta in (0, 50, 100):
            env = {"altitude": 1500 + delta, "record_altitude": 1500, "altitude_tolerance_m": 100}
            values.append(self.model.altitude_score(env))
            self.assertFalse(self.service._strict_record_altitude_decision_v283(env)["exclude"])
        self.assertEqual(values, [100, 75, 50])
        self.assertTrue(self.service._strict_record_altitude_decision_v283(
            {"altitude": 1601, "record_altitude": 1500, "altitude_tolerance_m": 100})["exclude"])

    def test_range_altitude_has_no_midpoint_preference(self):
        for altitude in (1400, 1450, 1500, 1600):
            env = {"altitude": altitude, "record_altitude_min": 1400, "record_altitude_max": 1600,
                   "altitude_tolerance_m": 10}
            strict = self.service._strict_record_altitude_decision_v283(env)
            self.assertEqual(strict["delta_m"], 0)
            self.assertEqual(self.model.altitude_score(env), 100)
        env["altitude"] = 1610
        self.assertEqual(self.model.altitude_score(env), 50)
        self.assertFalse(self.service._strict_record_altitude_decision_v283(env)["exclude"])
        env["altitude"] = 1611
        self.assertTrue(self.service._strict_record_altitude_decision_v283(env)["exclude"])

    def test_flat_dem_has_no_aspect_or_direction_bonus(self):
        flat = (1500, 1500, 1500, 1500, 10)
        self.assertEqual(self.service._slope_from_neighbours(flat), 0)
        self.assertIsNone(self.service._aspect_from_neighbours(flat))
        for direction in ("N", "S"):
            env = self.service._apply_record_aspect_preference({"aspect": None, "slope": 0},
                                                               {"record_aspect": direction})
            self.assertEqual(env["aspect_bonus"], 0)
            self.assertIsNone(self.model.component_scores(env)["aspect"])

    def test_nonflat_dem_keeps_original_direction_and_slope(self):
        for values in ((1500, 1520, 1500, 1500, 10), (1500, 1500, 1520, 1500, 10)):
            left, right, down, up, step = values
            dx, dy = (right-left)/(2*step), (up-down)/(2*step)
            self.assertEqual(self.service._aspect_from_neighbours(values),
                             (180 + math.degrees(math.atan2(dx, dy))) % 360)
            self.assertAlmostEqual(self.service._slope_from_neighbours(values),
                                   math.degrees(math.atan(math.sqrt(dx*dx + dy*dy))))

    def test_trail_distance_does_not_modify_slope_score(self):
        for group in ("rock", "soil", "epiphyte", "moss", "unknown"):
            a = self.service._slope_penalty_v291({"slope": 75, "trail_dist_m": 0}, {"substrate_group": group})
            b = self.service._slope_penalty_v291({"slope": 75, "trail_dist_m": 200}, {"substrate_group": group})
            self.assertEqual(a, b)

    def test_host_mismatch_does_not_receive_a_positive_cover_bonus(self):
        evaluator = EnvironmentalEvidenceService()
        env = {"observed_tree": "abete", "expected_tree": "quercia", "forest_category": "conifere"}
        precise = evaluator._tree(env, "epiphyte")
        self.assertLess(precise["score"], 50)
        env["tree_observation_source"] = "forest_polygon"
        mapped = evaluator._tree(env, "epiphyte")
        self.assertEqual(mapped["score"], 50)
        env["observed_tree"] = "quercia"
        self.assertEqual(evaluator._tree(env, "epiphyte")["quality"], 0.75)

    def test_environment_is_aggregated_once(self):
        with patch.object(self.model, "_environmental_components", wraps=self.model._environmental_components) as evaluate:
            self.model.apply_to_env({"substrate_group": "rock"})
            self.assertEqual(evaluate.call_count, 1)


class SpatialAnalysis(unittest.TestCase):
    @staticmethod
    def comparable(value):
        if isinstance(value, QgsGeometry):
            return value.asWkt()
        if isinstance(value, dict):
            return {key: SpatialAnalysis.comparable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [SpatialAnalysis.comparable(item) for item in value]
        return value

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="geolichen_analysis_")
        self.addCleanup(self.temp.cleanup)
        self.point = QgsPointXY(10.2, 46.05)
        self.wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        self.metric = local_metric_crs(self.point)
        self.to_metric = QgsCoordinateTransform(self.wgs, self.metric, QgsProject.instance())
        self.to_wgs = QgsCoordinateTransform(self.metric, self.wgs, QgsProject.instance())
        self.center = self.to_metric.transform(self.point)
        self.buffer = self.make_buffer(150)
        self.profile = {"substrate_group": "rock", "rock_type": "siliceo"}
        self.service = HabitatSuitabilityService(EcologyEngine())

    def xy(self, x, y):
        return self.to_wgs.transform(QgsPointXY(self.center.x()+x, self.center.y()+y))

    def make_buffer(self, radius):
        geom = QgsGeometry.fromPointXY(self.center).buffer(radius, 48)
        geom.transform(self.to_wgs)
        return geom

    def run_analysis(self, service=None, **kwargs):
        options = dict(_candidate_points=[self.point, self.xy(1, 0)], _adaptive_refinement=False,
                       create_layer=False, context_point=self.point, context={"type": "pass"})
        options.update(kwargs)
        return (service or self.service).find_best_point(self.buffer, self.profile, **options)

    def polygon(self, name, fields, attributes):
        layer = QgsVectorLayer("Polygon?crs=EPSG:4326" + fields, name, "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(self.make_buffer(250))
        feature.setAttributes(attributes)
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        return layer

    def dem(self, name="dem", nodata=False):
        path = str(Path(self.temp.name) / (name + ".tif"))
        n = 128
        values = np.full((n, n), -9999 if nodata else 1500, dtype=np.float32)
        if not nodata:
            values += np.indices((n, n))[1] * 0.5
        ds = gdal.GetDriverByName("GTiff").Create(path, n, n, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((self.center.x()-320, 5, 0, self.center.y()+320, 0, -5))
        projection = osr.SpatialReference()
        projection.ImportFromEPSG(int(self.metric.authid().split(":")[1]))
        ds.SetProjection(projection.ExportToWkt())
        ds.GetRasterBand(1).SetNoDataValue(-9999)
        ds.GetRasterBand(1).WriteArray(values)
        ds = None
        return QgsRasterLayer(path, name)

    def test_context_is_used_and_does_not_leak_between_records(self):
        supplied = {"type": "summit_peak", "reference_name": "Test"}
        result = self.run_analysis(context=supplied)
        self.assertEqual(result["context"]["type"], "summit")
        self.assertEqual(result["best_env"]["context_type"], "summit")
        self.assertEqual(supplied["type"], "summit_peak")
        fresh = self.run_analysis(context=None)
        self.assertEqual(fresh["context"]["type"], "locality")

    def test_zero_distance_point_is_rank_one_in_real_pipeline(self):
        result = self.run_analysis()
        self.assertEqual(result["best_point"], self.point)
        self.assertEqual(result["best_env"]["context_dist_m"], 0)

    def test_soil_chemistry_alone_does_not_declare_ground_support(self):
        soil = self.polygon("pH", "&field=PH_H2O:double", [5.2])
        rock = self.polygon("Geology", "&field=rock:string", ["siliceo"])
        bare = self.run_analysis(geology_layer=rock, geology_field="rock")
        with_ph = self.run_analysis(geology_layer=rock, geology_field="rock", soil_layer=soil, soil_field="PH_H2O")
        self.assertEqual(bare["best_score"], with_ph["best_score"])
        self.assertIsNone(with_ph["best_env"]["substrate"])
        self.assertIsNone(with_ph["best_env"]["environmental_ph_score"])

    def test_explicit_ground_support_survives_a_separate_numeric_ph_field(self):
        soil = self.polygon("Soil", "&field=support:string&field=PH_H2O:double", ["roccia", 5.2])
        env = self.service._build_env_for_point(self.point, soil_layer=soil, soil_field="support")
        self.assertEqual(env["substrate"], "roccia")
        self.assertEqual(env["soil_ph_num"], 5.2)

    def test_single_dem_samples_five_values_not_nine(self):
        dem = self.dem()
        with patch.object(self.service, "_sample_raster_value", wraps=self.service._sample_raster_value) as sample:
            env = self.service._build_env_for_point(self.point, dem_layer=dem)
            self.assertEqual(sample.call_count, 5)
        self.assertIsNotNone(env["slope"])
        self.assertIsNotNone(env["aspect"])

    def test_multidem_fallback_keeps_priority_and_diagnostics(self):
        missing, valid = self.dem("missing", True), self.dem("valid")
        with patch.object(self.service, "_sample_raster_value", wraps=self.service._sample_raster_value) as sample:
            env = self.service._build_env_for_point(self.point, dem_layers=[missing, valid])
            self.assertEqual(sample.call_count, 6)
        self.assertEqual(env["dem_priority"], 2)
        self.assertTrue(env["dem_fallback_used"])
        self.assertEqual(env["dem_valid_count"], 1)

    def test_altitude_rejection_skips_vectors_and_dem_neighbours(self):
        dem = self.dem()
        with patch.object(self.service, "_feature_at_point") as features, patch.object(
                self.service, "_dem_neighbour_values") as neighbours:
            env = self.service._build_env_for_point(self.point, dem_layer=dem,
                                                   _altitude_profile={"record_altitude": 2000})
            self.assertTrue(env["_excluded_by_record_altitude"])
            features.assert_not_called()
            neighbours.assert_not_called()

    def test_optimized_and_complete_pipeline_outputs_match(self):
        dem = self.dem()
        soil = self.polygon("Soil", "&field=PH_H2O:double", [5.2])
        forest = self.polygon("Forest", "&field=tree:string", ["abete"])
        points = [self.xy(x, y) for x in range(-60, 61, 20) for y in range(-60, 61, 20)]
        params = dict(dem_layer=dem, soil_layer=soil, soil_field="PH_H2O", trees_layer=forest,
                      trees_field="tree", _candidate_points=points)
        reference = UnoptimizedHabitat(EcologyEngine())
        reference.uncertainty_service.stability_service = FullStability()
        a = self.run_analysis(**params)
        b = self.run_analysis(service=reference, **params)
        self.assertEqual(a["features"], b["features"])
        self.assertEqual(a["best_point"], b["best_point"])
        self.assertEqual(self.comparable(a["uncertainty"]), self.comparable(b["uncertainty"]))
        # Compare actual output attributes and raster pixels too.
        def outputs(service, result):
            layer = service._create_points_layer(result["features"], uncertainty=result["uncertainty"],
                                                 add_to_project=False)
            attrs = [feature.attributes() for feature in layer.getFeatures()]
            raster = service._create_heatmap_layer(result["global_features"], uncertainty=result["uncertainty"],
                                                   grid_step_m=20, search_extent=self.buffer)
            pixels = gdal.Open(raster.source()).ReadAsArray()
            QgsProject.instance().removeMapLayer(raster.id())
            return attrs, pixels
        attrs_a, pixels_a = outputs(self.service, a)
        attrs_b, pixels_b = outputs(reference, b)
        self.assertEqual(attrs_a, attrs_b)
        np.testing.assert_array_equal(pixels_a, pixels_b)

    def test_refinement_computes_uncertainty_only_for_final_grid(self):
        with patch.object(self.service.uncertainty_service, "estimate", return_value={}) as uncertainty:
            result = self.run_analysis(_candidate_points=[self.point, self.xy(10, 0)],
                                       _adaptive_refinement=True, grid_step_m=30)
        self.assertTrue(result["adaptive_refinement"]["applied"])
        self.assertEqual(uncertainty.call_count, 1)
        self.assertEqual(result["context"]["type"], "pass")
        self.assertEqual(sum(row["rank"] == 1 for row in result["display_features"]), 1)

    def test_range_reaches_official_terrain_and_ranking(self):
        self.profile.update(record_altitude_min=1500, record_altitude_max=1600)
        result = self.run_analysis(dem_layer=self.dem())
        for row in result["features"]:
            self.assertEqual(row["alt_delta_m"], 0)
            self.assertEqual(self.service.scoring_model.altitude_score(row["env"]), 100)

    def test_early_filter_and_complete_filter_keep_identical_candidates(self):
        self.profile["record_altitude"] = 1525
        dem = self.dem()
        points = [self.xy(x, 0) for x in range(-100, 101, 10)]
        params = dict(dem_layer=dem, _candidate_points=points)
        fast = self.run_analysis(**params)
        full = self.run_analysis(service=UnoptimizedHabitat(EcologyEngine()), **params)
        self.assertGreater(fast["excluded_by_altitude"], 0)
        self.assertEqual(fast["excluded_by_altitude"], full["excluded_by_altitude"])
        self.assertEqual(fast["features"], full["features"])

    def test_record_invariants_are_computed_once_per_grid(self):
        with patch.object(self.service.ecology_engine, "compute_constraints",
                          wraps=self.service.ecology_engine.compute_constraints) as constraints, patch.object(
                self.service, "_build_ecological_context", wraps=self.service._build_ecological_context) as context:
            self.run_analysis(_candidate_points=[self.xy(x, 0) for x in range(10)])
            self.assertEqual(constraints.call_count, 1)
            self.assertEqual(context.call_count, 1)

    def test_forest_geometry_cache_is_not_reused_after_layer_edits(self):
        forest = self.polygon("Forest", "&field=tree:string", ["abete"])
        first = self.run_analysis(trees_layer=forest, trees_field="tree")
        self.assertEqual(first["best_env"]["forest_dist_m"], 0)
        feature = next(forest.getFeatures())
        moved = QgsGeometry(feature.geometry())
        moved.translate(1, 0)
        forest.dataProvider().changeGeometryValues({feature.id(): moved})
        forest.updateExtents()
        second = self.run_analysis(trees_layer=forest, trees_field="tree")
        self.assertIsNone(second["best_env"]["forest_dist_m"])

    def test_geodesic_reuse_matches_fresh_measurement(self):
        model = ModelUncertaintyService()
        reuse = model.make_distance_func()
        for point in (self.point, self.xy(100, 200), QgsPointXY(-179.9, 0), QgsPointXY(10, 89)):
            self.assertEqual(reuse(self.point, point), model.distance_m(self.point, point))
        self.assertIsNone(reuse(None, self.point))

    def test_uncertainty_empty_candidates_has_safe_fallback(self):
        result = ModelUncertaintyService().estimate(self.buffer, [], self.point, 0)
        self.assertGreater(result["model_radius_m"], 0)
        self.assertEqual(result["compatible_points"], 0)

    def test_r55_s65_threshold_and_ui_label_agree(self):
        rows = [{"point": self.point, "score": 100}, {"point": self.xy(20, 0), "score": 68}]
        result = ModelUncertaintyService().estimate(self.buffer, rows, self.point, 100)
        self.assertEqual(result["compatible_points"], 2)
        self.assertIn("S65", result["model_method"])
        text = (ROOT / "gui" / "confirm_point_dialog.py").read_text()
        self.assertIn("R55–S65", text)
        self.assertNotIn("R55–S70", text)

    def test_compact_ssi_uses_linear_number_of_distances(self):
        rows = [{"point": self.xy(i % 40, i // 40), "score": 80} for i in range(800)]
        distance = ModelUncertaintyService().make_distance_func()
        with patch.object(ModelUncertaintyService, "distance_m", side_effect=distance) as counted:
            fast = SolutionStabilityService().evaluate(80, rows, self.point, counted, 100, 10)
            self.assertLessEqual(counted.call_count, 800)
        full = FullStability().evaluate(80, rows, self.point, distance, 100, 10)
        self.assertEqual(fast, full)

    def test_compact_dispersed_and_multicluster_ssi_match_full_algorithm(self):
        rng = random.Random(20261023)
        distance = ModelUncertaintyService().make_distance_func()
        for case in range(60):
            scale = 20 if case % 2 == 0 else 500
            rows = [{"point": self.xy(rng.uniform(-scale, scale), rng.uniform(-scale, scale)),
                     "score": rng.choice((50, 78, 79, 80, 81))} for _ in range(30)]
            fast = SolutionStabilityService().evaluate(80, rows, self.point, distance, 100, 10)
            full = FullStability().evaluate(80, rows, self.point, distance, 100, 10)
            self.assertEqual(fast, full, case)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="geolichen_analysis_profile_") as profile_dir:
        app = QgsApplication([], False, profile_dir)
        app.initQgis()
        unittest.main(verbosity=2)
