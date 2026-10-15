"""Diagnostic decision engine for GeoLichen SearchGeometry.

Phase 15.2b centralises the *classification* of the geometry strategy that was
already selected by the existing OSM-first/fallback pipeline.  It is purposely
non-operative: it never creates, buffers or replaces a geometry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class SearchGeometryDecision:
    """Serializable explanation of the selected SearchGeometry strategy."""

    decision: str
    family: str
    source: str
    canonical_type: str
    input_geometry_type: str
    selected_strategy: str
    used_osm: bool
    used_fallback: bool
    source_bbox_available: bool
    reasons: tuple = field(default_factory=tuple)
    phase: str = "15.2b-diagnostic"
    behavior_changed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


class AdaptiveBufferDecisionService:
    """Classify the current geometry choice without changing it.

    The decision vocabulary is intentionally small so Phase 15.3 can later
    attach operative behaviour to one branch at a time.
    """

    USE_ADMINISTRATIVE_EXTENT = "USE_ADMINISTRATIVE_EXTENT"
    USE_OSM_POLYGON = "USE_OSM_POLYGON"
    USE_LINE_CORRIDOR = "USE_LINE_CORRIDOR"
    USE_POINT_BUFFER = "USE_POINT_BUFFER"
    USE_GEOCODER_BBOX = "USE_GEOCODER_BBOX"
    USE_GEOCODER_GEOMETRY = "USE_GEOCODER_GEOMETRY"
    USE_SEMANTIC_BUFFER = "USE_SEMANTIC_BUFFER"

    def decide(
        self,
        *,
        canonical_type: str,
        geometry_type: str,
        selected_strategy: str,
        source: str,
        used_osm: bool,
        used_fallback: bool,
        source_bbox_available: bool = False,
    ) -> SearchGeometryDecision:
        canonical = str(canonical_type or "generic_locality").strip().lower()
        geom_type = str(geometry_type or "UNKNOWN").strip().upper()
        strategy = str(selected_strategy or "").strip()
        strategy_l = strategy.lower()
        source_text = str(source or "unknown")
        reasons = [f"semantic_type={canonical}", f"selected_strategy={strategy or 'unknown'}"]

        if canonical == "municipality" and (
            "municipality_full_extent" in strategy_l or "admin" in strategy_l
        ):
            decision = self.USE_ADMINISTRATIVE_EXTENT
            family = "POLYGON"
            reasons.append("municipality_extent_selected")
        elif used_osm and geom_type == "POLYGON":
            decision = self.USE_OSM_POLYGON
            family = "POLYGON"
            reasons.append("osm_polygon_selected")
        elif used_osm and geom_type == "LINE":
            decision = self.USE_LINE_CORRIDOR
            family = "LINE"
            reasons.append("osm_line_buffered_as_corridor")
        elif used_osm and geom_type == "POINT":
            decision = self.USE_POINT_BUFFER
            family = "BUFFER"
            reasons.append("osm_point_buffered_by_semantic_radius")
        elif "bbox" in strategy_l:
            decision = self.USE_GEOCODER_BBOX
            family = "BBOX"
            reasons.append("compatible_geocoder_bbox_selected")
        elif "point_fallback" in strategy_l or "point_buffer" in strategy_l:
            decision = self.USE_POINT_BUFFER
            family = "BUFFER"
            reasons.append("point_geometry_buffered")
        elif strategy_l.startswith("semantic_") and any(
            token in strategy_l for token in ("_buffer_", "area_or_point_buffer", "line_corridor")
        ):
            decision = self.USE_SEMANTIC_BUFFER
            family = "BUFFER"
            reasons.append("semantic_buffer_fallback_selected")
        elif used_fallback:
            decision = self.USE_GEOCODER_GEOMETRY
            family = geom_type if geom_type in {"POINT", "LINE", "POLYGON"} else "GEOMETRY"
            reasons.append("semantic_geocoder_geometry_fallback")
        else:
            decision = self.USE_GEOCODER_GEOMETRY
            family = geom_type if geom_type in {"POINT", "LINE", "POLYGON"} else "GEOMETRY"
            reasons.append("existing_geometry_strategy_preserved")

        if source_bbox_available:
            reasons.append("source_bbox_available")
        if used_fallback:
            reasons.append("osm_unavailable_or_rejected")

        return SearchGeometryDecision(
            decision=decision,
            family=family,
            source=source_text,
            canonical_type=canonical,
            input_geometry_type=geom_type,
            selected_strategy=strategy,
            used_osm=bool(used_osm),
            used_fallback=bool(used_fallback),
            source_bbox_available=bool(source_bbox_available),
            reasons=tuple(reasons),
        )
