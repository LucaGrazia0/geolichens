"""Explainability engine for GeoLichen Phase 11.1.

Builds a deterministic, read-only explanation from candidate environments.
It never recalculates or changes GSS/ranking.
"""


class ExplainabilityService:
    MACRO_LABELS = {
        "geographic": "Coerenza geografica",
        "terrain": "Terreno (quota, esposizione, pendenza)",
        "environmental": "Ambiente (substrato, litologia, pH, habitat, alberi)",
        "accessibility": "Accessibilità",
    }
    ENV_LABELS = {
        "substrate": "Substrato",
        "lithology": "Litologia",
        "ph": "pH",
        "habitat": "Habitat",
        "tree_forest": "Albero / foresta",
    }

    @staticmethod
    def _num(value, default=None):
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _candidate_rank(candidate, fallback=0):
        try:
            return int(candidate.get("rank") or fallback)
        except Exception:
            return fallback


    @staticmethod
    def _present(value):
        return value not in (None, "", [], {}, ())

    @staticmethod
    def _as_text(value, default=""):
        if value is None:
            return default
        try:
            text = str(value).strip()
            return text if text else default
        except Exception:
            return default

    def _substrate_resolution(self, candidate, env):
        """Build a read-only audit block for the central substrate decision.

        The method never infers a new substrate class. It only exposes values
        already propagated by RecordSemanticInterpreter /
        SubstrateResolutionService and the layer-decision pipeline.
        """
        candidate = candidate or {}
        env = env or {}
        constraints = candidate.get("constraints") or {}
        if not isinstance(constraints, dict):
            constraints = {}

        def first(*keys, default=None):
            for key in keys:
                for source in (env, constraints, candidate):
                    if isinstance(source, dict) and self._present(source.get(key)):
                        return source.get(key)
            return default

        group = self._as_text(first("substrate_group", "environmental_group"), "unknown").lower()
        raw = self._as_text(first("substrate_raw", "record_substrate", "substrate"), "Non disponibile")
        source = self._as_text(first("substrate_source"), "Non tracciata")
        reason = self._as_text(
            first("substrate_resolution_reason", "substrate_reason"),
            "Motivazione non registrata",
        )
        confidence = self._num(first("substrate_confidence"))
        locked_value = first("substrate_locked")
        locked = bool(locked_value) if locked_value is not None else False

        layer_decision = first("layer_decision", default={}) or {}
        if not isinstance(layer_decision, dict):
            layer_decision = {}
        primary_layer = self._as_text(
            layer_decision.get("primary_layer")
            or layer_decision.get("primary")
            or first("primary_environmental_layer"),
            "non definito",
        )
        use_geology = layer_decision.get("use_geology")
        use_soil = layer_decision.get("use_soil")
        use_trees = layer_decision.get("use_trees")

        italic_role = "fallback" if source == "italic_profile" else "supporto ecologico"
        italic_overrode = bool(source == "italic_profile" and not locked)

        group_labels = {
            "rock": "Roccia",
            "soil": "Suolo",
            "epiphyte": "Epifita",
            "lignicolous": "Lignicolo",
            "moss": "Muscicolo",
            "unknown": "Non determinato",
        }
        pipeline_labels = {
            "rock": "Pipeline geologica",
            "soil": "Pipeline del suolo",
            "epiphyte": "Pipeline arborea/forestale",
            "lignicolous": "Pipeline legno/foresta",
            "moss": "Pipeline suolo/microhabitat",
            "unknown": "Pipeline ambientale generica",
        }

        return {
            "observed_value": raw,
            "group": group,
            "group_label": group_labels.get(group, group or "Non determinato"),
            "source": source,
            "locked": locked,
            "confidence": confidence,
            "confidence_percent": confidence * 100.0 if confidence is not None else None,
            "reason": reason,
            "pipeline": pipeline_labels.get(group, "Pipeline ambientale generica"),
            "primary_layer": primary_layer,
            "use_geology": use_geology,
            "use_soil": use_soil,
            "use_trees": use_trees,
            "italic_role": italic_role,
            "italic_changed_substrate": italic_overrode,
            "decision_flow": [
                "Specimen Label",
                "Substrate Resolution",
                "Ecological Context",
                "Layer Decision",
                "Environmental Score",
            ],
        }

    def _macro_rows(self, env):
        env = env or {}
        weights = {
            "geographic": 15.0,
            "terrain": 30.0,
            "environmental": 40.0,
            "accessibility": 15.0,
        }
        # Prefer weights persisted by the scoring engine when available.
        text = str(env.get("norm_weights") or "")
        for part in text.split(";"):
            try:
                key, value = part.strip().split(":", 1)
                weights[key.strip()] = float(value.replace("%", "").strip())
            except Exception:
                pass

        scores = {
            "geographic": self._num(env.get("geographic_score"), 50.0),
            "terrain": self._num(env.get("terrain_macro_score"), 50.0),
            "environmental": self._num(env.get("environmental_score"), 50.0),
            "accessibility": self._num(env.get("accessibility_macro_score"), 50.0),
        }
        rows = []
        for key in ("geographic", "terrain", "environmental", "accessibility"):
            score = scores[key]
            weight = weights.get(key, 0.0)
            rows.append({
                "key": key,
                "label": self.MACRO_LABELS[key],
                "score": score,
                "weight": weight,
                "contribution": score * weight / 100.0,
            })
        return rows

    def _environment_rows(self, env):
        env = env or {}
        value_keys = {
            "substrate": "environmental_substrate_score",
            "lithology": "environmental_lithology_score",
            "ph": "environmental_ph_score",
            "habitat": "environmental_habitat_score",
            "tree_forest": "environmental_tree_score",
        }
        nominal_weights = {}
        for part in str(env.get("environmental_weights") or "").split(";"):
            try:
                key, value = part.strip().split(":", 1)
                nominal_weights[key.strip()] = float(value.replace("%", "").strip())
            except Exception:
                pass
        effective_weights = {}
        for part in str(env.get("environmental_effective_weights") or "").split(";"):
            try:
                key, value = part.strip().split(":", 1)
                effective_weights[key.strip()] = float(value.replace("%", "").strip())
            except Exception:
                pass
        statuses = {}
        for part in str(env.get("environmental_status") or "").split(";"):
            try:
                key, value = part.strip().split(":", 1)
                statuses[key.strip()] = value.strip()
            except Exception:
                pass
        reasons = env.get("environmental_reasons") or {}
        contributions = env.get("environmental_contributions") or {}
        rows = []
        for key, field in value_keys.items():
            score = self._num(env.get(field))
            status = statuses.get(key, "valutato" if score is not None else "non valutato")
            effective_weight = effective_weights.get(key, nominal_weights.get(key))
            contribution = self._num(contributions.get(key))
            if contribution is None and score is not None and effective_weight is not None:
                contribution = score * effective_weight / 100.0
            rows.append({
                "key": key,
                "label": self.ENV_LABELS[key],
                "score": score,
                "status": status,
                "weight": nominal_weights.get(key),
                "effective_weight": effective_weight,
                "contribution": contribution,
                "reason": reasons.get(key) or "Motivazione non registrata",
            })
        return rows


    @staticmethod
    def _present(value):
        return value not in (None, "", [], {}, ())

    @classmethod
    def _first_present(cls, *values):
        for value in values:
            if cls._present(value):
                return value
        return None

    def _substrate_resolution_from_env(self, env):
        """Builds a compact read-only audit block from an environment mapping.

        This compatibility helper is used only by ``_ecological_resolution``.
        The public report path uses ``_substrate_resolution(candidate, env)``.

        No classification is performed here: the method only exposes values already
        persisted by SubstrateResolutionService / RecordSemanticInterpreter.
        """
        env = env or {}
        constraints = env.get("constraints") or {}
        if not isinstance(constraints, dict):
            constraints = {}
        layer_decision = self._first_present(
            env.get("layer_decision"),
            constraints.get("layer_decision"),
        ) or {}
        if not isinstance(layer_decision, dict):
            layer_decision = {}

        group = self._first_present(
            env.get("substrate_group"),
            constraints.get("substrate_group"),
            layer_decision.get("substrate_group"),
            env.get("environmental_group"),
        ) or "unknown"
        raw = self._first_present(
            env.get("substrate_raw"),
            constraints.get("substrate_raw"),
            env.get("record_substrate_raw"),
            env.get("record_substrate"),
        )
        source = self._first_present(
            env.get("substrate_source"),
            constraints.get("substrate_source"),
        ) or "unknown"
        locked_raw = self._first_present(
            env.get("substrate_locked"),
            constraints.get("substrate_locked"),
        )
        locked = bool(locked_raw)
        confidence = self._num(self._first_present(
            env.get("substrate_confidence"),
            constraints.get("substrate_confidence"),
        ))
        reason = self._first_present(
            env.get("substrate_resolution_reason"),
            constraints.get("substrate_resolution_reason"),
        ) or "Motivazione non registrata"
        primary_layer = self._first_present(
            layer_decision.get("primary_layer"),
            layer_decision.get("primary"),
            env.get("environmental_pipeline"),
        )

        pipeline_by_group = {
            "rock": "geology",
            "soil": "soil",
            "moss": "soil",
            "epiphyte": "trees",
            "lignicolous": "trees",
            "unknown": "generic",
        }
        pipeline = primary_layer or pipeline_by_group.get(str(group).lower(), "generic")

        italic_used = bool(self._first_present(
            env.get("italic_profile_used"),
            env.get("italic_used"),
            constraints.get("italic_profile_used"),
        ))
        italic_role = self._first_present(
            env.get("italic_role"),
            constraints.get("italic_role"),
        )
        if not italic_role:
            italic_role = "fallback" if source == "italic_profile" else "supporto ecologico"
        italic_overrode = bool(source == "italic_profile" and not locked)

        return {
            "raw_observation": raw,
            "group": str(group),
            "source": str(source),
            "locked": locked,
            "confidence": confidence,
            "reason": str(reason),
            "pipeline": str(pipeline),
            "italic_used": italic_used,
            "italic_role": italic_role,
            "italic_overrode_substrate": italic_overrode,
            "trace_complete": source != "unknown" and str(group).lower() != "unknown",
        }

    def _ecological_resolution(self, env):
        env = env or {}
        substrate = self._substrate_resolution_from_env(env)
        habitat_observed = self._first_present(
            env.get("record_habitat_raw"),
            env.get("habitat_raw"),
            env.get("record_notes"),
        )
        habitat_interpreted = self._first_present(
            env.get("interpreted_habitat"),
            env.get("habitat_interpreted"),
            env.get("habitat"),
        )
        tree_observed = self._first_present(
            env.get("record_forophyte_raw"),
            env.get("forophyte_raw"),
            env.get("record_tree"),
        )
        tree_group = self._first_present(
            env.get("tree_group"),
            env.get("tree_type"),
            env.get("forest_type"),
        )
        rock_observed = self._first_present(
            env.get("record_rock_raw"),
            env.get("rock_raw"),
        )
        rock_group = self._first_present(
            env.get("record_rock_type"),
            env.get("rock_type"),
        )
        ph_value = self._first_present(
            env.get("soil_ph_num"),
            env.get("soil_ph"),
            env.get("soil_ph_class"),
        )
        ph_source = self._first_present(
            env.get("ph_source"),
            env.get("litho_soil_ph_match"),
            env.get("soil_confidence"),
        )

        return {
            "substrate": substrate,
            "habitat": {
                "observed": habitat_observed,
                "interpreted": habitat_interpreted,
                "score": self._num(env.get("environmental_habitat_score")),
                "reason": (env.get("environmental_reasons") or {}).get("habitat")
                if isinstance(env.get("environmental_reasons"), dict) else None,
            },
            "tree": {
                "observed": tree_observed,
                "interpreted": tree_group,
                "score": self._num(env.get("environmental_tree_score")),
                "reason": env.get("tree_match_reason"),
            },
            "lithology": {
                "observed": rock_observed,
                "interpreted": rock_group,
                "score": self._num(env.get("environmental_lithology_score")),
            },
            "ph": {
                "value": ph_value,
                "source": ph_source,
                "score": self._num(env.get("environmental_ph_score")),
                "reason": env.get("ph_reason") or env.get("soil_confidence_reason"),
            },
            "decision_graph": [
                "Specimen Label",
                "Substrate Resolution",
                "Ecological Context",
                "Layer Decision",
                "Environmental Score",
            ],
        }

    def _diagnostic_items(self, env):
        env = env or {}
        items = []
        altitude = self._num(env.get("altitude"))
        record_alt = self._num(env.get("record_altitude"))
        delta = self._num(env.get("alt_delta_m"))
        if delta is None and altitude is not None and record_alt is not None:
            delta = abs(altitude - record_alt)
        if delta is not None:
            items.append(f"Differenza di quota: {delta:.1f} m")
        if env.get("rock_type") or env.get("rock_raw"):
            items.append(f"Litologia osservata: {env.get('rock_type') or env.get('rock_raw')}")
        if env.get("substrate"):
            items.append(f"Substrato osservato: {env.get('substrate')}")
        if env.get("forest_dist_m") is not None:
            try:
                items.append(f"Distanza dalla copertura forestale: {float(env.get('forest_dist_m')):.1f} m")
            except Exception:
                pass
        constraints = str(env.get("constraints") or "").strip()
        if constraints:
            items.append(f"Vincoli: {constraints}")
        details = str(env.get("details") or "").strip()
        if details:
            items.append(f"Diagnostica: {details}")
        return items[:8]

    def build_report(self, selected_candidate, candidates, locality_context=None, uncertainty_info=None):
        selected_candidate = selected_candidate or {}
        candidates = list(candidates or [])
        selected_env = selected_candidate.get("env") or {}
        selected_rank = self._candidate_rank(selected_candidate, 1)
        selected_score = self._num(selected_candidate.get("score"), 0.0)

        ordered = sorted(
            candidates,
            key=lambda c: (self._candidate_rank(c, 10**9), -self._num(c.get("score"), 0.0)),
        )
        alternatives = [c for c in ordered if c is not selected_candidate and self._candidate_rank(c) != selected_rank]
        comparison = alternatives[0] if alternatives else None

        macro_rows = self._macro_rows(selected_env)
        env_rows = self._environment_rows(selected_env)
        substrate_resolution = self._substrate_resolution(selected_candidate, selected_env)
        main_reason = (
            "Il GSS integra quattro macro-componenti ponderate. "
            "La tabella seguente mostra i contributi effettivi senza attribuire automaticamente "
            "a una singola componente il ruolo di fattore decisivo."
        )

        comparison_rows = []
        comparison_summary = "Nessun secondo candidato disponibile per il confronto."
        comparison_rank = None
        comparison_score = None
        if comparison is not None:
            comparison_env = comparison.get("env") or {}
            comparison_rank = self._candidate_rank(comparison)
            comparison_score = self._num(comparison.get("score"), 0.0)
            other_by_key = {row["key"]: row for row in self._macro_rows(comparison_env)}
            for row in macro_rows:
                other = other_by_key.get(row["key"], {})
                comparison_rows.append({
                    "label": row["label"],
                    "selected": row["score"],
                    "other": self._num(other.get("score"), 0.0),
                    "difference": row["score"] - self._num(other.get("score"), 0.0),
                })
            decisive = max(comparison_rows, key=lambda row: abs(row["difference"])) if comparison_rows else None
            gap = selected_score - comparison_score
            if abs(gap) < 0.005:
                comparison_summary = (
                    f"Il Rank {selected_rank} e il Rank {comparison_rank} sono ecologicamente equivalenti "
                    f"(Δ GSS {gap:.2f}). Il primo posto deriva dall’ordinamento finale dei candidati, "
                    "non da una differenza sostanziale nelle macro-componenti."
                )
            else:
                comparison_summary = f"Il Rank {selected_rank} precede il Rank {comparison_rank} di {gap:.2f} punti GSS."
            if abs(gap) >= 0.005 and decisive and abs(decisive["difference"]) >= 0.05:
                direction = "favorevole" if decisive["difference"] > 0 else "sfavorevole"
                comparison_summary += (
                    f" La differenza macro più ampia è nella componente “{decisive['label']}” "
                    f"({decisive['difference']:+.1f}, {direction} al candidato selezionato)."
                )

        diagnostics = []
        for candidate in alternatives[:5]:
            score = self._num(candidate.get("score"), 0.0)
            diagnostics.append({
                "rank": self._candidate_rank(candidate),
                "score": score,
                "delta_gss": score - selected_score,
                "items": self._diagnostic_items(candidate.get("env") or {}),
            })

        ecological_resolution = self._ecological_resolution(selected_env)

        pipeline = [
            "Interpretazione semantica della località (SLGE)",
            "Risoluzione della geometria documentale e calcolo GCI",
            "Costruzione separata della geometria operativa di ricerca",
            "Risoluzione centralizzata del substrato del reperto",
            "Costruzione del contesto ecologico e scelta della pipeline ambientale",
            "Applicazione dei vincoli geografici ed ecologici",
            "Campionamento DEM e layer ambientali",
            "Calcolo delle quattro macro-componenti GSS",
            "Ordinamento dei candidati",
            "Analisi MCI e clusterizzazione SSI",
            "Calcolo separato del centro corretto e dell’incertezza GBIF",
        ]

        from .provenance_reporting_service import ProvenanceReportingService
        provenance = ProvenanceReportingService().build_provenance(
            selected_candidate, candidates, locality_context, uncertainty_info
        )

        return {
            "selected_rank": selected_rank,
            "selected_score": selected_score,
            "architecture": selected_env.get("scoring_architecture") or "4.5b.2",
            "macro_rows": macro_rows,
            "environment_rows": env_rows,
            "environment_group": selected_env.get("environmental_group") or substrate_resolution.get("group") or "unknown",
            "substrate_resolution": substrate_resolution,
            "ecological_resolution": {
                "substrate": substrate_resolution,
                "habitat_observed": selected_env.get("record_habitat") or selected_env.get("habitat_raw") or selected_env.get("habitat"),
                "habitat_interpreted": selected_env.get("interpreted_habitat") or selected_env.get("habitat_class"),
                "forophyte_observed": selected_env.get("record_forophyte") or selected_env.get("forophyte_raw"),
                "tree_group": selected_env.get("tree_type") or selected_env.get("tree_group"),
                "rock_observed": selected_env.get("record_rock") or selected_env.get("rock_raw"),
                "rock_group": selected_env.get("rock_type"),
                "ph_preference": selected_env.get("soil_ph_preference") or selected_env.get("expected_ph"),
                "ph_source": selected_env.get("ph_source") or selected_env.get("litho_soil_ph_match"),
            },
            "main_reason": main_reason,
            "selected_diagnostics": self._diagnostic_items(selected_env),
            "comparison_rank": comparison_rank,
            "comparison_score": comparison_score,
            "comparison_rows": comparison_rows,
            "comparison_summary": comparison_summary,
            "candidate_diagnostics": diagnostics,
            "pipeline": pipeline,
            "provenance": provenance,
        }
