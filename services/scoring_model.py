# -*- coding: utf-8 -*-
"""GeoLichen evidence-aware scoring engine.

Architettura ufficiale:
- Geographic Score: 25%
- Terrain Score: 25%
- Environmental Score: 25%
- Accessibility Score: 25%

Il cartellino è una sorgente primaria di evidenze.
ITALIC è riferimento/fallback e rimane disponibile a fini diagnostici,
ma non costituisce più un macro-score autonomo.

`final_score` è l'unico score ufficiale. Per retrocompatibilità:
- score = final_score
- norm_score = final_score
- heat_w = final_score

I vecchi componenti restano esportati come diagnostica legacy.
"""

from .environmental_evidence_service import EnvironmentalEvidenceService

from ._shared_geo_utils import to_float as _shared_to_float


class ScoringModel:
    """Official scoring, with candidate observations and proxy provenance."""

    MACRO_WEIGHTS = {
        "geographic": 25.0,
        "terrain": 25.0,
        "environmental": 25.0,
        "accessibility": 25.0,
    }

    # Pesi interni dei sotto-componenti del Terrain.
    TERRAIN_WEIGHTS = {
        "altitude": 20.0,
        "aspect": 5.0,
        "slope": 5.0,
    }

    def _to_float(self, value, default=None):
        return _shared_to_float(value, default=default)

    def _clamp(self, value, lo=0.0, hi=100.0):
        try:
            return max(lo, min(hi, float(value)))
        except Exception:
            return lo

    def _weighted_average(self, pairs, default=50.0):
        valid = []
        for score, weight in pairs:
            if score is None or weight is None:
                continue
            try:
                weight = float(weight)
            except Exception:
                continue
            if weight <= 0:
                continue
            valid.append((self._clamp(score), weight))

        if not valid:
            return self._clamp(default)

        total_weight = sum(weight for _, weight in valid) or 1.0
        return self._clamp(
            sum(score * weight for score, weight in valid) / total_weight
        )

    # ------------------------------------------------------------------
    # Componenti legacy: conservati solo per diagnostica e confronto.
    # ------------------------------------------------------------------
    def legacy_component_scores(self, env):
        env = env or {}

        record_score = self._clamp(
            self._to_float(env.get("record_score"), 50.0)
        )

        altitude_score = self.altitude_score(env)

        environmental_score = 50.0
        soil_confidence = self._to_float(env.get("soil_confidence_score"))
        lithology_ph = self._to_float(env.get("litho_soil_ph_score"))
        tree_match = self._to_float(env.get("tree_match_score"))
        forest_distance = self._to_float(env.get("forest_dist_score"))

        environmental_signals = [
            value
            for value in [
                soil_confidence,
                lithology_ph,
                tree_match,
                forest_distance,
            ]
            if value is not None
        ]
        if environmental_signals:
            environmental_score = self._clamp(
                50.0 + sum(environmental_signals) * 5.0
            )
        if env.get("substrate"):
            environmental_score = max(environmental_score, 70.0)

        italic_score = self._clamp(
            self._to_float(env.get("ecological_score"), 50.0)
        )

        accessibility_score = self._clamp(
            self._to_float(
                env.get("accessibility_confidence"),
                self._to_float(env.get("accessibility_score"), 50.0),
            )
        )

        aspect_bonus = self._to_float(env.get("aspect_bonus"), 0.0) or 0.0
        aspect_score = (self._clamp(50.0 + aspect_bonus * 10.0)
                        if self._to_float(env.get("aspect")) is not None and env.get("record_aspect")
                        else None)

        slope_penalty = self._to_float(env.get("slope_penalty"), 0.0) or 0.0
        slope_score = (self._clamp(100.0 + slope_penalty * 10.0)
                       if self._to_float(env.get("slope")) is not None
                       and self._to_float(env.get("slope_penalty")) is not None else None)

        return {
            "record": record_score,
            "altitude": altitude_score,
            "substrate": environmental_score,
            "italic": italic_score,
            "accessibility": accessibility_score,
            "aspect": aspect_score,
            "slope": slope_score,
        }

    def component_scores(self, env):
        """Alias storico per compatibilità."""
        return self.legacy_component_scores(env)

    def altitude_score(self, env):
        """Continuous compatibility, separate from the record's hard filter.

        Every elevation inside a stated interval is equally compatible. For a
        single value, distance is measured from that value. At one tolerance
        beyond the value/interval the score is neutral (50). This is an
        explicit model heuristic, not a calibrated probability.
        """
        env = env or {}
        altitude = self._to_float(env.get("altitude"))
        low = self._to_float(env.get("record_altitude_min"))
        high = self._to_float(env.get("record_altitude_max"))
        record = self._to_float(env.get("record_altitude"))
        if altitude is not None and low is not None and high is not None:
            low, high = sorted((low, high))
            delta = max(low - altitude, altitude - high, 0.0)
        elif altitude is not None and record is not None:
            delta = abs(altitude - record)
        else:
            delta = self._to_float(env.get("alt_delta_m"))
        if delta is None:
            return None
        tolerance = self._to_float(env.get("altitude_tolerance_m"), 100.0)
        if tolerance is None or tolerance <= 0:
            tolerance = 100.0
        return self._clamp(100.0 - 50.0 * abs(delta) / tolerance)

    # ------------------------------------------------------------------
    # Quattro macro-score ufficiali 4.5a.
    # ------------------------------------------------------------------
    def geographic_score(self, env, components=None):
        """Coerenza spaziale con località, contesto e toponimo.

        Usa il geography/context score già calcolato dal motore geografico.
        Non usa più `record_score` come punteggio autonomo.
        """
        env = env or {}
        value = self._to_float(env.get("geography_score"))
        if value is None:
            value = self._to_float(env.get("context_score"), 50.0)
        return self._clamp(value if value is not None else 50.0)

    def terrain_score(self, env, components=None):
        """Quota, esposizione e pendenza, aggregate una sola volta."""
        components = components or self.legacy_component_scores(env)
        # Fixed weights keep missing measurements neutral for every candidate.
        total_weight = sum(self.TERRAIN_WEIGHTS.values())
        return self._clamp(50.0 + sum(
            weight * (components[key] - 50.0)
            for key, weight in self.TERRAIN_WEIGHTS.items()
            if components.get(key) is not None
        ) / total_weight)

    def _lower_text(self, value):
        try:
            return str(value or "").strip().lower()
        except Exception:
            return ""

    def _contains_any(self, text, terms):
        text = self._lower_text(text)
        return any(term in text for term in terms)

    def _substrate_group(self, env):
        """Return the authoritative ecological group without reclassification.

        The scoring model must not reinterpret free text, GIS observations or
        ITALIC habitat strings. It consumes the decision already produced by
        SubstrateResolutionService / EcologicalLayerDecisionService.
        """
        env = env or {}
        constraints = env.get("constraints") or {}
        if not isinstance(constraints, dict):
            constraints = {}
        layer_decision = env.get("layer_decision") or constraints.get("layer_decision") or {}
        if not isinstance(layer_decision, dict):
            layer_decision = {}

        candidates = [
            env.get("substrate_group"),
            env.get("resolved_substrate_group"),
            constraints.get("substrate_group"),
            layer_decision.get("substrate_group"),
            env.get("environmental_group"),
        ]
        aliases = {
            "suolo": "soil",
            "terricolo": "soil",
            "roccia": "rock",
            "saxicolous": "rock",
            "sassicolo": "rock",
            "epifita": "epiphyte",
            "epiphytic": "epiphyte",
            "lignicolo": "lignicolous",
            "lignicolous": "lignicolous",
            "muschio": "moss",
            "muscicolo": "moss",
        }
        supported = {"soil", "rock", "epiphyte", "lignicolous", "moss", "unknown"}
        for value in candidates:
            value = self._lower_text(value)
            value = aliases.get(value, value)
            if value in supported:
                return value
        return "unknown"

    def _primary_pipeline(self, env, group=None):
        """Return the persisted pipeline, constrained by the resolved group."""
        env = env or {}
        constraints = env.get("constraints") or {}
        if not isinstance(constraints, dict):
            constraints = {}
        layer_decision = env.get("layer_decision") or constraints.get("layer_decision") or {}
        if not isinstance(layer_decision, dict):
            layer_decision = {}

        group = group or self._substrate_group(env)
        canonical = {
            "soil": "soil",
            "rock": "rock",
            "epiphyte": "epiphyte",
            "lignicolous": "lignicolous",
            "moss": "moss",
            "unknown": "unknown",
        }
        persisted = self._lower_text(
            env.get("primary_pipeline")
            or env.get("environmental_pipeline")
            or layer_decision.get("primary_pipeline")
            or layer_decision.get("primary_layer")
            or layer_decision.get("primary")
        )
        aliases = {
            "geology": "rock",
            "geologia": "rock",
            "trees": "epiphyte" if group == "epiphyte" else "lignicolous",
            "tree": "epiphyte" if group == "epiphyte" else "lignicolous",
            "forest": "epiphyte" if group == "epiphyte" else "lignicolous",
            "generic": "unknown",
        }
        persisted = aliases.get(persisted, persisted)
        expected = canonical.get(group, "unknown")
        # A persisted pipeline may refine an unknown group, but it may never
        # contradict an authoritative resolved group.
        if group == "unknown" and persisted in canonical.values():
            return persisted
        return expected

    def _environmental_components_for_group(self, env, group):
        """Aggregate explicit evidence with fixed weights and neutral missing data.

        Requirements never count as observations. Proxy quality reduces a
        contribution toward 50; it is not a probability of correctness.
        """
        env = env or {}
        evaluator = EnvironmentalEvidenceService()
        evidence = env.get("ecological_evidence")
        if not isinstance(evidence, dict):
            evidence = evaluator.evaluate(env, env.get("constraints") or {})
        weights_by_group = {
            "epiphyte": {"substrate": 0., "lithology": 0., "ph": 0., "habitat": 25., "tree_forest": 75.},
            "lignicolous": {"substrate": 0., "lithology": 0., "ph": 0., "habitat": 35., "tree_forest": 65.},
            "rock": {"substrate": 30., "lithology": 30., "ph": 0., "habitat": 20., "tree_forest": 0.},
            "soil": {"substrate": 30., "lithology": 15., "ph": 25., "habitat": 25., "tree_forest": 0.},
            "moss": {"substrate": 35., "lithology": 10., "ph": 15., "habitat": 30., "tree_forest": 0.},
            "unknown": {"substrate": 30., "lithology": 20., "ph": 0., "habitat": 20., "tree_forest": 0.},
        }
        group = group if group in weights_by_group else "unknown"
        original_weights = weights_by_group[group]
        total_weight = sum(original_weights.values())
        weights = {key: weight * 100.0 / total_weight for key, weight in original_weights.items()}
        values, status, reasons, qualities, sources = {}, {}, {}, {}, {}
        for key, weight in weights.items():
            item = evidence.get(key) or {}
            value = self._to_float(item.get("score"))
            if weight <= 0:
                value = None
                status[key] = "non applicabile"
            elif value is None:
                status[key] = "mancante"
            else:
                status[key] = "valutato"
            values[key] = None if value is None else self._clamp(value)
            qualities[key] = (self._clamp(self._to_float(item.get("quality"), 1.0), 0.0, 1.0)
                              if value is not None else 0.0)
            reasons[key] = item.get("reason") or "Dato del candidato non disponibile"
            sources[key] = item.get("source") or ""
        effective = {key: weights[key] * qualities[key] for key in weights}
        neutral = 50.0 * (1.0 - sum(effective.values()) / 100.0)
        contributions = {key: (None if values[key] is None else values[key] * effective[key] / 100.0)
                         for key in weights}
        total = neutral + sum(value for value in contributions.values() if value is not None)
        return {
            "score": self._clamp(total), "group": group, "weights": weights,
            "effective_weights": effective, "components": values, "status": status,
            "reasons": reasons, "contributions": contributions, "sources": sources,
            "qualities": qualities, "neutral_contribution": neutral,
            "coverage": sum(weights[key] for key in weights if values[key] is not None),
            "quality_coverage": sum(effective.values()),
            "method": "fixed_weights_neutral_missing_proxy_quality",
        }

    def environment_score_soil(self, env):
        return self._environmental_components_for_group(env, "soil")

    def environment_score_rock(self, env):
        return self._environmental_components_for_group(env, "rock")

    def environment_score_epiphyte(self, env):
        return self._environmental_components_for_group(env, "epiphyte")

    def environment_score_lignicolous(self, env):
        return self._environmental_components_for_group(env, "lignicolous")

    def environment_score_moss(self, env):
        return self._environmental_components_for_group(env, "moss")

    def environment_score_unknown(self, env):
        return self._environmental_components_for_group(env, "unknown")

    def _environmental_components(self, env):
        """Dispatch Environmental scoring through one explicit pipeline."""
        env = env or {}
        group = self._substrate_group(env)
        pipeline = self._primary_pipeline(env, group)
        dispatch = {
            "soil": self.environment_score_soil,
            "rock": self.environment_score_rock,
            "epiphyte": self.environment_score_epiphyte,
            "lignicolous": self.environment_score_lignicolous,
            "moss": self.environment_score_moss,
            "unknown": self.environment_score_unknown,
        }
        result = dispatch.get(pipeline, self.environment_score_unknown)(env)
        result["resolved_group"] = group
        result["pipeline"] = pipeline
        result["substrate_source"] = env.get("substrate_source")
        result["substrate_locked"] = bool(env.get("substrate_locked"))
        result["substrate_confidence"] = env.get("substrate_confidence")
        return result

    def environmental_score(self, env, components=None):
        """Fixed applicable weights; missing evidence stays neutral at 50."""
        result = self._environmental_components(env)
        return self._clamp(result.get("score"), 0.0)

    def accessibility_score(self, env, components=None):
        """Plausibilità di accesso tramite sentieri e piste, senza geografia."""
        components = components or self.legacy_component_scores(env)
        value = components.get("accessibility")
        return self._clamp(value if value is not None else 50.0)

    # Alias usato dalla versione bridge.
    def accessibility_macro_score(self, env, components=None):
        return self.accessibility_score(env, components)

    def macro_scores(self, env, environmental_result=None):
        components = self.legacy_component_scores(env)
        if environmental_result is None:
            environmental_result = self._environmental_components(env)
        return {
            "geographic": self.geographic_score(env, components),
            "terrain": self.terrain_score(env, components),
            "environmental": environmental_result["score"],
            "accessibility": self.accessibility_score(env, components),
        }

    def final_score(self, env):
        """Unica funzione obiettivo ufficiale GeoLichen 4.5a."""
        environmental_result = self._environmental_components(env)
        macro = self.macro_scores(env, environmental_result=environmental_result)
        contributions = {}
        total = 0.0

        for key, weight in self.MACRO_WEIGHTS.items():
            score = self._clamp(macro.get(key), 0.0)
            contribution = score * (weight / 100.0)
            contributions[key] = {
                "score": score,
                "weight": weight,
                "contribution": contribution,
            }
            total += contribution

        return {
            "score": self._clamp(total),
            "macro_components": macro,
            "weights": dict(self.MACRO_WEIGHTS),
            "used": contributions,
            "legacy_components": self.legacy_component_scores(env),
            "environmental_result": environmental_result,
            "architecture_version": "4.7-independent-evidence",
        }

    def normalized_score(self, env):
        """Alias storico: ora restituisce il final score ufficiale."""
        return self.final_score(env)

    def apply_to_env(self, env):
        env = env or {}
        result = self.final_score(env)
        final = self._clamp(result.get("score"), 0.0)
        macro = result.get("macro_components") or {}
        legacy = result.get("legacy_components") or {}
        used = result.get("used") or {}

        # Unico score ufficiale e alias retrocompatibili.
        env["final_score"] = final
        env["score"] = final
        env["norm_score"] = final
        env["heat_w"] = final
        env["scoring_architecture"] = result.get(
            "architecture_version", "4.7-independent-evidence"
        )

        env["geographic_score"] = macro.get("geographic")
        env["terrain_macro_score"] = macro.get("terrain")
        env["environmental_score"] = macro.get("environmental")
        env_result = result["environmental_result"]
        env["environmental_score_raw"] = env_result.get("score")
        env["environmental_score_method"] = env_result.get("method")
        env["environmental_available_weight"] = env_result["coverage"]
        env["environmental_quality_coverage"] = env_result["quality_coverage"]
        env["environmental_neutral_contribution"] = env_result["neutral_contribution"]
        env["environmental_sources"] = dict(env_result["sources"])
        env["environmental_qualities"] = dict(env_result["qualities"])
        env["environmental_evidence_status"] = dict(env_result["status"])
        env["environmental_group"] = env_result.get("group")
        env["environmental_pipeline"] = env_result.get("pipeline")
        env["primary_pipeline"] = env_result.get("pipeline")
        env["resolved_substrate_group"] = env_result.get("resolved_group")
        env["environmental_substrate_score"] = (env_result.get("components") or {}).get("substrate")
        env["environmental_lithology_score"] = (env_result.get("components") or {}).get("lithology")
        env["environmental_ph_score"] = (env_result.get("components") or {}).get("ph")
        env["environmental_habitat_score"] = (env_result.get("components") or {}).get("habitat")
        env["environmental_tree_score"] = (env_result.get("components") or {}).get("tree_forest")
        env["environmental_components"] = "; ".join(
            f"{key}={'N/A' if value is None else round(value, 1)}"
            for key, value in (env_result.get("components") or {}).items()
        )
        env["environmental_weights"] = "; ".join(
            f"{key}:{round(value, 1)}%"
            for key, value in (env_result.get("weights") or {}).items()
        )
        env["environmental_effective_weights"] = "; ".join(
            f"{key}:{round(value, 1)}%"
            for key, value in (env_result.get("effective_weights") or {}).items()
        )
        env["environmental_status"] = "; ".join(
            f"{key}:{value}" for key, value in (env_result.get("status") or {}).items()
        )
        env["environmental_reasons"] = dict(env_result.get("reasons") or {})
        env["environmental_contributions"] = dict(env_result.get("contributions") or {})
        env["environmental_aggregation_method"] = env_result.get("method")
        env["accessibility_macro_score"] = macro.get("accessibility")

        env["norm_weights"] = "; ".join(
            f"{key}:{round(value.get('weight', 0), 1)}%"
            for key, value in used.items()
        )
        env["score_components"] = "; ".join(
            f"{key}={round(value.get('score', 0), 1)}*"
            f"{round(value.get('weight', 0), 1)}%"
            for key, value in used.items()
        )
        env["macro_weights_target"] = env["norm_weights"]

        # Diagnostica legacy: non governa più ranking o GSS.
        env["altitude_score"] = legacy.get("altitude")
        env["substrate_score"] = legacy.get("substrate")
        env["lithology_score"] = legacy.get("substrate")
        env["italic_score"] = legacy.get("italic")
        env["accessibility_score_norm"] = legacy.get("accessibility")
        env["aspect_score_norm"] = legacy.get("aspect")
        env["slope_score"] = legacy.get("slope")
        env["record_score_norm"] = legacy.get("record")

        return env

    def diagnostic_text(self, env):
        env = env or {}
        final = self._to_float(env.get("final_score"))
        parts = []

        if final is not None:
            parts.append(f"final_score ufficiale={round(final, 1)}")
        if env.get("norm_weights"):
            parts.append(f"pesi macro: {env.get('norm_weights')}")
        if env.get("score_components"):
            parts.append(f"macro-componenti: {env.get('score_components')}")
        if env.get("environmental_available_weight") is not None:
            parts.append(f"copertura evidenze ambientali={env['environmental_available_weight']:.1f}%; "
                         f"ponderata per qualità={env['environmental_quality_coverage']:.1f}%; "
                         f"contributo neutro={env['environmental_neutral_contribution']:.1f}")

        return "; ".join(parts)
