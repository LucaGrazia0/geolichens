"""Phase 13D.3 — integrate terrain-derived geometry into SLGE and GBIF.

This module is the only Phase 13 component allowed to replace the immutable
``DocumentedGeometry`` container held by ``ResolvedLocality``.  The operational
``SearchGeometry`` is deliberately preserved.  If terrain geometry is not
accepted automatically, the semantic geometry remains authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from .documented_geometry import DocumentedGeometry
from .resolved_locality import ResolvedLocality
from .terrain_geometry_decision_context import (
    TerrainGeometryDecision,
    TerrainGeometryDecisionResult,
)
from .terrain_geometry_validation_context import TerrainGeometryValidationResult
from .terrain_polygon_context import TerrainPolygonResult

try:
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsGeometry,
        QgsProject,
    )
except Exception:  # pragma: no cover
    QgsCoordinateReferenceSystem = None
    QgsCoordinateTransform = None
    QgsGeometry = None
    QgsProject = None


@dataclass(frozen=True)
class TerrainGeometryIntegrationResult:
    applied: bool
    selected_source: str
    documented_geometry: Optional[DocumentedGeometry]
    fallback_used: bool = False
    manual_review_required: bool = False
    confidence: float = 0.0
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "applied", bool(self.applied))
        object.__setattr__(self, "fallback_used", bool(self.fallback_used))
        object.__setattr__(self, "manual_review_required", bool(self.manual_review_required))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence or 0.0))))
        object.__setattr__(self, "reasons", tuple(str(v) for v in (self.reasons or ()) if v))
        object.__setattr__(self, "warnings", tuple(str(v) for v in (self.warnings or ()) if v))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "applied": self.applied,
            "selected_source": self.selected_source,
            "fallback_used": self.fallback_used,
            "manual_review_required": self.manual_review_required,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }


class TerrainDocumentedGeometryIntegrator:
    """Apply a Phase 13D.2 decision without changing SearchGeometry."""

    VERSION = "13.D.3.1"

    @staticmethod
    def _clone_geometry(geometry: Any) -> Any:
        if geometry is None:
            return None
        if QgsGeometry is not None:
            try:
                return QgsGeometry(geometry)
            except Exception:
                pass
        return geometry

    def _transform_geometry(self, geometry: Any, source_crs: Any, target_crs: Any) -> Any:
        clone = self._clone_geometry(geometry)
        if clone is None or source_crs is None or target_crs is None:
            return clone
        try:
            if source_crs == target_crs:
                return clone
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            clone.transform(transform)
            return clone
        except Exception:
            return None

    def integrate(
        self,
        resolved_locality: Optional[ResolvedLocality],
        polygon_result: Optional[TerrainPolygonResult],
        validation_result: Optional[TerrainGeometryValidationResult],
        decision_result: Optional[TerrainGeometryDecisionResult],
        *,
        terrain_crs: Any = None,
        documented_crs: Any = None,
        summit_result: Any = None,
        terrain_context: Any = None,
    ) -> TerrainGeometryIntegrationResult:
        provenance: Dict[str, Any] = {
            "engine": "Terrain Documented Geometry Integrator",
            "version": self.VERSION,
            "phase": "13D.3",
            "search_geometry_mutated": False,
            "gbif_source": "ResolvedLocality.documented_geometry",
        }
        if resolved_locality is None:
            return TerrainGeometryIntegrationResult(
                False, "none", None, fallback_used=True,
                manual_review_required=True,
                warnings=("ResolvedLocality non disponibile",), provenance=provenance,
            )

        semantic = resolved_locality.documented_geometry
        if decision_result is None:
            return TerrainGeometryIntegrationResult(
                False, "semantic_fallback", semantic, fallback_used=True,
                confidence=float(getattr(semantic, "confidence", 0.0) or 0.0),
                reasons=("Decisione terrain non disponibile",), provenance=provenance,
            )

        decision = decision_result.decision
        provenance["decision"] = decision.value
        provenance["decision_summary"] = decision_result.summary_dict()
        if validation_result is not None:
            provenance["validation_summary"] = validation_result.summary_dict()
        if polygon_result is not None:
            provenance["polygon_summary"] = polygon_result.summary_dict()

        if decision is not TerrainGeometryDecision.USE_TERRAIN_GEOMETRY:
            manual = decision is TerrainGeometryDecision.REQUIRE_MANUAL_REVIEW
            resolved_locality.provenance["terrain_integration"] = {
                **provenance,
                "applied": False,
                "selected_source": "semantic_fallback",
                "manual_review_required": manual,
            }
            if manual:
                resolved_locality.warnings.append(
                    "Ricostruzione terrain disponibile ma non applicata automaticamente: revisione manuale richiesta"
                )
            return TerrainGeometryIntegrationResult(
                False,
                "semantic_fallback",
                semantic,
                fallback_used=True,
                manual_review_required=manual,
                confidence=float(decision_result.confidence or getattr(semantic, "confidence", 0.0) or 0.0),
                reasons=decision_result.reasons,
                warnings=decision_result.warnings,
                provenance=provenance,
            )

        if polygon_result is None or not polygon_result.available or polygon_result.geometry is None:
            return TerrainGeometryIntegrationResult(
                False, "semantic_fallback", semantic, fallback_used=True,
                confidence=float(getattr(semantic, "confidence", 0.0) or 0.0),
                reasons=("Decisione terrain positiva ma poligono non disponibile",),
                warnings=decision_result.warnings, provenance=provenance,
            )

        target_crs = documented_crs
        if target_crs is None and QgsCoordinateReferenceSystem is not None:
            target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        terrain_geometry = self._transform_geometry(
            polygon_result.geometry, terrain_crs, target_crs
        )
        if terrain_geometry is None:
            return TerrainGeometryIntegrationResult(
                False, "semantic_fallback", semantic, fallback_used=True,
                confidence=float(getattr(semantic, "confidence", 0.0) or 0.0),
                reasons=("Trasformazione CRS del poligono terrain fallita",),
                warnings=decision_result.warnings, provenance=provenance,
            )

        metadata = dict(getattr(semantic, "metadata", {}) or {})
        metadata.update({
            "phase": "13D.3",
            "terrain_area_m2": float(polygon_result.area_m2 or 0.0),
            "terrain_area_km2": float(polygon_result.area_km2 or 0.0),
            "terrain_compactness": float(polygon_result.compactness or 0.0),
            "terrain_maximum_distance_m": float(polygon_result.maximum_distance_m or 0.0),
            "terrain_validation_confidence": float(getattr(validation_result, "confidence", 0.0) or 0.0),
            "terrain_decision_confidence": float(decision_result.confidence or 0.0),
            "semantic_fallback_source": semantic.source,
            "semantic_fallback_method": semantic.method,
        })
        selected = getattr(summit_result, "selected", None)
        if selected is not None:
            metadata.update({
                "summit_elevation_m": getattr(selected, "elevation_m", None),
                "summit_prominence_m": getattr(selected, "prominence_m", None),
                "summit_distance_from_anchor_m": getattr(selected, "distance_from_anchor_m", None),
            })
        if terrain_context is not None:
            metadata.update({
                "dem_layer_name": getattr(terrain_context, "dem_layer_name", ""),
                "dem_source": getattr(terrain_context, "dem_source", ""),
                "dem_resolution_m": getattr(terrain_context, "resolution_m", None),
                "dem_coverage_ratio": getattr(terrain_context, "coverage_ratio", None),
            })

        confidence = max(
            float(decision_result.confidence or 0.0),
            float(getattr(validation_result, "confidence", 0.0) or 0.0),
        )
        terrain_documented = DocumentedGeometry(
            geometry=terrain_geometry,
            feature_type=semantic.feature_type,
            geometry_type="POLYGON",
            source="terrain_reconstruction",
            method="dem_derived_summit_domain",
            confidence=confidence,
            estimated=True,
            requires_review=False,
            source_identifier=getattr(semantic, "source_identifier", None),
            notes=tuple(dict.fromkeys(
                tuple(getattr(semantic, "notes", ()) or ())
                + tuple(decision_result.reasons or ())
                + ("Geometria documentale sostituita automaticamente dalla ricostruzione morfologica DEM",)
            )),
            metadata=metadata,
        )

        # ResolvedLocality is mutable by design; SearchGeometry is preserved.
        search_before = resolved_locality.search_geometry
        resolved_locality.documented_geometry = terrain_documented
        resolved_locality.search_geometry = search_before
        resolved_locality.geometry_confidence = confidence
        resolved_locality.geometry_confidence_class = (
            "high" if confidence >= 0.80 else "moderate" if confidence >= 0.65 else "low"
        )
        resolved_locality.geometry_confidence_reasons = tuple(dict.fromkeys(
            tuple(resolved_locality.geometry_confidence_reasons or ())
            + tuple(decision_result.reasons or ())
            + ("Geometria derivata dal dominio sommitale DEM validato",)
        ))
        resolved_locality.provenance["terrain_integration"] = {
            **provenance,
            "applied": True,
            "selected_source": "terrain_reconstruction",
            "documented_geometry": terrain_documented.provenance_dict(),
        }

        return TerrainGeometryIntegrationResult(
            True,
            "terrain_reconstruction",
            terrain_documented,
            fallback_used=False,
            manual_review_required=False,
            confidence=confidence,
            reasons=decision_result.reasons,
            warnings=decision_result.warnings,
            provenance=provenance,
        )
