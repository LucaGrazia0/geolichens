"""Phase 13B — DEM-based summit detection.

The engine consumes the local ``TerrainContext`` prepared in Phase 13A,
extracts local maxima, estimates local prominence and isolation, and ranks the
maxima against the geocoder anchor and an optional record altitude.

It is intentionally non-invasive. The selected summit is diagnostic input for
Phase 13C and does not alter DocumentedGeometry, SearchGeometry, GBIF
uncertainty, GSS, heatmap or candidate ranking.
"""
from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence, Tuple

from .summit_context import SummitCandidate, SummitDetectionResult
from .terrain_context import TerrainContext

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:  # QGIS is optional for external tests.
    from qgis.core import QgsPointXY
except Exception:  # pragma: no cover
    QgsPointXY = None


class SummitDetectionEngine:
    """Identify and rank candidate summits in a prepared DEM window."""

    VERSION = "13.B.1"

    def __init__(
        self,
        *,
        neighbourhood_m: float = 120.0,
        prominence_radius_m: float = 350.0,
        minimum_prominence_m: float = 8.0,
        maximum_anchor_distance_m: Optional[float] = None,
        max_candidates: int = 12,
    ) -> None:
        self.neighbourhood_m = max(10.0, float(neighbourhood_m))
        self.prominence_radius_m = max(self.neighbourhood_m, float(prominence_radius_m))
        self.minimum_prominence_m = max(0.0, float(minimum_prominence_m))
        self.maximum_anchor_distance_m = (
            max(1.0, float(maximum_anchor_distance_m))
            if maximum_anchor_distance_m is not None
            else None
        )
        self.max_candidates = max(1, int(max_candidates))

    @staticmethod
    def _point_xy(point: Any) -> Tuple[float, float]:
        try:
            return float(point.x()), float(point.y())
        except Exception:
            return float(point[0]), float(point[1])

    @staticmethod
    def _grid_point(context: TerrainContext, row: int, col: int) -> Any:
        extent = context.extent
        grid = context.grid
        x = float(extent.xMinimum()) + (float(col) + 0.5) * float(grid.pixel_size_x)
        y = float(extent.yMaximum()) - (float(row) + 0.5) * abs(float(grid.pixel_size_y))
        return QgsPointXY(x, y) if QgsPointXY is not None else (x, y)

    @staticmethod
    def _distance_m(context: TerrainContext, point_a: Any, point_b: Any) -> float:
        ax, ay = SummitDetectionEngine._point_xy(point_a)
        bx, by = SummitDetectionEngine._point_xy(point_b)
        # TerrainPreparationEngine currently prepares the local window in the
        # DEM CRS. Most production DEMs are metric. For geographic CRSs use a
        # local equirectangular approximation to keep the detector deterministic.
        try:
            geographic = bool(context.crs.isGeographic())
        except Exception:
            geographic = False
        if geographic:
            mean_lat = math.radians((ay + by) * 0.5)
            dx = (ax - bx) * 111_320.0 * max(0.01, math.cos(mean_lat))
            dy = (ay - by) * 110_540.0
            return math.hypot(dx, dy)
        return math.hypot(ax - bx, ay - by)

    @staticmethod
    def _maximum_filter(values: Any, radius_rows: int, radius_cols: int) -> Any:
        """NumPy-only maximum filter, avoiding a SciPy dependency in QGIS."""
        padded = np.pad(values, ((radius_rows, radius_rows), (radius_cols, radius_cols)), constant_values=-np.inf)
        result = np.full_like(values, -np.inf, dtype=float)
        height, width = values.shape
        for dy in range(2 * radius_rows + 1):
            for dx in range(2 * radius_cols + 1):
                result = np.maximum(result, padded[dy : dy + height, dx : dx + width])
        return result

    @staticmethod
    def _disk_values(values: Any, valid: Any, row: int, col: int, rr: int, rc: int) -> Any:
        r0, r1 = max(0, row - rr), min(values.shape[0], row + rr + 1)
        c0, c1 = max(0, col - rc), min(values.shape[1], col + rc + 1)
        sub = values[r0:r1, c0:c1]
        mask = valid[r0:r1, c0:c1].copy()
        yy, xx = np.ogrid[r0:r1, c0:c1]
        ellipse = ((yy - row) / max(1.0, float(rr))) ** 2 + ((xx - col) / max(1.0, float(rc))) ** 2 <= 1.0
        return sub[mask & ellipse]

    def _local_prominence(self, elevation: Any, valid: Any, row: int, col: int, rr: int, rc: int) -> float:
        values = self._disk_values(elevation, valid, row, col, rr, rc)
        if values.size < 5:
            return 0.0
        peak = float(elevation[row, col])
        # The 20th percentile approximates the local shoulder/base while being
        # less sensitive than the minimum to deep ravines and NoData borders.
        shoulder = float(np.nanpercentile(values, 20.0))
        return max(0.0, peak - shoulder)

    @staticmethod
    def _isolation(candidates_rcz: Sequence[Tuple[int, int, float]], index: int, px: float, py: float) -> float:
        row, col, elevation = candidates_rcz[index]
        distances = []
        for j, (other_row, other_col, other_elevation) in enumerate(candidates_rcz):
            if j == index or other_elevation <= elevation:
                continue
            distances.append(math.hypot((other_col - col) * px, (other_row - row) * py))
        return min(distances) if distances else float("inf")

    @staticmethod
    def _normalise(value: float, low: float, high: float) -> float:
        if high <= low:
            return 1.0 if value >= high else 0.0
        return max(0.0, min(1.0, (value - low) / (high - low)))

    def detect(
        self,
        terrain: TerrainContext,
        *,
        anchor_point: Any = None,
        record_elevation_m: Optional[float] = None,
    ) -> SummitDetectionResult:
        provenance = {
            "engine": "Summit Detection Engine",
            "version": self.VERSION,
            "geometry_mutation": False,
            "input": "TerrainContext",
            "method": "local_maxima_prominence_isolation_ranking",
        }
        if np is None:
            return SummitDetectionResult.unavailable("NumPy non disponibile", provenance=provenance)
        if terrain is None or not terrain.available or terrain.grid is None:
            return SummitDetectionResult.unavailable("TerrainContext non disponibile", provenance=provenance)

        grid = terrain.grid
        elevation = np.asarray(grid.elevation, dtype=float)
        valid = np.asarray(grid.valid_mask, dtype=bool) & np.isfinite(elevation)
        if elevation.ndim != 2 or valid.shape != elevation.shape or int(valid.sum()) < 9:
            return SummitDetectionResult.unavailable("Griglia DEM insufficiente per rilevare una cima", provenance=provenance)

        anchor = anchor_point if anchor_point is not None else terrain.center
        if anchor is None:
            return SummitDetectionResult.unavailable("Punto geocodificato assente", provenance=provenance)

        px = max(1e-9, abs(float(grid.pixel_size_x)))
        py = max(1e-9, abs(float(grid.pixel_size_y)))
        local_rr = max(1, int(math.ceil(self.neighbourhood_m / py)))
        local_rc = max(1, int(math.ceil(self.neighbourhood_m / px)))
        prom_rr = max(local_rr + 1, int(math.ceil(self.prominence_radius_m / py)))
        prom_rc = max(local_rc + 1, int(math.ceil(self.prominence_radius_m / px)))

        work = np.where(valid, elevation, -np.inf)
        local_max = self._maximum_filter(work, local_rr, local_rc)
        maxima_mask = valid & np.isclose(work, local_max, rtol=0.0, atol=1e-8)

        # Collapse flat summit plateaus to one representative cell: highest
        # profile curvature, then nearest to the anchor.
        raw_rows, raw_cols = np.where(maxima_mask)
        raw = []
        max_anchor_distance = self.maximum_anchor_distance_m or max(500.0, float(terrain.radius_m))
        for row, col in zip(raw_rows.tolist(), raw_cols.tolist()):
            point = self._grid_point(terrain, row, col)
            distance = self._distance_m(terrain, point, anchor)
            if distance <= max_anchor_distance:
                raw.append((row, col, float(elevation[row, col]), point, distance))
        if not raw:
            return SummitDetectionResult.unavailable("Nessun massimo locale vicino alla località", provenance=provenance)

        # Non-maximum suppression in physical space removes multiple pixels on
        # the same broad summit or plateau.
        raw.sort(key=lambda item: (-item[2], item[4]))
        retained = []
        suppression_m = max(self.neighbourhood_m, 2.0 * max(px, py))
        for item in raw:
            if any(self._distance_m(terrain, item[3], previous[3]) < suppression_m for previous in retained):
                continue
            retained.append(item)

        rcz = [(item[0], item[1], item[2]) for item in retained]
        elevations = [item[2] for item in retained]
        z_min, z_max = min(elevations), max(elevations)
        candidates: List[SummitCandidate] = []
        warnings: List[str] = []
        anchor_elevation = None
        try:
            ax, ay = self._point_xy(anchor)
            # Anchor elevation is diagnostic only; nearest grid cell lookup.
            col = int((ax - float(terrain.extent.xMinimum())) / px)
            row = int((float(terrain.extent.yMaximum()) - ay) / py)
            if 0 <= row < elevation.shape[0] and 0 <= col < elevation.shape[1] and valid[row, col]:
                anchor_elevation = float(elevation[row, col])
        except Exception:
            pass

        for index, (row, col, z, point, distance) in enumerate(retained):
            prominence = self._local_prominence(elevation, valid, row, col, prom_rr, prom_rc)
            if prominence < self.minimum_prominence_m:
                continue
            isolation = self._isolation(rcz, index, px, py)
            finite_isolation = max_anchor_distance if not math.isfinite(isolation) else isolation
            slope_context = float(grid.slope_degrees[row, col]) if grid.slope_degrees is not None else 0.0
            profile_curvature = float(grid.profile_curvature[row, col]) if grid.profile_curvature is not None else 0.0

            proximity_score = 1.0 - min(1.0, distance / max_anchor_distance)
            prominence_score = self._normalise(prominence, self.minimum_prominence_m, max(60.0, self.minimum_prominence_m + 120.0))
            isolation_score = self._normalise(finite_isolation, suppression_m, max(500.0, self.prominence_radius_m * 3.0))
            relative_height_score = self._normalise(z, z_min, z_max)
            altitude_score = 0.5
            altitude_delta = None
            if record_elevation_m is not None:
                altitude_delta = abs(float(record_elevation_m) - z)
                altitude_score = math.exp(-altitude_delta / 180.0)

            # Anchor proximity has the largest weight: the highest point in a
            # broad DEM window is not automatically the named summit.
            score_01 = (
                0.36 * proximity_score
                + 0.23 * prominence_score
                + 0.14 * isolation_score
                + 0.12 * relative_height_score
                + 0.15 * altitude_score
            )
            score = 100.0 * score_01
            reasons = [
                f"distanza dal punto geocodificato {distance:.0f} m",
                f"prominenza locale stimata {prominence:.0f} m",
            ]
            if math.isfinite(isolation):
                reasons.append(f"isolamento da cime più alte {isolation:.0f} m")
            else:
                reasons.append("nessuna cima più alta nella finestra DEM")
            if altitude_delta is not None:
                reasons.append(f"scarto dalla quota del record {altitude_delta:.0f} m")

            candidates.append(
                SummitCandidate(
                    point=point,
                    row=row,
                    col=col,
                    elevation_m=z,
                    distance_from_anchor_m=distance,
                    prominence_m=prominence,
                    isolation_m=finite_isolation,
                    slope_context_deg=slope_context,
                    profile_curvature=profile_curvature,
                    score=score,
                    confidence=score_01,
                    reasons=tuple(reasons),
                )
            )

        if not candidates:
            return SummitDetectionResult.unavailable(
                "I massimi locali non superano la prominenza minima",
                provenance=provenance,
            )

        candidates.sort(key=lambda c: (-c.score, c.distance_from_anchor_m, -c.elevation_m))
        candidates = candidates[: self.max_candidates]
        selected = candidates[0]
        gap = selected.score - candidates[1].score if len(candidates) > 1 else selected.score
        ambiguous = len(candidates) > 1 and gap < 7.0

        confidence = selected.confidence
        if ambiguous:
            confidence *= 0.82
            warnings.append(f"Cima ambigua: differenza tra i primi due candidati {gap:.1f} punti")
        if terrain.coverage_ratio < 0.8:
            confidence *= max(0.5, terrain.coverage_ratio / 0.8)
            warnings.append("Confidenza ridotta per copertura DEM parziale")
        edge_margin = max(local_rr, local_rc)
        if (
            selected.row < edge_margin
            or selected.col < edge_margin
            or selected.row >= grid.height - edge_margin
            or selected.col >= grid.width - edge_margin
        ):
            confidence *= 0.75
            warnings.append("Cima prossima al bordo della finestra DEM")

        confidence = max(0.0, min(1.0, confidence))
        fallback_required = confidence < 0.55 or ambiguous and confidence < 0.65
        provenance.update(
            {
                "neighbourhood_m": self.neighbourhood_m,
                "prominence_radius_m": self.prominence_radius_m,
                "minimum_prominence_m": self.minimum_prominence_m,
                "maximum_anchor_distance_m": max_anchor_distance,
                "candidate_count_before_limit": len(candidates),
                "score_gap": gap,
                "fallback_threshold": 0.55,
            }
        )
        return SummitDetectionResult(
            available=True,
            selected=selected,
            candidates=tuple(candidates),
            anchor_point=anchor,
            anchor_elevation_m=anchor_elevation,
            record_elevation_m=record_elevation_m,
            confidence=confidence,
            ambiguous=ambiguous,
            fallback_required=fallback_required,
            warnings=tuple(warnings),
            provenance=provenance,
        )
