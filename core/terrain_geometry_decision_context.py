"""Data models for Phase 13D.2 terrain-geometry decision making.

The decision layer compares the validated terrain polygon with the semantic
DocumentedGeometry but does not mutate either object.  Actual SLGE/GBIF
integration is intentionally deferred to Phase 13D.3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Tuple


class TerrainGeometryDecision(str, Enum):
    """Allowed outcomes of the Phase 13D.2 safety gate."""

    USE_TERRAIN_GEOMETRY = "USE_TERRAIN_GEOMETRY"
    USE_SEMANTIC_FALLBACK = "USE_SEMANTIC_FALLBACK"
    REQUIRE_MANUAL_REVIEW = "REQUIRE_MANUAL_REVIEW"


@dataclass(frozen=True)
class TerrainGeometryDecisionResult:
    """Immutable and auditable geometry-selection decision."""

    available: bool
    decision: TerrainGeometryDecision = TerrainGeometryDecision.USE_SEMANTIC_FALLBACK
    confidence: float = 0.0
    automatic: bool = False
    terrain_eligible: bool = False
    semantic_fallback_available: bool = False
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        decision = self.decision
        if not isinstance(decision, TerrainGeometryDecision):
            decision = TerrainGeometryDecision(str(decision))
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "available", bool(self.available))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence or 0.0))))
        object.__setattr__(self, "automatic", bool(self.automatic))
        object.__setattr__(self, "terrain_eligible", bool(self.terrain_eligible))
        object.__setattr__(self, "semantic_fallback_available", bool(self.semantic_fallback_available))
        object.__setattr__(self, "reasons", tuple(str(v) for v in (self.reasons or ()) if v))
        object.__setattr__(self, "warnings", tuple(str(v) for v in (self.warnings or ()) if v))
        object.__setattr__(self, "metrics", dict(self.metrics or {}))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))

    @property
    def use_terrain_geometry(self) -> bool:
        return self.decision is TerrainGeometryDecision.USE_TERRAIN_GEOMETRY

    @property
    def use_semantic_fallback(self) -> bool:
        return self.decision is TerrainGeometryDecision.USE_SEMANTIC_FALLBACK

    @property
    def requires_manual_review(self) -> bool:
        return self.decision is TerrainGeometryDecision.REQUIRE_MANUAL_REVIEW

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "decision": self.decision.value,
            "confidence": self.confidence,
            "automatic": self.automatic,
            "terrain_eligible": self.terrain_eligible,
            "semantic_fallback_available": self.semantic_fallback_available,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "metrics": dict(self.metrics),
            "provenance": dict(self.provenance),
        }
