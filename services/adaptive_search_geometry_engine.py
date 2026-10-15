"""Operative selector for adaptive SearchGeometry dimensions.

GeoLichen 15.4.0 introduces one orchestration layer for the metric values used
by point buffers, line corridors and polygon margins.  Geometry construction
remains in :mod:`initial_boundary_service`; this engine only selects dimensions
and explains the choice.

The first release is deliberately conservative: it preserves the semantic
values centralised in phases 15.3.1--15.3.3, including the existing explicit
provider-accuracy rule for geocoder point fallbacks.  Later 15.4.x releases can
add new evidence without spreading dimensional rules across geometry builders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from .semantic_search_buffer_service import SemanticSearchBufferService


@dataclass(frozen=True)
class AdaptiveGeometryResult:
    """Serializable metric plan returned before geometry construction."""

    canonical_type: str
    decision: str
    family: str
    point_radius_m: Optional[float] = None
    line_corridor_radius_m: Optional[float] = None
    polygon_margin_m: Optional[float] = None
    base_point_radius_m: Optional[float] = None
    base_line_corridor_radius_m: Optional[float] = None
    base_polygon_margin_m: Optional[float] = None
    source_kind: str = "unknown"
    source_accuracy_m: Optional[float] = None
    reasons: tuple = field(default_factory=tuple)
    phase: str = "15.4.0-adaptive-search-geometry-engine"
    behavior_changed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


class AdaptiveSearchGeometryEngine:
    """Choose dimensions; never create, buffer or replace geometries."""

    POINT_DECISIONS = {"USE_POINT_BUFFER", "USE_SEMANTIC_BUFFER"}
    LINE_DECISIONS = {"USE_LINE_CORRIDOR"}
    POLYGON_DECISIONS = {
        "USE_OSM_POLYGON",
        "USE_GEOCODER_BBOX",
        "USE_ADMINISTRATIVE_EXTENT",
    }

    def __init__(self, strategy_service=None):
        self.strategy_service = strategy_service or SemanticSearchBufferService()

    def plan(
        self,
        feature_type,
        *,
        decision,
        source_kind="unknown",
        source_accuracy_m=None,
    ) -> AdaptiveGeometryResult:
        canonical, strategy = self.strategy_service.strategy_for(feature_type)
        decision_text = str(decision or "UNCLASSIFIED").strip().upper()
        source_text = str(source_kind or "unknown")
        reasons = [
            f"semantic_type={canonical}",
            f"decision={decision_text}",
            f"source_kind={source_text}",
            "conservative_15_4_0_rules",
        ]

        _, base_point = self.strategy_service.radius_for(canonical)
        _, base_line = self.strategy_service.line_corridor_radius_for(canonical)
        _, base_polygon = self.strategy_service.polygon_margin_for(canonical)

        point_radius = None
        line_radius = None
        polygon_margin = None
        changed = False
        family = "NONE"

        if decision_text in self.LINE_DECISIONS:
            family = "LINE"
            _, line_radius = self.strategy_service.line_corridor_radius_for(canonical)
            reasons.append("centralized_line_corridor_selected")
        elif decision_text in self.POLYGON_DECISIONS:
            family = "POLYGON"
            if decision_text == "USE_ADMINISTRATIVE_EXTENT":
                polygon_margin = 0.0
                reasons.append("administrative_extent_kept_unexpanded")
            else:
                _, polygon_margin = self.strategy_service.polygon_margin_for(canonical)
                reasons.append("centralized_polygon_margin_selected")
        elif decision_text in self.POINT_DECISIONS:
            family = "POINT"
            _, point_radius, point_reasons, changed = (
                self.strategy_service.adaptive_point_radius_for(
                    canonical,
                    source_accuracy_m=source_accuracy_m,
                    source_kind=source_text,
                )
            )
            reasons.extend(point_reasons)
        else:
            reasons.append("no_metric_transformation_requested")

        return AdaptiveGeometryResult(
            canonical_type=canonical,
            decision=decision_text,
            family=family,
            point_radius_m=float(point_radius) if point_radius is not None else None,
            line_corridor_radius_m=float(line_radius) if line_radius is not None else None,
            polygon_margin_m=float(polygon_margin) if polygon_margin is not None else None,
            base_point_radius_m=float(base_point),
            base_line_corridor_radius_m=float(base_line),
            base_polygon_margin_m=float(base_polygon),
            source_kind=source_text,
            source_accuracy_m=(float(source_accuracy_m) if source_accuracy_m is not None else None),
            reasons=tuple(dict.fromkeys(str(reason) for reason in reasons if reason)),
            behavior_changed=bool(changed),
        )
