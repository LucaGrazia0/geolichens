"""Aggregate result produced by the Semantic Locality & Geometry Engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from .documented_geometry import DocumentedGeometry
from .search_geometry import SearchGeometry


@dataclass(frozen=True)
class LocalityInterpretation:
    original_text: str
    normalized_text: str
    feature_type: str
    expected_geometry: str
    confidence: float
    matched_rule: str = "fallback"
    relation: Optional[str] = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_type", str(self.feature_type or "unknown"))
        object.__setattr__(self, "expected_geometry", str(self.expected_geometry or "unknown").upper())
        try:
            conf = max(0.0, min(1.0, float(self.confidence)))
        except (TypeError, ValueError):
            conf = 0.0
        object.__setattr__(self, "confidence", conf)
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))
        object.__setattr__(self, "attributes", dict(self.attributes or {}))


@dataclass
class ResolvedLocality:
    interpretation: LocalityInterpretation
    documented_geometry: DocumentedGeometry
    search_geometry: SearchGeometry
    geometry_confidence: float
    geometry_confidence_class: str = "unknown"
    geometry_confidence_reasons: tuple[str, ...] = field(default_factory=tuple)
    provenance: Dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        try:
            self.geometry_confidence = max(0.0, min(1.0, float(self.geometry_confidence)))
        except (TypeError, ValueError):
            self.geometry_confidence = 0.0
        self.geometry_confidence_class = str(self.geometry_confidence_class or "unknown")
        self.geometry_confidence_reasons = tuple(self.geometry_confidence_reasons or ())
        self.provenance = dict(self.provenance or {})
        self.warnings = list(self.warnings or [])

    @property
    def requires_review(self) -> bool:
        return bool(
            self.documented_geometry.requires_review
            or self.documented_geometry.estimated
            or self.geometry_confidence < 0.70
            or self.warnings
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "interpretation": {
                "original_text": self.interpretation.original_text,
                "normalized_text": self.interpretation.normalized_text,
                "feature_type": self.interpretation.feature_type,
                "expected_geometry": self.interpretation.expected_geometry,
                "confidence": self.interpretation.confidence,
                "matched_rule": self.interpretation.matched_rule,
                "relation": self.interpretation.relation,
                "warnings": list(self.interpretation.warnings),
                "attributes": dict(self.interpretation.attributes),
            },
            "documented_geometry": self.documented_geometry.provenance_dict(),
            "search_geometry": dict(self.search_geometry.provenance_dict()),
            "geometry_confidence": self.geometry_confidence,
            "geometry_confidence_class": self.geometry_confidence_class,
            "geometry_confidence_reasons": list(self.geometry_confidence_reasons),
            "requires_review": self.requires_review,
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }
