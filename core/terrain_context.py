"""Data models for Phase 13A terrain preparation.

The classes are intentionally independent from QGIS imports so they can be
unit-tested outside QGIS. Runtime geometries, CRS objects and raster layers are
stored as ``Any`` references.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class TerrainRasterGrid:
    """Local DEM grid and terrain derivatives prepared for later phases."""

    elevation: Any
    slope_degrees: Any = None
    aspect_degrees: Any = None
    profile_curvature: Any = None
    plan_curvature: Any = None
    valid_mask: Any = None
    width: int = 0
    height: int = 0
    pixel_size_x: float = 0.0
    pixel_size_y: float = 0.0
    nodata_value: Optional[float] = None

    @property
    def cell_count(self) -> int:
        return max(0, int(self.width)) * max(0, int(self.height))


@dataclass(frozen=True)
class TerrainContext:
    """Immutable result of Phase 13A DEM preparation.

    No documented or search geometry is changed by this object. It is a
    reusable topographic context consumed by summit detection (13B) and later
    reconstruction phases.
    """

    available: bool
    dem_layer: Any = None
    dem_layer_name: str = ""
    dem_source: str = ""
    band: int = 1
    extent: Any = None
    crs: Any = None
    center: Any = None
    radius_m: float = 0.0
    resolution_m: Optional[float] = None
    grid: Optional[TerrainRasterGrid] = None
    coverage_ratio: float = 0.0
    valid_cell_count: int = 0
    total_cell_count: int = 0
    quality_flags: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "dem_layer_name", str(self.dem_layer_name or ""))
        object.__setattr__(self, "dem_source", str(self.dem_source or ""))
        object.__setattr__(self, "radius_m", max(0.0, float(self.radius_m or 0.0)))
        object.__setattr__(self, "coverage_ratio", max(0.0, min(1.0, float(self.coverage_ratio or 0.0))))
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags or ()))
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))

    @classmethod
    def unavailable(cls, *warnings: str, provenance: Optional[Mapping[str, Any]] = None) -> "TerrainContext":
        return cls(
            available=False,
            warnings=tuple(str(v) for v in warnings if v),
            provenance=dict(provenance or {}),
        )

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "available": bool(self.available),
            "dem_layer": self.dem_layer_name,
            "dem_source": self.dem_source,
            "band": int(self.band),
            "radius_m": self.radius_m,
            "resolution_m": self.resolution_m,
            "coverage_ratio": self.coverage_ratio,
            "valid_cell_count": int(self.valid_cell_count),
            "total_cell_count": int(self.total_cell_count),
            "quality_flags": list(self.quality_flags),
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }
