import math

from ._shared_geo_utils import to_float as _shared_to_float
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDistanceArea,
    QgsPointXY,
    QgsProject,
)


class ModelUncertaintyService:
    """Stima la concentrazione spaziale dei candidati GeoLichen.

    Questa misura descrive il comportamento del modello (R55-S70) e non deve
    essere esportata come ``coordinateUncertaintyInMeters``.
    """

    SCORE_THRESHOLD_RATIO = 0.65
    SCORE_EXPONENT = 2.0
    TARGET_WEIGHT_COVERAGE = 0.55

    def estimate(
        self,
        buffer_geom,
        features_data,
        center_point,
        center_score,
        center_row=None,
        grid_step_m=100,
    ):
        features_data = features_data or []
        grid_step_m = self._positive_float(grid_step_m, 100.0)
        buffer_radius = self._equivalent_radius_m(buffer_geom)
        candidate_resolution = max(1.0, grid_step_m / math.sqrt(2.0))
        # R55 cannot be resolved below the sampling resolution, but this lower
        # bound remains a model diagnostic and is never a Darwin Core uncertainty.
        minimum_radius = candidate_resolution

        if not features_data:
            fallback = (
                min(buffer_radius * self.MAX_MODEL_RADIUS_BUFFER_RATIO, buffer_radius)
                if buffer_radius else grid_step_m
            )
            fallback = max(minimum_radius, fallback)
            return {
                "model_radius_m": round(float(fallback), 1),
                "r55_m": None,
                "score_gap": None,
                "best_alternative_score": None,
                "compatible_points": 0,
                "points_count": 0,
                "weighted_coverage": 0.0,
                "buffer_radius_m": round(float(buffer_radius), 1) if buffer_radius else None,
                "minimum_model_radius_m": round(float(minimum_radius), 1),
                "candidate_resolution_m": round(float(candidate_resolution), 1),
                "candidate_resolution_method": "grid_step_div_sqrt_2",
                "maximum_model_radius_m": round(float(fallback), 1),
                "model_method": "selected_local_weighted_R55_S65_fallback",
            }

        center_score = self._to_float(center_score) or 0.0
        threshold = self.SCORE_THRESHOLD_RATIO * center_score
        compatible = [
            row for row in features_data
            if (self._to_float(row.get("score")) or 0.0) >= threshold
        ]
        # Scala spaziale ricavata dai candidati compatibili, non dal buffer.
        # Con passo 30 m il limite minimo resta 21,2 m e lambda non scende
        # sotto 60 m.
        distance_rows = []
        if center_point is not None:
            for row in compatible:
                distance = self.distance_m(center_point, row.get("point"))
                score = self._to_float(row.get("score"))
                if distance is None or score is None:
                    continue
                distance_rows.append((float(distance), float(score), row))
        distance_rows.sort(key=lambda item: item[0])

        distances = [item[0] for item in distance_rows]
        median_distance = self._percentile(distances, 0.50) if distances else 0.0
        lambda_m = max(grid_step_m * 2.0, median_distance)

        weighted_rows = []
        denominator_score = max(abs(center_score), 1e-9)
        for distance, score, row in distance_rows:
            score_weight = max(0.0, score / denominator_score) ** self.SCORE_EXPONENT
            distance_weight = math.exp(-distance / max(lambda_m, 1e-9))
            weighted_rows.append((distance, score_weight * distance_weight, row))

        total_weight = sum(item[1] for item in weighted_rows)
        target_weight = self.TARGET_WEIGHT_COVERAGE * total_weight
        cumulative_weight = 0.0
        r55 = None
        previous_distance = 0.0
        previous_cumulative = 0.0
        if total_weight > 0.0:
            for distance, weight, _row in weighted_rows:
                next_cumulative = cumulative_weight + weight
                if next_cumulative + 1e-12 >= target_weight:
                    if weight > 0.0 and distance > previous_distance:
                        fraction = (target_weight - previous_cumulative) / weight
                        fraction = max(0.0, min(1.0, fraction))
                        r55 = previous_distance + fraction * (distance - previous_distance)
                    else:
                        r55 = distance
                    cumulative_weight = next_cumulative
                    break
                cumulative_weight = next_cumulative
                previous_cumulative = cumulative_weight
                previous_distance = distance
        if r55 is None:
            r55 = minimum_radius

        # Limite superiore interno alla distribuzione: 90° percentile delle
        # distanze dei candidati S65. Non dipende più dalla dimensione del buffer.
        p90_distance = self._percentile(distances, 0.90) if distances else float(r55)
        maximum_radius = max(minimum_radius, p90_distance)
        model_radius = min(maximum_radius, max(minimum_radius, float(r55)))

        alternative_scores = []
        for row in features_data:
            if center_row is not None and row is center_row:
                continue
            score = self._to_float(row.get("score"))
            if score is not None:
                alternative_scores.append(score)
        best_alternative = max(alternative_scores) if alternative_scores else None
        score_gap = center_score - best_alternative if best_alternative is not None else None

        return {
            "model_radius_m": round(model_radius, 1),
            "r55_m": round(float(r55), 1),
            "score_gap": round(score_gap, 3) if score_gap is not None else None,
            "best_alternative_score": best_alternative,
            "compatible_points": len(compatible),
            "points_count": len(features_data),
            "weighted_coverage": round(
                min(1.0, cumulative_weight / total_weight) if total_weight > 0 else 0.0,
                6,
            ),
            "uncertainty_threshold": round(threshold, 3),
            "lambda_m": round(lambda_m, 1),
            "buffer_radius_m": round(buffer_radius, 1) if buffer_radius else None,
            "minimum_model_radius_m": round(minimum_radius, 1),
            "candidate_resolution_m": round(candidate_resolution, 1),
            "candidate_resolution_method": "grid_step_div_sqrt_2",
            "maximum_model_radius_m": round(maximum_radius, 1),
            "model_method": "selected_local_weighted_R55_S65_interpolated_distribution",
            "distance_scale_method": "max_2x_grid_step_or_median_distance",
            "maximum_radius_method": "compatible_distance_p90",
            "median_compatible_distance_m": round(median_distance, 1) if distances else None,
            "p90_compatible_distance_m": round(p90_distance, 1) if distances else None,
        }

    def confidence(self, center_score, score_gap, compatible_points, model_radius_m, buffer_radius_m):
        score_strength = max(0.0, min(1.0, float(center_score or 0.0) / 100.0))
        gap_strength = max(0.0, min(1.0, float(score_gap or 0.0) / 15.0))
        uniqueness = 1.0 / math.sqrt(max(1, int(compatible_points or 1)))
        if model_radius_m is not None and buffer_radius_m:
            concentration = math.exp(-float(model_radius_m) / max(float(buffer_radius_m), 1.0))
        else:
            concentration = 0.0
        numeric = 100.0 * (
            0.35 * score_strength
            + 0.30 * gap_strength
            + 0.20 * uniqueness
            + 0.15 * concentration
        )
        if numeric >= 80:
            label = "very_high"
        elif numeric >= 65:
            label = "high"
        elif numeric >= 45:
            label = "medium"
        elif numeric >= 25:
            label = "low"
        else:
            label = "very_low"
        return {"model_confidence": label, "model_confidence_score": round(numeric, 1)}

    def distance_m(self, pt1_wgs84, pt2_wgs84):
        try:
            if not pt1_wgs84 or not pt2_wgs84:
                return None
            distance = QgsDistanceArea()
            distance.setSourceCrs(
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsProject.instance().transformContext(),
            )
            distance.setEllipsoid("WGS84")
            return float(distance.measureLine(QgsPointXY(pt1_wgs84), QgsPointXY(pt2_wgs84)))
        except Exception:
            return None

    def _equivalent_radius_m(self, geom_wgs84):
        try:
            if geom_wgs84 is None or geom_wgs84.isEmpty():
                return None
            centroid = geom_wgs84.centroid().asPoint()
            distance = QgsDistanceArea()
            distance.setSourceCrs(
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsProject.instance().transformContext(),
            )
            distance.setEllipsoid("WGS84")
            area = float(distance.measureArea(geom_wgs84))
            return math.sqrt(area / math.pi) if area > 0 else None
        except Exception:
            return None


    @staticmethod
    def _percentile(values, quantile):
        """Percentile lineare per una sequenza numerica già o non già ordinata."""
        clean = sorted(float(value) for value in values if value is not None)
        if not clean:
            return 0.0
        if len(clean) == 1:
            return clean[0]
        q = max(0.0, min(1.0, float(quantile)))
        position = q * (len(clean) - 1)
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return clean[lower]
        fraction = position - lower
        return clean[lower] + fraction * (clean[upper] - clean[lower])

    @staticmethod
    def _to_float(value):
        return _shared_to_float(value)

    @classmethod
    def _positive_float(cls, value, default):
        parsed = cls._to_float(value)
        return parsed if parsed is not None and parsed > 0 else float(default)
