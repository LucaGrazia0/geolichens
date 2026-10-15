"""Data models for Phase 13B summit detection.

These models deliberately avoid mandatory QGIS imports. Coordinates can be
stored as QgsPointXY objects at runtime or as plain ``(x, y)`` tuples in tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class SummitCandidate:
    """A local DEM maximum considered as the summit of the named locality."""

    point: Any
    row: int
    col: int
    elevation_m: float
    distance_from_anchor_m: float
    prominence_m: float
    isolation_m: float
    slope_context_deg: float
    profile_curvature: float
    score: float
    confidence: float
    reasons: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "row", int(self.row))
        object.__setattr__(self, "col", int(self.col))
        object.__setattr__(self, "elevation_m", float(self.elevation_m))
        object.__setattr__(self, "distance_from_anchor_m", max(0.0, float(self.distance_from_anchor_m)))
        object.__setattr__(self, "prominence_m", max(0.0, float(self.prominence_m)))
        object.__setattr__(self, "isolation_m", max(0.0, float(self.isolation_m)))
        object.__setattr__(self, "score", max(0.0, min(100.0, float(self.score))))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))
        object.__setattr__(self, "reasons", tuple(self.reasons or ()))

    def summary_dict(self) -> Dict[str, Any]:
        try:
            x, y = float(self.point.x()), float(self.point.y())
        except Exception:
            try:
                x, y = float(self.point[0]), float(self.point[1])
            except Exception:
                x = y = None
        return {
            "x": x,
            "y": y,
            "row": self.row,
            "col": self.col,
            "elevation_m": self.elevation_m,
            "distance_from_anchor_m": self.distance_from_anchor_m,
            "prominence_m": self.prominence_m,
            "isolation_m": self.isolation_m,
            "slope_context_deg": self.slope_context_deg,
            "profile_curvature": self.profile_curvature,
            "score": self.score,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class SummitDetectionResult:
    """Immutable Phase 13B result.

    Phase 13B is diagnostic only: it does not replace the SLGE documented
    geometry. Phase 13C may consume ``selected`` to reconstruct a polygon.
    """

    available: bool
    selected: Optional[SummitCandidate] = None
    candidates: Tuple[SummitCandidate, ...] = field(default_factory=tuple)
    anchor_point: Any = None
    anchor_elevation_m: Optional[float] = None
    record_elevation_m: Optional[float] = None
    confidence: float = 0.0
    ambiguous: bool = False
    fallback_required: bool = False
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates or ()))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence or 0.0))))
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))

    @classmethod
    def unavailable(cls, *warnings: str, provenance: Optional[Mapping[str, Any]] = None) -> "SummitDetectionResult":
        return cls(
            available=False,
            fallback_required=True,
            warnings=tuple(str(v) for v in warnings if v),
            provenance=dict(provenance or {}),
        )

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "available": bool(self.available),
            "selected": self.selected.summary_dict() if self.selected else None,
            "candidate_count": len(self.candidates),
            "candidates": [candidate.summary_dict() for candidate in self.candidates],
            "anchor_elevation_m": self.anchor_elevation_m,
            "record_elevation_m": self.record_elevation_m,
            "confidence": self.confidence,
            "ambiguous": bool(self.ambiguous),
            "fallback_required": bool(self.fallback_required),
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }
