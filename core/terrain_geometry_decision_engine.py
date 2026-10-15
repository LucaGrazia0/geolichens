"""Phase 13D.2 — decision engine for terrain-derived documentary geometry.

The engine consumes the semantic DocumentedGeometry, the Phase 13C polygon and
its Phase 13D.1 validation result.  It emits a transparent decision only; it
never replaces DocumentedGeometry and never changes the GBIF calculation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .documented_geometry import DocumentedGeometry
from .terrain_geometry_decision_context import (
    TerrainGeometryDecision,
    TerrainGeometryDecisionResult,
)
from .terrain_geometry_validation_context import TerrainGeometryValidationResult
from .terrain_polygon_context import TerrainPolygonResult


class TerrainGeometryDecisionEngine:
    """Choose terrain geometry, semantic fallback, or manual review."""

    VERSION = "13.D.2.1"

    def __init__(
        self,
        *,
        automatic_terrain_confidence: float = 0.80,
        manual_review_confidence: float = 0.62,
        minimum_gain_over_semantic: float = 0.05,
        maximum_automatic_area_ratio: float = 6.0,
        minimum_automatic_area_ratio: float = 0.15,
    ) -> None:
        self.automatic_terrain_confidence = max(0.0, min(1.0, float(automatic_terrain_confidence)))
        self.manual_review_confidence = max(0.0, min(self.automatic_terrain_confidence, float(manual_review_confidence)))
        self.minimum_gain_over_semantic = max(-1.0, min(1.0, float(minimum_gain_over_semantic)))
        self.maximum_automatic_area_ratio = max(1.0, float(maximum_automatic_area_ratio))
        self.minimum_automatic_area_ratio = max(0.0, min(1.0, float(minimum_automatic_area_ratio)))

    @staticmethod
    def _geometry_available(documented: Optional[DocumentedGeometry]) -> bool:
        return bool(documented is not None and documented.is_available)

    @staticmethod
    def _geometry_area_m2(geometry: Any) -> Optional[float]:
        if geometry is None:
            return None
        try:
            area = float(geometry.area())
            return area if area > 0.0 else None
        except Exception:
            return None

    def decide(
        self,
        documented_geometry: Optional[DocumentedGeometry],
        polygon_result: Optional[TerrainPolygonResult],
        validation_result: Optional[TerrainGeometryValidationResult],
    ) -> TerrainGeometryDecisionResult:
        provenance: Dict[str, Any] = {
            "engine": "Terrain Geometry Decision Engine",
            "version": self.VERSION,
            "phase": "13D.2",
            "geometry_mutation": False,
            "documented_geometry_updated": False,
            "gbif_uncertainty_updated": False,
            "thresholds": {
                "automatic_terrain_confidence": self.automatic_terrain_confidence,
                "manual_review_confidence": self.manual_review_confidence,
                "minimum_gain_over_semantic": self.minimum_gain_over_semantic,
                "minimum_automatic_area_ratio": self.minimum_automatic_area_ratio,
                "maximum_automatic_area_ratio": self.maximum_automatic_area_ratio,
            },
        }
        reasons: List[str] = []
        warnings: List[str] = []
        semantic_available = self._geometry_available(documented_geometry)
        semantic_confidence = float(getattr(documented_geometry, "confidence", 0.0) or 0.0)
        semantic_area = self._geometry_area_m2(getattr(documented_geometry, "geometry", None))

        if validation_result is None or not validation_result.available:
            reasons.append("Validazione terrain non disponibile")
            if semantic_available:
                reasons.append("Mantenuta la geometria documentale semantica disponibile")
            else:
                warnings.append("Nessuna geometria documentale semantica disponibile")
            return TerrainGeometryDecisionResult(
                available=False,
                decision=TerrainGeometryDecision.USE_SEMANTIC_FALLBACK,
                confidence=semantic_confidence,
                automatic=True,
                terrain_eligible=False,
                semantic_fallback_available=semantic_available,
                reasons=tuple(reasons),
                warnings=tuple(warnings),
                metrics={"semantic_confidence": semantic_confidence},
                provenance=provenance,
            )

        terrain_available = bool(
            polygon_result is not None
            and polygon_result.available
            and polygon_result.geometry is not None
            and not polygon_result.fallback_required
        )
        terrain_confidence = float(validation_result.confidence or 0.0)
        terrain_area = float(getattr(polygon_result, "area_m2", 0.0) or 0.0)
        confidence_gain = terrain_confidence - semantic_confidence
        area_ratio = None
        if semantic_area and semantic_area > 0.0:
            area_ratio = terrain_area / semantic_area

        metrics: Dict[str, Any] = {
            "terrain_available": terrain_available,
            "terrain_validation_valid": bool(validation_result.valid),
            "terrain_validation_confidence": terrain_confidence,
            "terrain_area_m2": terrain_area,
            "semantic_available": semantic_available,
            "semantic_confidence": semantic_confidence,
            "semantic_area_m2": semantic_area,
            "confidence_gain_over_semantic": confidence_gain,
            "area_ratio_terrain_to_semantic": area_ratio,
            "failed_required_checks": list(validation_result.failed_required_checks or ()),
            "validation_manual_review_recommended": bool(validation_result.manual_review_recommended),
        }

        if not terrain_available:
            reasons.append("Poligono terrain non disponibile o già marcato per fallback")
        if not validation_result.valid or validation_result.fallback_required:
            reasons.append("Validazione 13D.1 non superata")
        if validation_result.failed_required_checks:
            reasons.append("Controlli obbligatori falliti: " + ", ".join(validation_result.failed_required_checks))

        area_ratio_automatic = True
        if area_ratio is not None:
            area_ratio_automatic = self.minimum_automatic_area_ratio <= area_ratio <= self.maximum_automatic_area_ratio
            if not area_ratio_automatic:
                warnings.append(
                    "Differenza di area rilevante tra geometria terrain e geometria semantica "
                    f"(rapporto {area_ratio:.2f})"
                )

        terrain_eligible = bool(terrain_available and validation_result.valid and not validation_result.fallback_required)
        if not terrain_eligible:
            if semantic_available:
                reasons.append("Selezionato fallback semantico sicuro")
                decision = TerrainGeometryDecision.USE_SEMANTIC_FALLBACK
                confidence = semantic_confidence
                automatic = True
            else:
                reasons.append("Fallback semantico assente: richiesta revisione manuale")
                decision = TerrainGeometryDecision.REQUIRE_MANUAL_REVIEW
                confidence = terrain_confidence
                automatic = False
            warnings.extend(validation_result.warnings or ())
            provenance["decision_rule"] = "terrain_ineligible"
            return TerrainGeometryDecisionResult(
                available=True,
                decision=decision,
                confidence=confidence,
                automatic=automatic,
                terrain_eligible=False,
                semantic_fallback_available=semantic_available,
                reasons=tuple(dict.fromkeys(reasons)),
                warnings=tuple(dict.fromkeys(warnings)),
                metrics=metrics,
                provenance=provenance,
            )

        high_confidence = terrain_confidence >= self.automatic_terrain_confidence
        sufficient_gain = (not semantic_available) or confidence_gain >= self.minimum_gain_over_semantic
        no_review_flag = not validation_result.manual_review_recommended

        if high_confidence and sufficient_gain and area_ratio_automatic and no_review_flag:
            decision = TerrainGeometryDecision.USE_TERRAIN_GEOMETRY
            automatic = True
            confidence = terrain_confidence
            reasons.extend([
                "Poligono terrain disponibile e validato",
                f"Confidenza di validazione sufficiente ({terrain_confidence * 100.0:.1f}%)",
                "Vantaggio rispetto alla geometria semantica sufficiente" if semantic_available else "Nessun fallback semantico affidabile disponibile",
                "Rapporto di area compatibile con la sostituzione automatica" if area_ratio is not None else "Confronto di area non disponibile ma non necessario",
            ])
            provenance["decision_rule"] = "automatic_terrain_acceptance"
        elif terrain_confidence >= self.manual_review_confidence:
            decision = TerrainGeometryDecision.REQUIRE_MANUAL_REVIEW
            automatic = False
            confidence = terrain_confidence
            reasons.append("Poligono terrain valido ma non abbastanza forte per la sostituzione automatica")
            if not high_confidence:
                reasons.append("Confidenza inferiore alla soglia automatica")
            if not sufficient_gain:
                reasons.append("Miglioramento rispetto alla geometria semantica insufficiente")
            if not area_ratio_automatic:
                reasons.append("Rapporto di area richiede verifica manuale")
            if not no_review_flag:
                reasons.append("La validazione 13D.1 raccomanda revisione manuale")
            provenance["decision_rule"] = "manual_review_band"
        else:
            decision = TerrainGeometryDecision.USE_SEMANTIC_FALLBACK if semantic_available else TerrainGeometryDecision.REQUIRE_MANUAL_REVIEW
            automatic = semantic_available
            confidence = semantic_confidence if semantic_available else terrain_confidence
            reasons.append("Confidenza terrain insufficiente per l'uso documentale")
            reasons.append("Mantenuto fallback semantico" if semantic_available else "Fallback semantico assente")
            provenance["decision_rule"] = "low_terrain_confidence"

        warnings.extend(validation_result.warnings or ())
        return TerrainGeometryDecisionResult(
            available=True,
            decision=decision,
            confidence=confidence,
            automatic=automatic,
            terrain_eligible=terrain_eligible,
            semantic_fallback_available=semantic_available,
            reasons=tuple(dict.fromkeys(reasons)),
            warnings=tuple(dict.fromkeys(warnings)),
            metrics=metrics,
            provenance=provenance,
        )
