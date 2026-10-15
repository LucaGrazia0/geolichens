# -*- coding: utf-8 -*-
"""GeoLichen 4.5a scoring engine.

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

import re

from ._shared_geo_utils import to_float as _shared_to_float


class ScoringModel:
    """Motore ufficiale GeoLichen 4.5a."""

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

        altitude_score = 50.0
        alt_delta = self._to_float(env.get("alt_delta_m"))
        tolerance = self._to_float(
            env.get("altitude_tolerance_m"), 100.0
        ) or 100.0

        if alt_delta is not None:
            distance = abs(alt_delta)
            if distance <= tolerance:
                altitude_score = 100.0
            elif distance <= tolerance * 1.5:
                altitude_score = 75.0
            elif distance <= tolerance * 2.0:
                altitude_score = 50.0
            else:
                altitude_score = 20.0
        elif env.get("altitude") is not None:
            altitude_score = 70.0

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
        aspect_score = self._clamp(50.0 + aspect_bonus * 10.0)

        slope_penalty = self._to_float(env.get("slope_penalty"), 0.0) or 0.0
        slope_score = self._clamp(100.0 + slope_penalty * 10.0)

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
        return self._weighted_average(
            [
                (
                    components.get("altitude"),
                    self.TERRAIN_WEIGHTS["altitude"],
                ),
                (
                    components.get("aspect"),
                    self.TERRAIN_WEIGHTS["aspect"],
                ),
                (
                    components.get("slope"),
                    self.TERRAIN_WEIGHTS["slope"],
                ),
            ],
            default=50.0,
        )

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
        """Sottocomponenti Environmental 4.5b.2, availability-aware.

        Un valore mancante non viene più trasformato automaticamente in 50.
        Le componenti non valutabili sono marcate N/A ed escluse dalla media;
        i pesi delle sole componenti disponibili sono rinormalizzati a 100%.
        Un valore 50 resta possibile solo quando esiste un'evidenza realmente
        neutra o non discriminante.
        """
        env = env or {}
        group = group if group in ("soil", "rock", "epiphyte", "lignicolous", "moss", "unknown") else "unknown"

        constraints = self._lower_text(env.get("constraints"))
        observed_substrate = self._lower_text(env.get("substrate"))
        details = self._lower_text(env.get("details"))
        soil_reason = self._lower_text(env.get("soil_confidence_reason"))
        ph_reason = self._lower_text(env.get("ph_reason"))
        tree_reason = self._lower_text(env.get("tree_match_reason"))

        values = {}
        status = {}
        reasons = {}

        # 1) Substrato
        substrate_available = bool(observed_substrate) or self._contains_any(
            details, ["substrato compatibile", "substrato non ideale", "substrato incompatibile"]
        )
        substrate_score = None
        if substrate_available:
            substrate_score = 70.0 if observed_substrate else 50.0
            reason = f"substrato osservato: {observed_substrate}" if observed_substrate else "evidenza registrata nei dettagli"
            if "substrato compatibile" in details:
                substrate_score, reason = 100.0, "substrato esplicitamente compatibile"
            elif "substrato non ideale" in details or "substrato incompatibile" in details:
                substrate_score, reason = 40.0, "substrato non ideale o incompatibile"
            elif group in ("epiphyte", "lignicolous"):
                substrate_score, reason = None, "substrato GIS del terreno non applicabile al substrato legnoso del record"
            status["substrate"] = "non valutato" if substrate_score is None else "valutato"
            reasons["substrate"] = reason
        else:
            status["substrate"] = "non valutato"
            reasons["substrate"] = "nessuna evidenza di substrato disponibile"
        values["substrate"] = None if substrate_score is None else self._clamp(substrate_score)

        # 2) Litologia
        rock_type = self._lower_text(env.get("rock_type"))
        rock_raw = self._lower_text(env.get("rock_raw"))
        lithology_available = bool(rock_type or rock_raw) or "litologia" in details
        lithology_score = None
        if lithology_available:
            lithology_score = 65.0 if (rock_type or rock_raw) else 50.0
            reason = f"litologia osservata: {rock_type or rock_raw}" if (rock_type or rock_raw) else "evidenza litologica registrata"
            if "litologia compatibile" in details:
                lithology_score, reason = 100.0, "litologia esplicitamente compatibile"
            elif "litologia richiesta ma dato gis assente" in details:
                lithology_score, reason = 50.0, "preferenza presente, ma dato GIS non discriminante"
            elif "litologia" in details and any(term in details for term in ["incompatibile", "non compatibile"]):
                lithology_score, reason = 30.0, "litologia incompatibile"
            if group in ("epiphyte", "lignicolous"):
                lithology_score, reason = None, "litologia del terreno non applicabile al substrato legnoso del record"
            status["lithology"] = "non valutato" if lithology_score is None else "valutato"
            reasons["lithology"] = reason
        else:
            status["lithology"] = "non valutato"
            reasons["lithology"] = "layer o evidenza litologica non disponibile"
        values["lithology"] = None if lithology_score is None else self._clamp(lithology_score)

        # 3) pH
        ph_bonus = self._to_float(env.get("ph_score"), self._to_float(env.get("litho_soil_ph_score")))
        ph_available = ph_bonus is not None or bool(ph_reason or soil_reason)
        ph_score = None
        if ph_available:
            ph_score = 50.0
            reason = ph_reason or soil_reason or "evidenza pH disponibile"
            if ph_bonus is not None and "nessuna preferenza" not in reason:
                ph_score = self._clamp(50.0 + ph_bonus * 4.0)
            if "dentro range preferito" in ph_reason:
                ph_score = max(ph_score, 85.0)
            if group in ("epiphyte", "lignicolous") and "corteccia" not in tree_reason and "bark" not in tree_reason:
                ph_score, reason = None, "pH del suolo non applicabile al pH della corteccia"
            status["ph"] = "non valutato" if ph_score is None else "valutato"
            reasons["ph"] = reason
        else:
            status["ph"] = "non valutato"
            reasons["ph"] = "nessuna evidenza o preferenza pH disponibile"
        values["ph"] = None if ph_score is None else self._clamp(ph_score)

        # 4) Habitat
        habitat_terms = ["habitat=", "bosco", "alpino", "rupicolo", "prateria", "torbiera"]
        habitat_available = "coerenza habitat" in details or self._contains_any(constraints, habitat_terms)
        habitat_score = None
        if habitat_available:
            habitat_score = 60.0 if self._contains_any(constraints, habitat_terms) else 50.0
            reason = "vincolo o contesto habitat disponibile"
            if "coerenza habitat" in details:
                habitat_score, reason = 75.0, "coerenza habitat esplicitamente registrata"
                match = re.search(r"coerenza habitat[^\(]*\(([-+]?\d+(?:\.\d+)?)\)", details)
                if match:
                    try:
                        bonus = float(match.group(1))
                        habitat_score = self._clamp(55.0 + bonus * 4.0)
                        reason = f"coerenza habitat con bonus {bonus:g}"
                    except Exception:
                        pass
            status["habitat"] = "valutato"
            reasons["habitat"] = reason
        else:
            status["habitat"] = "non valutato"
            reasons["habitat"] = "nessuna evidenza tecnica di habitat registrata"
        values["habitat"] = None if habitat_score is None else self._clamp(habitat_score)

        # 5) Albero / foresta
        tree_match = max(0.0, self._to_float(env.get("tree_match_score"), 0.0) or 0.0)
        forest_bonus = max(0.0, self._to_float(env.get("forest_dist_score"), 0.0) or 0.0)
        forest_dist = self._to_float(env.get("forest_dist_m"))
        expected_tree = self._lower_text(env.get("expected_tree"))
        observed_tree = self._lower_text(env.get("observed_tree"))
        forest_category = self._lower_text(env.get("forest_category"))
        tree_available = any([tree_match > 0, forest_bonus > 0, forest_dist is not None, expected_tree, observed_tree, forest_category, tree_reason])
        tree_score = None
        if tree_available:
            tree_score = 50.0
            reason = "evidenza forestale disponibile ma non discriminante"
            explicit_tree_expected = bool(expected_tree)
            exact_tree_match = bool(explicit_tree_expected and observed_tree and (expected_tree == observed_tree or expected_tree in observed_tree or observed_tree in expected_tree))
            if exact_tree_match:
                tree_score, reason = 100.0, "forofita attesa confermata"
            elif tree_match > 0:
                tree_score, reason = self._clamp(50.0 + tree_match * 2.5), "corrispondenza arborea parziale"
            if group == "epiphyte" and explicit_tree_expected and observed_tree and not exact_tree_match:
                tree_score, reason = max(tree_score, 58.0), "presenza arborea confermata, forofita specifica non confermata"
            if group == "lignicolous" and forest_dist is not None:
                # Per legno morto/ceppaie la copertura forestale è un proxy del
                # contesto adatto, non una prova diretta della presenza di deadwood.
                # Curva continua e più prudente rispetto agli epifiti.
                d = max(0.0, float(forest_dist))
                if d <= 25.0:
                    proposed = 92.0
                elif d <= 100.0:
                    proposed = 92.0 - ((d - 25.0) / 75.0) * 12.0
                elif d <= 250.0:
                    proposed = 80.0 - ((d - 100.0) / 150.0) * 25.0
                elif d <= 500.0:
                    proposed = 55.0 - ((d - 250.0) / 250.0) * 25.0
                elif d <= 1000.0:
                    proposed = 30.0 - ((d - 500.0) / 500.0) * 18.0
                else:
                    proposed = 10.0
                tree_score = proposed
                reason = f"distanza dal contesto forestale: {forest_dist:.1f} m; proxy lignicolo={proposed:.1f}"
            elif group == "epiphyte" and forest_dist is not None:
                # Score assoluto e continuo: la distanza deve poter penalizzare,
                # non soltanto aggiungere un bonus sopra il valore neutro 50.
                d = max(0.0, float(forest_dist))
                if d <= 25.0:
                    proposed = 100.0
                elif d <= 100.0:
                    proposed = 100.0 - ((d - 25.0) / 75.0) * 15.0
                elif d <= 250.0:
                    proposed = 85.0 - ((d - 100.0) / 150.0) * 35.0
                elif d <= 500.0:
                    proposed = 50.0 - ((d - 250.0) / 250.0) * 30.0
                elif d <= 1000.0:
                    proposed = 20.0 - ((d - 500.0) / 500.0) * 15.0
                else:
                    proposed = 5.0

                # Una forofita esatta confermata resta evidenza più forte della
                # distanza dal poligono forestale; negli altri casi prevale lo
                # score spaziale, che può scendere sotto 50.
                if not exact_tree_match:
                    tree_score = proposed
                reason = f"distanza dalla copertura forestale: {forest_dist:.1f} m; score epifita={proposed:.1f}"
            if group == "epiphyte" and not explicit_tree_expected and (forest_category or observed_tree):
                tree_score, reason = max(tree_score, 70.0), "copertura arborea generica confermata"
            elif group == "lignicolous" and forest_dist is None and (forest_category or observed_tree):
                tree_score, reason = max(tree_score, 68.0), "contesto forestale disponibile; presenza di legno morto non verificata"
            elif group not in ("epiphyte", "lignicolous") and (forest_category or observed_tree):
                tree_score, reason = max(tree_score, 65.0), "presenza arborea/forestale nel contesto"
            status["tree_forest"] = "valutato"
            reasons["tree_forest"] = reason
        else:
            status["tree_forest"] = "non valutato"
            reasons["tree_forest"] = "nessun dato su alberi o copertura forestale"
        values["tree_forest"] = None if tree_score is None else self._clamp(tree_score)

        weights_by_group = {
            "epiphyte": {"substrate": 0.0, "lithology": 0.0, "ph": 0.0, "habitat": 25.0, "tree_forest": 75.0},
            "lignicolous": {"substrate": 0.0, "lithology": 0.0, "ph": 0.0, "habitat": 35.0, "tree_forest": 65.0},
            "rock": {"substrate": 30.0, "lithology": 30.0, "ph": 15.0, "habitat": 20.0, "tree_forest": 5.0},
            "soil": {"substrate": 30.0, "lithology": 15.0, "ph": 25.0, "habitat": 25.0, "tree_forest": 5.0},
            "moss": {"substrate": 35.0, "lithology": 10.0, "ph": 15.0, "habitat": 30.0, "tree_forest": 10.0},
            "unknown": {"substrate": 30.0, "lithology": 20.0, "ph": 15.0, "habitat": 20.0, "tree_forest": 15.0},
        }
        nominal_weights = weights_by_group[group]
        available = [key for key, value in values.items() if value is not None]
        available_weight = sum(nominal_weights[key] for key in available)

        # Per epifiti e lignicoli la sola prossimità alla foresta non deve
        # assorbire automaticamente il peso delle evidenze mancanti. I pesi
        # nominali restano quindi un tetto: albero/foresta vale al massimo 75%
        # negli epifiti e 65% nei lignicoli. Per gli altri gruppi si conserva
        # la rinormalizzazione storica delle componenti disponibili.
        preserve_missing_weight = group in ("epiphyte", "lignicolous")
        if preserve_missing_weight:
            effective_weights = {
                key: (nominal_weights[key] if key in available else 0.0)
                for key in values
            }
        else:
            effective_weights = {
                key: (nominal_weights[key] * 100.0 / available_weight if key in available and available_weight > 0 else 0.0)
                for key in values
            }

        if available_weight > 0:
            total = sum(values[key] * effective_weights[key] for key in available) / 100.0
            method = "nominal_weights_missing_not_redistributed" if preserve_missing_weight else "available_components_renormalized"
        else:
            italic = self._to_float(env.get("ecological_score"))
            total = self._clamp(italic) if italic is not None else 50.0
            method = "italic_fallback" if italic is not None else "neutral_fallback"

        contributions = {key: (None if values[key] is None else values[key] * effective_weights[key] / 100.0) for key in values}
        return {
            "score": self._clamp(total),
            "group": group,
            "weights": nominal_weights,
            "effective_weights": effective_weights,
            "components": values,
            "status": status,
            "reasons": reasons,
            "contributions": contributions,
            "method": method,
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
        """Environmental 4.5b: substrato, litologia, pH, habitat e foresta.

        Il valore è costruito da sottocomponenti esplicite. La carta forestale
        fornisce evidenza positiva per epifiti/lignicoli, mentre la sua assenza
        resta neutra per rispettare alberi isolati e microhabitat non mappati.
        """
        result = self._environmental_components(env)
        return self._clamp(result.get("score"), 0.0)

    def accessibility_score(self, env, components=None):
        """Plausibilità di accesso tramite sentieri, piste e contesto."""
        components = components or self.legacy_component_scores(env)
        return self._clamp(components.get("accessibility"), 50.0)

    # Alias usato dalla versione bridge.
    def accessibility_macro_score(self, env, components=None):
        return self.accessibility_score(env, components)

    def macro_scores(self, env):
        components = self.legacy_component_scores(env)
        return {
            "geographic": self.geographic_score(env, components),
            "terrain": self.terrain_score(env, components),
            "environmental": self.environmental_score(env, components),
            "accessibility": self.accessibility_score(env, components),
        }

    def final_score(self, env):
        """Unica funzione obiettivo ufficiale GeoLichen 4.5a."""
        macro = self.macro_scores(env)
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
            "architecture_version": "4.5c-context-pipelines",
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
            "architecture_version", "4.5c-context-pipelines"
        )

        env["geographic_score"] = macro.get("geographic")
        env["terrain_macro_score"] = macro.get("terrain")
        env["environmental_score"] = macro.get("environmental")
        env_result = self._environmental_components(env)
        env["environmental_score_raw"] = env_result.get("score")
        env["environmental_score_method"] = env_result.get("method")
        env["environmental_available_weight"] = sum(
            value for key, value in (env_result.get("weights") or {}).items()
            if (env_result.get("components") or {}).get(key) is not None
        )
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

        return "; ".join(parts)
