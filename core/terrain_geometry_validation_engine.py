"""Phase 13D.1 — validation of terrain-derived mountain polygons.

This engine performs the safety gate between reconstruction (13C) and the
future decision/integration stages (13D.2–13D.4).  It never replaces the
DocumentedGeometry and never changes the GBIF uncertainty.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .summit_context import SummitDetectionResult
from .terrain_context import TerrainContext
from .terrain_geometry_validation_context import (
    TerrainGeometryCheck,
    TerrainGeometryValidationResult,
)
from .terrain_polygon_context import TerrainPolygonResult

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:  # QGIS remains optional for isolated tests.
    from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes
except Exception:  # pragma: no cover
    QgsGeometry = None
    QgsPointXY = None
    QgsWkbTypes = None


class TerrainGeometryValidationEngine:
    """Validate the Phase 13C polygon with explicit, traceable rules."""

    VERSION = "13.D.1.1"

    def __init__(
        self,
        *,
        minimum_area_m2: float = 30_000.0,
        maximum_area_m2: float = 12_000_000.0,
        minimum_compactness: float = 0.06,
        preferred_compactness: float = 0.12,
        minimum_dem_coverage: float = 0.80,
        preferred_dem_coverage: float = 0.95,
        minimum_summit_confidence: float = 0.55,
        minimum_polygon_confidence: float = 0.58,
        maximum_distance_m: float = 1_800.0,
        maximum_edge_fraction: float = 0.02,
        minimum_valid_cell_count: int = 4,
        acceptance_confidence: float = 0.62,
        manual_review_confidence: float = 0.78,
    ) -> None:
        self.minimum_area_m2 = max(0.0, float(minimum_area_m2))
        self.maximum_area_m2 = max(self.minimum_area_m2, float(maximum_area_m2))
        self.minimum_compactness = max(0.0, min(1.0, float(minimum_compactness)))
        self.preferred_compactness = max(self.minimum_compactness, min(1.0, float(preferred_compactness)))
        self.minimum_dem_coverage = max(0.0, min(1.0, float(minimum_dem_coverage)))
        self.preferred_dem_coverage = max(self.minimum_dem_coverage, min(1.0, float(preferred_dem_coverage)))
        self.minimum_summit_confidence = max(0.0, min(1.0, float(minimum_summit_confidence)))
        self.minimum_polygon_confidence = max(0.0, min(1.0, float(minimum_polygon_confidence)))
        self.maximum_distance_m = max(1.0, float(maximum_distance_m))
        self.maximum_edge_fraction = max(0.0, min(1.0, float(maximum_edge_fraction)))
        self.minimum_valid_cell_count = max(1, int(minimum_valid_cell_count))
        self.acceptance_confidence = max(0.0, min(1.0, float(acceptance_confidence)))
        self.manual_review_confidence = max(self.acceptance_confidence, min(1.0, float(manual_review_confidence)))

    @staticmethod
    def _linear_score(value: float, minimum: float, preferred: float) -> float:
        if value < minimum:
            return 0.0
        if preferred <= minimum or value >= preferred:
            return 1.0
        return (value - minimum) / (preferred - minimum)

    @staticmethod
    def _range_score(value: float, minimum: float, maximum: float) -> float:
        if value < minimum or value > maximum:
            return 0.0
        midpoint = (minimum + maximum) / 2.0
        half = max((maximum - minimum) / 2.0, 1e-9)
        return max(0.55, 1.0 - 0.45 * abs(value - midpoint) / half)

    @staticmethod
    def _summit_point(summit_result: SummitDetectionResult) -> Any:
        selected = getattr(summit_result, "selected", None)
        return getattr(selected, "point", None) if selected is not None else None

    @staticmethod
    def _geometry_is_valid(geometry: Any) -> Tuple[bool, str]:
        if geometry is None:
            return False, "Geometria poligonale non disponibile"
        try:
            if geometry.isEmpty():
                return False, "Geometria vuota"
        except Exception:
            return False, "Oggetto geometrico non interpretabile"
        try:
            if not geometry.isGeosValid():
                return False, "Geometria GEOS non valida"
        except Exception:
            # Some QGIS/test doubles do not implement isGeosValid.
            pass
        if QgsWkbTypes is not None:
            try:
                if QgsWkbTypes.geometryType(geometry.wkbType()) != QgsWkbTypes.PolygonGeometry:
                    return False, "La geometria non è poligonale"
            except Exception:
                pass
        return True, "Geometria valida"

    @staticmethod
    def _geometry_part_count(geometry: Any) -> int:
        if geometry is None:
            return 0
        try:
            if not geometry.isMultipart():
                return 1
            parts = geometry.asGeometryCollection()
            return len(parts)
        except Exception:
            return 1

    @staticmethod
    def _contains_summit(geometry: Any, summit_point: Any, mask: Any, summit_result: SummitDetectionResult) -> bool:
        if geometry is not None and summit_point is not None:
            try:
                point_geometry = QgsGeometry.fromPointXY(summit_point) if QgsGeometry is not None else summit_point
                return bool(geometry.contains(point_geometry) or geometry.intersects(point_geometry))
            except Exception:
                pass
        if np is not None and mask is not None and summit_result and summit_result.selected is not None:
            try:
                row = int(summit_result.selected.row)
                col = int(summit_result.selected.col)
                array = np.asarray(mask, dtype=bool)
                return bool(0 <= row < array.shape[0] and 0 <= col < array.shape[1] and array[row, col])
            except Exception:
                pass
        return False

    @staticmethod
    def _edge_fraction(mask: Any) -> float:
        if np is None or mask is None:
            return 1.0
        try:
            array = np.asarray(mask, dtype=bool)
            total = int(array.sum())
            if total <= 0:
                return 1.0
            edge = np.zeros_like(array, dtype=bool)
            edge[0, :] = True
            edge[-1, :] = True
            edge[:, 0] = True
            edge[:, -1] = True
            return float((array & edge).sum()) / float(total)
        except Exception:
            return 1.0

    def validate(
        self,
        terrain: TerrainContext,
        summit_result: SummitDetectionResult,
        polygon_result: TerrainPolygonResult,
    ) -> TerrainGeometryValidationResult:
        provenance: Dict[str, Any] = {
            "engine": "Terrain Geometry Validation Engine",
            "version": self.VERSION,
            "phase": "13D.1",
            "geometry_mutation": False,
            "documented_geometry_updated": False,
            "gbif_uncertainty_updated": False,
        }

        if terrain is None or not terrain.available:
            return TerrainGeometryValidationResult.unavailable("TerrainContext non disponibile", provenance=provenance)
        if summit_result is None or not summit_result.available or summit_result.selected is None:
            return TerrainGeometryValidationResult.unavailable("SummitDetectionResult non disponibile", provenance=provenance)
        if polygon_result is None or not polygon_result.available:
            warnings = list(getattr(polygon_result, "warnings", ()) or ())
            return TerrainGeometryValidationResult.unavailable(
                "TerrainPolygonResult non disponibile",
                *warnings,
                provenance=provenance,
            )

        checks: List[TerrainGeometryCheck] = []
        warnings: List[str] = list(polygon_result.warnings or ())

        geometry_valid, geometry_message = self._geometry_is_valid(polygon_result.geometry)
        # Outside QGIS, a valid numerical mask is sufficient for diagnostic tests.
        mask_available = False
        if np is not None and polygon_result.mask is not None:
            try:
                mask_available = int(np.asarray(polygon_result.mask, dtype=bool).sum()) >= self.minimum_valid_cell_count
            except Exception:
                mask_available = False
        polygon_representation_valid = geometry_valid if QgsGeometry is not None else mask_available
        checks.append(TerrainGeometryCheck(
            "polygon_representation",
            polygon_representation_valid,
            required=True,
            value="geometry" if geometry_valid else ("mask" if mask_available else "missing"),
            threshold="valid polygon or testable raster mask",
            score=1.0 if polygon_representation_valid else 0.0,
            message=geometry_message if QgsGeometry is not None else ("Maschera raster disponibile" if mask_available else "Maschera raster non disponibile"),
        ))

        contains_summit = self._contains_summit(
            polygon_result.geometry,
            self._summit_point(summit_result),
            polygon_result.mask,
            summit_result,
        )
        checks.append(TerrainGeometryCheck(
            "summit_contained",
            contains_summit,
            required=True,
            value=contains_summit,
            threshold=True,
            score=1.0 if contains_summit else 0.0,
            message="La cima ricade nel dominio" if contains_summit else "La cima non ricade nel dominio",
        ))

        area = float(polygon_result.area_m2 or 0.0)
        area_ok = self.minimum_area_m2 <= area <= self.maximum_area_m2
        checks.append(TerrainGeometryCheck(
            "plausible_area",
            area_ok,
            required=True,
            value=area,
            threshold=(self.minimum_area_m2, self.maximum_area_m2),
            score=self._range_score(area, self.minimum_area_m2, self.maximum_area_m2),
            message=f"Area {area / 1_000_000.0:.3f} km²",
        ))

        compactness = float(polygon_result.compactness or 0.0)
        compactness_ok = compactness >= self.minimum_compactness
        checks.append(TerrainGeometryCheck(
            "compactness",
            compactness_ok,
            required=True,
            value=compactness,
            threshold=self.minimum_compactness,
            score=self._linear_score(compactness, self.minimum_compactness, self.preferred_compactness),
            message=f"Compattezza {compactness:.3f}",
        ))

        coverage = float(terrain.coverage_ratio or 0.0)
        coverage_ok = coverage >= self.minimum_dem_coverage
        checks.append(TerrainGeometryCheck(
            "dem_coverage",
            coverage_ok,
            required=True,
            value=coverage,
            threshold=self.minimum_dem_coverage,
            score=self._linear_score(coverage, self.minimum_dem_coverage, self.preferred_dem_coverage),
            message=f"Copertura DEM {coverage * 100.0:.1f}%",
        ))

        summit_confidence = float(summit_result.confidence or 0.0)
        summit_ok = summit_confidence >= self.minimum_summit_confidence and not summit_result.fallback_required
        checks.append(TerrainGeometryCheck(
            "summit_confidence",
            summit_ok,
            required=True,
            value=summit_confidence,
            threshold=self.minimum_summit_confidence,
            score=self._linear_score(summit_confidence, self.minimum_summit_confidence, 0.85),
            message=f"Confidenza cima {summit_confidence * 100.0:.1f}%",
        ))

        polygon_confidence = float(polygon_result.confidence or 0.0)
        polygon_confidence_ok = polygon_confidence >= self.minimum_polygon_confidence and not polygon_result.fallback_required
        checks.append(TerrainGeometryCheck(
            "polygon_confidence",
            polygon_confidence_ok,
            required=True,
            value=polygon_confidence,
            threshold=self.minimum_polygon_confidence,
            score=self._linear_score(polygon_confidence, self.minimum_polygon_confidence, 0.85),
            message=f"Confidenza poligono {polygon_confidence * 100.0:.1f}%",
        ))

        maximum_distance = float(polygon_result.maximum_distance_m or 0.0)
        distance_ok = maximum_distance <= self.maximum_distance_m
        distance_score = 1.0 if maximum_distance <= self.maximum_distance_m * 0.75 else max(
            0.0,
            (self.maximum_distance_m - maximum_distance) / max(self.maximum_distance_m * 0.25, 1.0),
        )
        checks.append(TerrainGeometryCheck(
            "maximum_distance",
            distance_ok,
            required=True,
            value=maximum_distance,
            threshold=self.maximum_distance_m,
            score=distance_score,
            message=f"Distanza massima dalla cima {maximum_distance:.1f} m",
        ))

        edge_fraction = self._edge_fraction(polygon_result.mask)
        edge_ok = edge_fraction <= self.maximum_edge_fraction and "touches_dem_edge" not in polygon_result.quality_flags
        checks.append(TerrainGeometryCheck(
            "dem_edge_contact",
            edge_ok,
            required=True,
            value=edge_fraction,
            threshold=self.maximum_edge_fraction,
            score=1.0 if edge_fraction <= 0.0 else max(0.0, 1.0 - edge_fraction / max(self.maximum_edge_fraction, 1e-9)),
            message=("Il dominio non raggiunge il bordo DEM" if edge_ok else f"Contatto col bordo DEM: {edge_fraction * 100.0:.2f}% delle celle"),
        ))

        part_count = self._geometry_part_count(polygon_result.geometry) if polygon_result.geometry is not None else 1
        single_part = part_count == 1
        checks.append(TerrainGeometryCheck(
            "single_component",
            single_part,
            required=False,
            value=part_count,
            threshold=1,
            score=1.0 if single_part else max(0.0, 1.0 / float(part_count)),
            message="Dominio continuo" if single_part else f"Dominio composto da {part_count} parti",
        ))

        failed_required = tuple(check.name for check in checks if check.required and not check.passed)
        required_checks = [check for check in checks if check.required]
        optional_checks = [check for check in checks if not check.required]
        required_score = sum(check.score for check in required_checks) / max(1, len(required_checks))
        optional_score = sum(check.score for check in optional_checks) / max(1, len(optional_checks))
        confidence = 0.90 * required_score + 0.10 * optional_score
        # Retain the confidence produced by the two upstream stages without
        # allowing it to hide a failed safety requirement.
        confidence *= 0.75 + 0.25 * min(summit_confidence, polygon_confidence)
        confidence = max(0.0, min(1.0, confidence))

        valid = not failed_required and confidence >= self.acceptance_confidence
        fallback_required = not valid
        manual_review = valid and confidence < self.manual_review_confidence
        if failed_required:
            warnings.append("Controlli obbligatori falliti: " + ", ".join(failed_required))
        if manual_review:
            warnings.append("Geometria valida ma revisione manuale consigliata")

        provenance.update({
            "acceptance_confidence": self.acceptance_confidence,
            "manual_review_confidence": self.manual_review_confidence,
            "required_score": required_score,
            "optional_score": optional_score,
            "validation_confidence": confidence,
            "failed_required_checks": list(failed_required),
            "upstream_polygon_quality_flags": list(polygon_result.quality_flags or ()),
            "upstream_polygon_fallback_required": bool(polygon_result.fallback_required),
            "upstream_summit_fallback_required": bool(summit_result.fallback_required),
        })

        return TerrainGeometryValidationResult(
            available=True,
            valid=valid,
            confidence=confidence,
            fallback_required=fallback_required,
            manual_review_recommended=manual_review,
            checks=tuple(checks),
            failed_required_checks=failed_required,
            warnings=tuple(dict.fromkeys(str(value) for value in warnings if value)),
            provenance=provenance,
        )
