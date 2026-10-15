"""Data models for Phase 13C terrain-domain reconstruction.

The models remain importable outside QGIS. ``geometry`` is a ``QgsGeometry``
at runtime, while ``mask`` is normally a NumPy boolean array.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class TerrainPolygonResult:
    """Immutable result of the Phase 13C mountain-domain reconstruction."""

    available: bool
    geometry: Any = None
    mask: Any = None
    area_m2: float = 0.0
    cell_count: int = 0
    summit_elevation_m: Optional[float] = None
    elevation_floor_m: Optional[float] = None
    relief_m: Optional[float] = None
    maximum_distance_m: float = 0.0
    compactness: float = 0.0
    confidence: float = 0.0
    fallback_required: bool = False
    quality_flags: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "area_m2", max(0.0, float(self.area_m2 or 0.0)))
        object.__setattr__(self, "cell_count", max(0, int(self.cell_count or 0)))
        object.__setattr__(self, "maximum_distance_m", max(0.0, float(self.maximum_distance_m or 0.0)))
        object.__setattr__(self, "compactness", max(0.0, min(1.0, float(self.compactness or 0.0))))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence or 0.0))))
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags or ()))
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))

    @classmethod
    def unavailable(cls, *warnings: str, provenance: Optional[Mapping[str, Any]] = None) -> "TerrainPolygonResult":
        return cls(
            available=False,
            fallback_required=True,
            warnings=tuple(str(v) for v in warnings if v),
            provenance=dict(provenance or {}),
        )

    @property
    def area_km2(self) -> float:
        return self.area_m2 / 1_000_000.0

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "available": bool(self.available),
            "area_m2": self.area_m2,
            "area_km2": self.area_km2,
            "cell_count": self.cell_count,
            "summit_elevation_m": self.summit_elevation_m,
            "elevation_floor_m": self.elevation_floor_m,
            "relief_m": self.relief_m,
            "maximum_distance_m": self.maximum_distance_m,
            "compactness": self.compactness,
            "confidence": self.confidence,
            "fallback_required": bool(self.fallback_required),
            "quality_flags": list(self.quality_flags),
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }
