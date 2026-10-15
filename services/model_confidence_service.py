import math


class ModelConfidenceService:
    """Calcola il Model Confidence Index (MCI) senza alterare GSS o ranking.

    L'indice descrive quanto la scelta del candidato migliore sia robusta
    rispetto alle alternative. Tutte le componenti sono normalizzate 0-1.
    """

    WEIGHTS = {
        "score_gap": 0.30,
        "spatial_concentration": 0.20,
        "data_completeness": 0.20,
        "locality_precision": 0.10,
        "classification_confidence": 0.10,
        "ecological_uniqueness": 0.10,
    }

    def evaluate(
        self,
        center_score,
        score_gap,
        features_data,
        center_point,
        distance_func,
        model_radius_m=None,
        buffer_radius_m=None,
        compatible_points=None,
        center_row=None,
        locality_context=None,
        selection_method="automatic_rank_1",
    ):
        rows = list(features_data or [])
        center_score = self._float(center_score, 0.0)
        gap = max(0.0, self._float(score_gap, 0.0))

        gap_component = 1.0 - math.exp(-gap / 8.0)
        spread_m, concentration = self._spatial_component(
            rows, center_point, distance_func, model_radius_m, buffer_radius_m
        )
        completeness, completeness_items = self._data_completeness(center_row or {})
        locality_precision = self._locality_precision(locality_context)
        class_confidence = self._classification_confidence(locality_context)
        uniqueness, equivalent_count = self._ecological_uniqueness(rows, center_score)

        components = {
            "score_gap": gap_component,
            "spatial_concentration": concentration,
            "data_completeness": completeness,
            "locality_precision": locality_precision,
            "classification_confidence": class_confidence,
            "ecological_uniqueness": uniqueness,
        }
        numeric = 100.0 * sum(
            self.WEIGHTS[name] * value for name, value in components.items()
        )

        # La selezione manuale non aumenta artificialmente la robustezza del modello.
        if str(selection_method or "").lower().startswith("manual"):
            numeric = min(numeric, 85.0)

        label = self._label(numeric)
        reasons = self._reasons(components, gap, spread_m, completeness_items, equivalent_count)
        return {
            "model_confidence": label,
            "model_confidence_class": label,
            "model_confidence_score": round(numeric, 1),
            "model_confidence_index": round(numeric, 1),
            "model_confidence_reasons": reasons,
            "model_confidence_method": "MCI_v1_weighted_multicomponent",
            "candidate_spread_m": round(spread_m, 1) if spread_m is not None else None,
            "data_completeness": round(completeness * 100.0, 1),
            "locality_precision": round(locality_precision * 100.0, 1),
            "classification_component": round(class_confidence * 100.0, 1),
            "ecological_uniqueness": round(uniqueness * 100.0, 1),
            "equivalent_candidates": int(equivalent_count),
            "confidence_components": {
                name: round(value * 100.0, 1) for name, value in components.items()
            },
        }

    def _spatial_component(self, rows, center_point, distance_func, model_radius_m, buffer_radius_m):
        distances = []
        for row in rows:
            try:
                distance = distance_func(center_point, row.get("point"))
            except Exception:
                distance = None
            if distance is not None and math.isfinite(float(distance)):
                distances.append(max(0.0, float(distance)))
        if distances:
            distances.sort()
            # Mediana: robusta rispetto ai candidati periferici isolati.
            middle = len(distances) // 2
            spread = distances[middle] if len(distances) % 2 else (distances[middle - 1] + distances[middle]) / 2.0
        else:
            spread = self._float(model_radius_m, None)
        reference = self._float(buffer_radius_m, None)
        if reference is None or reference <= 0:
            reference = max(self._float(model_radius_m, 1.0) * 4.0, 1.0)
        if spread is None:
            return None, 0.0
        concentration = math.exp(-2.5 * spread / max(reference, 1.0))
        return spread, self._clip(concentration)

    def _data_completeness(self, row):
        env = row.get("env") or {}
        constraints = row.get("constraints") or {}
        checks = {
            "quota": self._present(env.get("record_altitude")) or self._present(constraints.get("altitude_min")),
            "DEM": self._present(env.get("altitude")),
            "substrato": self._present(env.get("substrate")) or self._present(constraints.get("substrate")),
            "litologia": self._present(env.get("rock_type")) or self._present(constraints.get("rock_type")),
            "habitat": self._present(env.get("humidity")) or self._present(constraints.get("habitat")),
            "albero": self._present(env.get("tree_type")) or self._present(env.get("expected_tree")),
            "ITALIC": self._present(env.get("italic_score")) or self._present(env.get("italic_altitudinal_distribution_min")),
            "accessibilità": self._present(env.get("accessibility_score")) or self._present(env.get("trail_dist_m")),
        }
        count = sum(1 for value in checks.values() if value)
        return count / float(len(checks)), [name for name, value in checks.items() if value]

    def _locality_precision(self, context):
        locality_type = str(getattr(context, "locality_type", "unknown") or "unknown")
        values = {
            "coordinates": 1.00,
            "named_feature": 0.88,
            "near_feature": 0.72,
            "between_features": 0.68,
            "linear_feature": 0.62,
            "municipality": 0.48,
            "municipality_only": 0.32,
            "unknown": 0.20,
        }
        return values.get(locality_type, 0.35)

    def _classification_confidence(self, context):
        value = self._float(getattr(context, "classification_confidence", 0.0), 0.0)
        return self._clip(value if value <= 1.0 else value / 100.0)

    def _ecological_uniqueness(self, rows, center_score):
        scores = []
        for row in rows:
            value = self._float(row.get("score"), None)
            if value is not None:
                scores.append(value)
        if not scores:
            return 0.0, 0
        tolerance = max(2.0, abs(center_score) * 0.03)
        equivalent = sum(1 for score in scores if center_score - score <= tolerance)
        uniqueness = 1.0 / math.sqrt(max(1, equivalent))
        return self._clip(uniqueness), equivalent

    def _reasons(self, components, gap, spread_m, completeness_items, equivalent_count):
        reasons = []
        reasons.append(self._quality_reason("distacco dal secondo candidato", components["score_gap"], f"Δ GSS {gap:.1f}"))
        spread_detail = "dispersione non disponibile" if spread_m is None else f"dispersione mediana {spread_m:.0f} m"
        reasons.append(self._quality_reason("concentrazione spaziale", components["spatial_concentration"], spread_detail))
        reasons.append(self._quality_reason("completezza dei dati", components["data_completeness"], ", ".join(completeness_items) or "nessun vincolo completo"))
        reasons.append(self._quality_reason("precisione della località", components["locality_precision"]))
        reasons.append(self._quality_reason("classificazione della località", components["classification_confidence"]))
        reasons.append(self._quality_reason("unicità ecologica", components["ecological_uniqueness"], f"{equivalent_count} candidati equivalenti"))
        return reasons

    @staticmethod
    def _quality_reason(name, value, detail=""):
        if value >= 0.75:
            quality = "forte"
        elif value >= 0.50:
            quality = "moderata"
        elif value >= 0.30:
            quality = "debole"
        else:
            quality = "molto debole"
        return f"{name}: {quality}" + (f" ({detail})" if detail else "")

    @staticmethod
    def _label(value):
        if value >= 80:
            return "very_high"
        if value >= 65:
            return "high"
        if value >= 50:
            return "medium"
        if value >= 35:
            return "low"
        return "very_low"

    @staticmethod
    def _present(value):
        return value not in (None, "", [], {}, "unknown", "not_used")

    @staticmethod
    def _clip(value):
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _float(value, default=None):
        try:
            return float(value)
        except Exception:
            return default
