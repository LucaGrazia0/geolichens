"""Evidence regression checks; run with the QGIS Python interpreter (-B).

Synthetic cases verify implementation invariants, not ecological accuracy.
No specimen datasets, external services or user QGIS profile are used.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("geolichen", ROOT / "__init__.py",
                                             submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules["geolichen"] = package
spec.loader.exec_module(package)

from geolichen.services.ecology_engine import EcologyEngine
from geolichen.services.environmental_evidence_service import EnvironmentalEvidenceService
from geolichen.services.explainability_service import ExplainabilityService
from geolichen.services.model_confidence_service import ModelConfidenceService
from geolichen.services.scoring_model import ScoringModel


class EvidenceRegression(unittest.TestCase):
    def setUp(self):
        self.model = ScoringModel()
        self.engine = EcologyEngine()
        self.evaluator = EnvironmentalEvidenceService()

    def scored(self, group="rock", profile=None, env=None):
        profile = dict(profile or {}, substrate_group=group)
        env = dict(env or {}, substrate_group=group)
        result = self.engine.compute_score(profile, env)
        env["constraints"] = result["constraints"]
        env["ecological_evidence"] = result["environmental_evidence"]
        return self.model.apply_to_env(env)

    def test_no_evidence_has_no_positive_bonus(self):
        self.assertEqual(self.model.final_score({})["score"], 50.0)
        for group in ("rock", "soil", "moss", "epiphyte", "lignicolous", "unknown"):
            with self.subTest(group=group):
                env = self.scored(group)
                self.assertEqual(env["environmental_score"], 50.0)
                self.assertEqual(env["environmental_available_weight"], 0.0)
                self.assertEqual(env["environmental_quality_coverage"], 0.0)

    def test_default_zero_and_diagnostic_text_are_not_observations(self):
        env = self.scored(env={"ph_score": 0.0, "litho_soil_ph_score": 0.0,
                               "tree_match_reason": "non applicabile", "tree_match_score": 0.0})
        self.assertIsNone(env["environmental_ph_score"])
        self.assertIsNone(env["environmental_tree_score"])
        self.assertEqual(env["environmental_available_weight"], 0.0)

    def test_requirements_do_not_confirm_missing_observations(self):
        env = self.scored("epiphyte", {"tree_type": "quercia", "habitat": ["bosco"]},
                          {"expected_tree": "quercia", "tree_match_reason": "preferenza presente"})
        self.assertIsNone(env["environmental_tree_score"])
        self.assertIsNone(env["environmental_habitat_score"])
        completeness, names = ModelConfidenceService()._data_completeness({"env": env})
        self.assertEqual(completeness, 0.0)
        self.assertNotIn("supporto arboreo/contesto forestale", names)

    def test_missing_slope_and_record_aspect_are_not_perfect_scores(self):
        components = self.model.component_scores({"slope_penalty": 0.0, "aspect_bonus": 0.0})
        self.assertIsNone(components["slope"])
        self.assertIsNone(components["aspect"])
        self.assertIsNone(components["altitude"])
        self.assertEqual(self.model.terrain_score({"altitude": 2000}), 50.0)
        self.assertEqual(self.model.terrain_score({"alt_delta_m": 0.0}), 50.0 + 50.0 * 20.0 / 30.0)

    def test_numeric_zero_is_a_real_measurement_when_available(self):
        self.assertEqual(self.model.component_scores({"slope": 0.0, "slope_penalty": 0.0})["slope"], 100.0)
        self.assertEqual(self.model.component_scores({"aspect": 0.0, "record_aspect": "N", "aspect_bonus": 5.0})["aspect"], 100.0)

    def test_generic_forest_does_not_reward_ground_groups(self):
        for group in ("rock", "soil", "moss", "unknown"):
            bare = self.scored(group)
            forest = self.scored(group, env={"forest_category": "bosco", "observed_tree": "quercia",
                                            "tree_match_score": 20.0, "forest_dist_m": 0.0})
            self.assertEqual(bare["environmental_score"], forest["environmental_score"])
            self.assertEqual(forest["environmental_evidence_status"]["tree_forest"], "non applicabile")

    def test_forest_habitat_is_conditional_on_requirements(self):
        observed = {"forest_category": "bosco", "forest_dist_m": 0.0}
        forest = self.scored(profile={"habitat": ["bosco"]}, env=observed)
        open_habitat = self.scored(profile={"habitat": ["aperto"]}, env=observed)
        self.assertGreater(forest["environmental_score"], 50.0)
        self.assertLess(open_habitat["environmental_score"], 50.0)
        self.assertEqual(forest["environmental_qualities"]["habitat"], 0.5)

    def test_habitat_no_longer_assumes_openness_or_dryness(self):
        env = self.scored(profile={"habitat": ["aperto", "secco", "rupicolo", "alpino"]},
                          env={"altitude": 2500.0, "slope": 55.0, "rock_type": "siliceo"})
        self.assertIsNone(env["environmental_habitat_score"])
        self.assertIsNone(env["ecological_evidence"]["habitat"]["score"])

    def test_habitat_structured_result_reaches_official_score(self):
        env = self.scored(profile={"habitat": ["umido"]}, env={"humidity": "alta"})
        self.assertEqual(env["environmental_habitat_score"], 100.0)
        self.assertGreater(env["environmental_score"], 50.0)
        self.assertGreater(env["final_score"], 50.0)
        original = self.model.final_score(env)
        env["details"] = ["substrato incompatibile", "coerenza habitat ITALIC/GIS (-999)"]
        self.assertEqual(original, self.model.final_score(env))

    def test_contradictory_habitat_ranges_are_not_accumulated_bonuses(self):
        env = self.scored(profile={"habitat": ["umido", "secco", "bosco", "aperto"]},
                          env={"humidity": "alta", "forest_dist_m": 0.0})
        self.assertEqual(env["environmental_habitat_score"], 50.0)
        self.assertEqual(env["environmental_score"], 50.0)

    def test_lithology_compares_observation_and_requirement(self):
        profile = {"rock_type": "siliceo"}
        good = self.scored(profile=profile, env={"rock_type": "siliceo"})
        bad = self.scored(profile=profile, env={"rock_type": "calcareo"})
        self.assertGreater(good["environmental_score"], bad["environmental_score"])
        absent = self.scored(profile=profile)
        self.assertIsNone(absent["environmental_lithology_score"])
        self.assertEqual(absent["environmental_score"], 50.0)

    def test_ground_substrate_conflict_stays_soft(self):
        good = self.scored(env={"substrate": "roccia"})
        bad = self.scored(env={"substrate": "suolo"})
        self.assertGreater(good["environmental_score"], 50.0)
        self.assertLess(bad["environmental_score"], 50.0)
        self.assertGreater(bad["environmental_score"], 0.0)

    def test_soil_ph_is_not_applied_to_rock_or_bark(self):
        soil = {"soil_ph_num": 5.0, "ph_score": 6.0, "expected_ph": "acid",
                "litho_soil_ph_match": "numeric_ph", "ph_reason": "dentro range preferito"}
        for group in ("rock", "epiphyte", "lignicolous"):
            env = self.scored(group, env=soil)
            self.assertIsNone(env["environmental_ph_score"])
        env = self.scored("soil", env=soil)
        self.assertEqual(env["environmental_ph_score"], 85.0)
        soil['ph_reason'] = 'Translated diagnostic text'
        self.assertEqual(self.scored("soil", env=soil)["environmental_ph_score"], 85.0)

    def test_ph_without_a_species_preference_remains_missing(self):
        env = self.scored("soil", env={"soil_ph_num": 5.0, "soil_ph": "acid", "ph_score": 0.0})
        self.assertIsNone(env["environmental_ph_score"])

    def test_soil_reaction_compares_species_not_only_parent_rock(self):
        good = self.scored("soil", env={"soil_ph": "acid", "expected_ph": "acid"})
        bad = self.scored("soil", env={"soil_ph": "basic", "expected_ph": "acid"})
        self.assertGreater(good["environmental_ph_score"], bad["environmental_ph_score"])

    def test_parent_rock_proxy_is_not_counted_twice(self):
        env = self.scored("soil", {"rock_type": "siliceo"},
                          {"rock_type": "siliceo", "litho_soil_ph": "acid", "expected_ph": "acid"})
        self.assertIsNotNone(env["environmental_lithology_score"])
        self.assertIsNone(env["environmental_ph_score"])

    def test_missing_components_do_not_magnify_remaining_evidence(self):
        env = self.scored("soil", env={"soil_ph": "acid", "expected_ph": "acid"})
        parts = self.model._environmental_components(env)
        self.assertAlmostEqual(parts["effective_weights"]["ph"], (25.0 / 95.0) * 100.0 * 0.75)
        self.assertLess(parts["score"], 65.0)
        self.assertAlmostEqual(parts["score"], parts["neutral_contribution"] +
                               sum(value for value in parts["contributions"].values() if value is not None))

    def test_same_group_keeps_identical_weights_across_candidates(self):
        for group in ("soil", "rock", "moss", "epiphyte", "lignicolous", "unknown"):
            absent = self.model._environmental_components(self.scored(group))
            observed = self.model._environmental_components(self.scored(group, env={"forest_dist_m": 0.0,
                "substrate": "suolo", "soil_ph": "acid", "expected_ph": "acid"}))
            self.assertEqual(absent["weights"], observed["weights"])
            self.assertAlmostEqual(sum(absent["weights"].values()), 100.0)

    def test_woody_context_is_weaker_than_confirmed_phorophyte(self):
        exact = self.scored("epiphyte", env={"expected_tree": "quercia", "observed_tree": "quercia"})
        forest = self.scored("epiphyte", env={"forest_dist_m": 0.0})
        deadwood = self.scored("lignicolous", env={"forest_dist_m": 0.0})
        self.assertGreater(exact["environmental_score"], forest["environmental_score"])
        self.assertGreater(forest["environmental_score"], deadwood["environmental_score"])
        self.assertIn("non verificato", deadwood["environmental_reasons"]["tree_forest"])

    def test_distant_forest_does_not_prove_absence_of_isolated_supports(self):
        for group in ("epiphyte", "lignicolous"):
            env = self.scored(group, env={"forest_dist_m": 2000.0})
            self.assertIsNone(env["environmental_tree_score"])
            self.assertEqual(env["environmental_score"], 50.0)

    def test_woody_forest_proxy_is_not_duplicated_in_habitat(self):
        for group in ('epiphyte', 'lignicolous'):
            env = self.scored(group, {'habitat': ['bosco']}, {'forest_dist_m': 0.0})
            self.assertIsNotNone(env['environmental_tree_score'])
            self.assertIsNone(env['environmental_habitat_score'])

    def test_report_includes_neutral_contribution_and_sources(self):
        env = self.scored(profile={"rock_type": "siliceo"}, env={"rock_type": "siliceo"})
        rows = ExplainabilityService()._environment_rows(env)
        self.assertEqual(rows[-1]["key"], "neutral")
        self.assertAlmostEqual(sum(row["contribution"] or 0.0 for row in rows), env["environmental_score"])
        self.assertEqual(env["environmental_sources"]["lithology"], "candidate_lithology")

    def test_macro_weights_and_output_aliases_are_preserved(self):
        env = self.scored(profile={"rock_type": "siliceo"}, env={"rock_type": "siliceo"})
        self.assertEqual(self.model.MACRO_WEIGHTS, dict.fromkeys(
            ("geographic", "terrain", "environmental", "accessibility"), 25.0))
        self.assertEqual(env["final_score"], env["score"])
        self.assertEqual(env["score"], env["norm_score"])
        self.assertEqual(env["score"], env["heat_w"])
        before = copy.deepcopy(env)
        self.assertEqual(self.model.apply_to_env(env), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
