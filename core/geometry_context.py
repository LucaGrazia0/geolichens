"""Unified documented/search geometry context for GeoLichen 15.4.5.

This is an additive compatibility layer. Existing DocumentedGeometry,
SearchGeometry and ResolvedLocality objects remain authoritative runtime
objects; this context records their relationship and validation state in one
serialisable snapshot for later uncertainty, reporting and export stages.
"""
from dataclasses import dataclass, field
from typing import Any, Dict

from .geometry_result import GeometryResult


@dataclass
class GeoreferencingGeometryContext:
    semantic_type: str
    documented: GeometryResult
    search: GeometryResult
    version: str = "15.4.5-S3"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return bool(self.documented.success and self.search.success)

    @property
    def requires_review(self) -> bool:
        return bool(
            self.documented.requires_review
            or self.search.requires_review
            or not self.valid
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "semantic_type": str(self.semantic_type or ""),
            "valid": self.valid,
            "requires_review": self.requires_review,
            "documented": self.documented.to_dict(include_geometry=False),
            "search": self.search.to_dict(include_geometry=False),
            "metadata": dict(self.metadata or {}),
        }
