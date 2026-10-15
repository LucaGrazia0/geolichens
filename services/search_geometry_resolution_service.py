"""Single decision point for GeoLichen operational SearchGeometry.

The service keeps documentary geometry separate from the operational search
area.  It applies the strict order requested by the workflow:

1. try a named OpenStreetMap geometry;
2. fall back to the existing deterministic semantic geometry.

It does not generate candidates, fetch trails, alter GSS, or mutate the
DocumentedGeometry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass
class SearchGeometryResolutionResult:
    geometry: Any
    strategy: str
    source: str
    osm_result: Any = None
    used_osm: bool = False
    used_fallback: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        if self.geometry is None:
            return False
        try:
            return not self.geometry.isEmpty()
        except Exception:
            return True


class SearchGeometryResolutionService:
    """Resolve one authoritative operational SearchGeometry result."""

    def resolve(
        self,
        osm_builder: Callable[[], Tuple[Any, Optional[str], Any]],
        semantic_builder: Callable[[], Tuple[Any, str]],
    ) -> SearchGeometryResolutionResult:
        osm_geometry = None
        osm_strategy = None
        osm_result = None
        try:
            osm_geometry, osm_strategy, osm_result = osm_builder()
        except Exception as exc:
            # OSM is an opportunistic first choice.  Any failure must lead to
            # the unchanged semantic fallback rather than aborting the record.
            osm_result = osm_result or None
            osm_error = str(exc)
        else:
            osm_error = getattr(osm_result, "error", None) if osm_result is not None else None

        if self._valid(osm_geometry):
            return SearchGeometryResolutionResult(
                geometry=osm_geometry,
                strategy=str(osm_strategy or "osm_geometry"),
                source="openstreetmap_geometry",
                osm_result=osm_result,
                used_osm=True,
                metadata={
                    "resolution_order": "osm_then_semantic",
                    "fallback_used": False,
                    "osm_error": None,
                },
            )

        semantic_geometry, semantic_strategy = semantic_builder()
        return SearchGeometryResolutionResult(
            geometry=semantic_geometry,
            strategy=str(semantic_strategy or "semantic_fallback"),
            source="semantic_geometry_fallback",
            osm_result=osm_result,
            used_osm=False,
            used_fallback=True,
            metadata={
                "resolution_order": "osm_then_semantic",
                "fallback_used": True,
                "osm_error": osm_error,
            },
        )

    @staticmethod
    def _valid(geometry: Any) -> bool:
        if geometry is None:
            return False
        try:
            return not geometry.isEmpty()
        except Exception:
            return True
