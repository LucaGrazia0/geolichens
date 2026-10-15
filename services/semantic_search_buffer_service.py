"""Semantic strategies for the operational candidate-search geometry.

This service selects conservative, type-specific radii and bbox margins.  It
only controls the geometry used to generate candidates; it does not score or
rank them and it does not assign Darwin Core uncertainty directly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AdaptiveBufferPlan:
    """Diagnostic-only description of the current search-buffer decision.

    Phase 15.2 deliberately does not alter the geometry.  The plan records the
    values already used by the existing pipeline so they can be inspected,
    tested and evolved safely in later phases.
    """

    canonical_type: str
    shape: str
    base_radius_m: float
    selected_radius_m: float
    min_radius_m: float
    max_radius_m: float
    line_corridor_radius_m: float
    line_corridor_min_m: float
    line_corridor_max_m: float
    bbox_margin_m: float
    polygon_margin_base_m: float
    polygon_margin_selected_m: float
    polygon_margin_min_m: float
    polygon_margin_max_m: float
    osm_query_initial_m: float
    osm_query_max_m: float
    expansion_step_m: Optional[float]
    altitude_expansion_allowed: bool
    altitude_expansion_radii_m: tuple = field(default_factory=tuple)
    geometry_source: str = "unknown"
    geometry_type: str = "UNKNOWN"
    used_osm: bool = False
    fallback_used: bool = False
    record_altitude_available: bool = False
    reasons: tuple = field(default_factory=tuple)
    decision: str = "UNCLASSIFIED"
    decision_family: str = "UNKNOWN"
    decision_source: str = "unknown"
    decision_reasons: tuple = field(default_factory=tuple)
    phase: str = "15.4.0-adaptive-search-geometry-engine"
    behavior_changed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["altitude_expansion_radii_m"] = list(self.altitude_expansion_radii_m)
        data["reasons"] = list(self.reasons)
        data["decision_reasons"] = list(self.decision_reasons)
        return data


class SemanticSearchBufferService:
    """Central registry for semantic search-buffer rules."""

    STRATEGIES = {
        "peak": {
            "shape": "point_buffer",
            "radius_m": 150.0,
            "min_radius_m": 75.0,
            "max_radius_m": 400.0,
            "osm_query_initial_m": 225.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 50.0,
            "polygon_margin_base_m": 50.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 50.0,
        },
        "hill": {
            "shape": "area_or_point_buffer",
            "radius_m": 500.0,
            "min_radius_m": 300.0,
            "max_radius_m": 800.0,
            "osm_query_initial_m": 750.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 100.0,
            "polygon_margin_base_m": 100.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 100.0,
        },
        "pass": {
            "shape": "point_buffer",
            "radius_m": 250.0,
            "min_radius_m": 100.0,
            "max_radius_m": 600.0,
            "osm_query_initial_m": 375.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 75.0,
            "polygon_margin_base_m": 75.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 75.0,
        },
        "mountain": {
            "shape": "area_or_point_buffer",
            "radius_m": 1000.0,
            "min_radius_m": 500.0,
            "max_radius_m": 3000.0,
            "osm_query_initial_m": 1500.0,
            "osm_query_max_m": 2500.0,
            "allow_altitude_expansion": True,
            "altitude_expansion_radii_m": (1500.0, 1800.0, 2100.0, 2400.0, 2700.0, 3000.0),
            "expansion_step_m": 300.0,
            "bbox_margin_m": 200.0,
            "polygon_margin_base_m": 200.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 200.0,
        },
        "mountain_group": {
            "shape": "area_or_point_buffer",
            "radius_m": 2500.0,
            "min_radius_m": 1200.0,
            "max_radius_m": 5000.0,
            "osm_query_initial_m": 3750.0,
            "osm_query_max_m": 6000.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 300.0,
            "polygon_margin_base_m": 300.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 300.0,
        },
        "valley": {
            "shape": "elongated_area",
            "radius_m": 1500.0,
            "min_radius_m": 750.0,
            "max_radius_m": 3000.0,
            "osm_query_initial_m": 2250.0,
            "osm_query_max_m": 3500.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 750.0,
            "polygon_margin_base_m": 750.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 750.0,
        },
        "generic_locality": {
            "shape": "best_available",
            "radius_m": 500.0,
            "min_radius_m": 150.0,
            "max_radius_m": 1500.0,
            "osm_query_initial_m": 750.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 100.0,
            "polygon_margin_base_m": 100.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 100.0,
        },
        "municipality": {
            "shape": "administrative_extent",
            "radius_m": 2000.0,
            "min_radius_m": 1000.0,
            "max_radius_m": 5000.0,
            "osm_query_initial_m": 5000.0,
            "osm_query_max_m": 8000.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 0.0,
            "polygon_margin_base_m": 0.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 0.0,
        },
        "trail": {
            "shape": "line_corridor",
            "radius_m": 150.0,
            "min_radius_m": 20.0,
            "max_radius_m": 300.0,
            "line_corridor_radius_m": 150.0,
            "line_corridor_min_m": 20.0,
            "line_corridor_max_m": 300.0,
            "osm_query_initial_m": 500.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 75.0,
            "polygon_margin_base_m": 75.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 75.0,
        },
        "forest": {
            "shape": "polygon_or_filtered_area",
            "radius_m": 1000.0,
            "min_radius_m": 250.0,
            "max_radius_m": 2500.0,
            "osm_query_initial_m": 1500.0,
            "osm_query_max_m": 3000.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 75.0,
            "polygon_margin_base_m": 75.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 75.0,
        },
        "lake": {
            "shape": "polygon_or_filtered_area",
            "radius_m": 300.0,
            "min_radius_m": 100.0,
            "max_radius_m": 1000.0,
            "osm_query_initial_m": 900.0,
            "osm_query_max_m": 2200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 50.0,
            "polygon_margin_base_m": 50.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 50.0,
        },
        "river": {
            "shape": "line_corridor",
            "radius_m": 300.0,
            "min_radius_m": 50.0,
            "max_radius_m": 750.0,
            "line_corridor_radius_m": 300.0,
            "line_corridor_min_m": 50.0,
            "line_corridor_max_m": 750.0,
            "osm_query_initial_m": 500.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 100.0,
            "polygon_margin_base_m": 100.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 100.0,
        },
        "refuge": {
            "shape": "point_buffer",
            "radius_m": 150.0,
            "min_radius_m": 50.0,
            "max_radius_m": 400.0,
            "osm_query_initial_m": 500.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 50.0,
            "polygon_margin_base_m": 50.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 50.0,
        },
        "meadow": {
            "shape": "area_or_point_buffer",
            "radius_m": 600.0,
            "min_radius_m": 250.0,
            "max_radius_m": 1500.0,
            "osm_query_initial_m": 900.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 100.0,
            "polygon_margin_base_m": 100.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 100.0,
        },
        # GeoLichen 14.2.1: aggiunte le strategie mancanti per 4 tipi già
        # riconosciuti dal parser semantico (core/locality_parser.py) ma privi
        # finora di una voce qui, che quindi ricadevano silenziosamente su
        # "generic_locality" (raggio 500 m, punto/area generica).
        "glacier": {
            "shape": "polygon_or_filtered_area",
            "radius_m": 500.0,
            "min_radius_m": 200.0,
            "max_radius_m": 1500.0,
            "osm_query_initial_m": 750.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 100.0,
            "polygon_margin_base_m": 100.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 100.0,
        },
        "road": {
            "shape": "line_corridor",
            "radius_m": 150.0,
            "min_radius_m": 30.0,
            "max_radius_m": 400.0,
            "line_corridor_radius_m": 150.0,
            "line_corridor_min_m": 30.0,
            "line_corridor_max_m": 400.0,
            "osm_query_initial_m": 500.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 75.0,
            "polygon_margin_base_m": 75.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 75.0,
        },
        "church": {
            "shape": "point_buffer",
            "radius_m": 100.0,
            "min_radius_m": 30.0,
            "max_radius_m": 300.0,
            "osm_query_initial_m": 500.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 40.0,
            "polygon_margin_base_m": 40.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 40.0,
        },
        "ridge": {
            "shape": "line_corridor",
            "radius_m": 200.0,
            "min_radius_m": 50.0,
            "max_radius_m": 600.0,
            "line_corridor_radius_m": 200.0,
            "line_corridor_min_m": 50.0,
            "line_corridor_max_m": 600.0,
            "osm_query_initial_m": 500.0,
            "osm_query_max_m": 1200.0,
            "allow_altitude_expansion": False,
            "bbox_margin_m": 75.0,
            "polygon_margin_base_m": 75.0,
            "polygon_margin_min_m": 0.0,
            "polygon_margin_max_m": 75.0,
        },
    }

    ALIASES = {
        "summit": "peak",
        "summit_peak": "peak",
        "mountain_area": "mountain",
        "forest_area": "forest",
        "hydro": "lake",
        "refuge_malga": "refuge",
        "generic_toponym": "generic_locality",
        "locality": "generic_locality",
        "nearby_place": "generic_locality",
    }

    def canonical_type(self, feature_type):
        value = str(feature_type or "generic_locality").strip().lower()
        return self.ALIASES.get(value, value)

    def strategy_for(self, feature_type):
        key = self.canonical_type(feature_type)
        return key, dict(self.STRATEGIES.get(key, self.STRATEGIES["generic_locality"]))

    def radius_for(self, feature_type, requested_radius_m=None):
        key, strategy = self.strategy_for(feature_type)
        radius = strategy["radius_m"] if requested_radius_m is None else float(requested_radius_m)
        radius = max(float(strategy["min_radius_m"]), radius)
        radius = min(float(strategy["max_radius_m"]), radius)
        return key, radius

    def osm_query_radius_for(self, feature_type):
        """Return the centralized OSM lookup radius without changing behavior."""
        key, strategy = self.strategy_for(feature_type)
        initial = float(strategy.get("osm_query_initial_m", strategy["radius_m"]))
        maximum = float(strategy.get("osm_query_max_m", initial))
        return key, min(initial, maximum)

    def altitude_expansion_radii_for(self, feature_type):
        """Return the existing controlled altitude-expansion sequence."""
        key, strategy = self.strategy_for(feature_type)
        if not bool(strategy.get("allow_altitude_expansion", False)):
            return key, ()
        radii = strategy.get("altitude_expansion_radii_m") or ()
        return key, tuple(float(value) for value in radii)


    def build_adaptive_plan(
        self,
        feature_type,
        *,
        geometry_source="unknown",
        geometry_type="UNKNOWN",
        used_osm=False,
        fallback_used=False,
        record_altitude_available=False,
        selected_radius_m=None,
        selected_line_corridor_m=None,
        selected_polygon_margin_m=None,
        extra_reasons=None,
        decision=None,
        behavior_changed=False,
    ):
        """Build a non-operative AdaptiveBufferPlan.

        The selected radius defaults to the same radius returned by
        :meth:`radius_for`; therefore Phase 15.2 is metadata-only.
        """
        canonical, strategy = self.strategy_for(feature_type)
        _, base_radius = self.radius_for(canonical)
        selected = base_radius if selected_radius_m is None else float(selected_radius_m)
        selected = max(float(strategy["min_radius_m"]), selected)
        selected = min(float(strategy["max_radius_m"]), selected)
        reasons = [f"semantic_type={canonical}", f"shape={strategy.get('shape', 'point_buffer')}"]
        if used_osm:
            reasons.append("osm_geometry_selected")
        elif fallback_used:
            reasons.append("semantic_fallback_selected")
        if record_altitude_available:
            reasons.append("record_altitude_available")
        for reason in extra_reasons or ():
            text = str(reason or "").strip()
            if text and text not in reasons:
                reasons.append(text)
        radii = tuple(float(v) for v in (strategy.get("altitude_expansion_radii_m") or ()))
        step = strategy.get("expansion_step_m")
        base_line = float(strategy.get("line_corridor_radius_m", strategy["radius_m"]))
        line_min = float(strategy.get("line_corridor_min_m", strategy["min_radius_m"]))
        line_max = float(strategy.get("line_corridor_max_m", strategy["max_radius_m"]))
        selected_line = base_line if selected_line_corridor_m is None else float(selected_line_corridor_m)
        selected_line = min(line_max, max(line_min, selected_line))
        base_polygon = float(strategy.get("polygon_margin_base_m", strategy.get("bbox_margin_m", 0.0)) or 0.0)
        polygon_min = float(strategy.get("polygon_margin_min_m", 0.0) or 0.0)
        polygon_max = float(strategy.get("polygon_margin_max_m", base_polygon) or 0.0)
        selected_polygon = base_polygon if selected_polygon_margin_m is None else float(selected_polygon_margin_m)
        selected_polygon = min(max(polygon_min, polygon_max), max(polygon_min, selected_polygon))
        return AdaptiveBufferPlan(
            canonical_type=canonical,
            shape=str(strategy.get("shape", "point_buffer")),
            base_radius_m=float(base_radius),
            selected_radius_m=float(selected),
            min_radius_m=float(strategy["min_radius_m"]),
            max_radius_m=float(strategy["max_radius_m"]),
            line_corridor_radius_m=float(selected_line),
            line_corridor_min_m=float(line_min),
            line_corridor_max_m=float(line_max),
            bbox_margin_m=float(strategy.get("bbox_margin_m", 0.0) or 0.0),
            polygon_margin_base_m=float(base_polygon),
            polygon_margin_selected_m=float(selected_polygon),
            polygon_margin_min_m=float(polygon_min),
            polygon_margin_max_m=float(polygon_max),
            osm_query_initial_m=float(strategy.get("osm_query_initial_m", base_radius)),
            osm_query_max_m=float(strategy.get("osm_query_max_m", strategy.get("osm_query_initial_m", base_radius))),
            expansion_step_m=float(step) if step is not None else None,
            altitude_expansion_allowed=bool(strategy.get("allow_altitude_expansion", False)),
            altitude_expansion_radii_m=radii,
            geometry_source=str(geometry_source or "unknown"),
            geometry_type=str(geometry_type or "UNKNOWN").upper(),
            used_osm=bool(used_osm),
            fallback_used=bool(fallback_used),
            record_altitude_available=bool(record_altitude_available),
            reasons=tuple(reasons),
            decision=str(getattr(decision, "decision", "UNCLASSIFIED")),
            decision_family=str(getattr(decision, "family", "UNKNOWN")),
            decision_source=str(getattr(decision, "source", "unknown")),
            decision_reasons=tuple(getattr(decision, "reasons", ()) or ()),
            behavior_changed=bool(behavior_changed),
        )


    def adaptive_point_radius_for(
        self,
        feature_type,
        *,
        source_accuracy_m=None,
        source_kind="geocoder_point",
    ):
        """Return a conservative adaptive radius for point-based strategies.

        Phase 15.3.1 is deliberately limited to point buffers.  OSM points keep
        the semantic base radius because their coordinate precision does not
        describe the real-world extent of the named locality.  Geocoder point
        fallbacks may expand to an explicit provider accuracy/radius, always
        clamped by the semantic minimum and maximum.
        """
        canonical, strategy = self.strategy_for(feature_type)
        _, base_radius = self.radius_for(canonical)
        selected = float(base_radius)
        reasons = ["point_buffer_branch", f"source_kind={source_kind}"]

        if str(source_kind or "").lower() == "osm_point":
            reasons.append("osm_point_keeps_semantic_extent")
        else:
            try:
                accuracy = float(source_accuracy_m) if source_accuracy_m is not None else None
            except Exception:
                accuracy = None
            if accuracy is not None and accuracy > 0:
                requested = max(float(base_radius), accuracy)
                selected = max(float(strategy["min_radius_m"]), requested)
                selected = min(float(strategy["max_radius_m"]), selected)
                reasons.append(f"provider_accuracy_m={accuracy:g}")
                if selected > float(base_radius):
                    reasons.append("expanded_to_provider_accuracy")
                elif accuracy > float(strategy["max_radius_m"]):
                    reasons.append("provider_accuracy_clamped_to_semantic_max")
                else:
                    reasons.append("semantic_base_radius_retained")
            else:
                reasons.append("provider_accuracy_unavailable")
                reasons.append("semantic_base_radius_retained")

        changed = abs(float(selected) - float(base_radius)) > 1e-9
        return canonical, float(selected), tuple(reasons), changed

    def line_corridor_radius_for(self, feature_type, requested_radius_m=None):
        """Return the centralized half-width used to buffer line geometries.

        Phase 15.3.2 is a refactoring-only step: current values are copied
        from the pre-existing semantic radii, so generated SearchGeometry
        remains unchanged. Future adaptive rules can evolve this method
        without reintroducing corridor constants in geometry builders.
        """
        key, strategy = self.strategy_for(feature_type)
        base = float(strategy.get("line_corridor_radius_m", strategy["radius_m"]))
        minimum = float(strategy.get("line_corridor_min_m", strategy["min_radius_m"]))
        maximum = float(strategy.get("line_corridor_max_m", strategy["max_radius_m"]))
        selected = base if requested_radius_m is None else float(requested_radius_m)
        selected = max(minimum, selected)
        selected = min(maximum, selected)
        return key, float(selected)

    def polygon_margin_for(self, feature_type, requested_margin_m=None):
        """Return the centralized margin applied to polygon-like geometries.

        Phase 15.3.3 is a refactoring-only step. The base, minimum and maximum
        polygon margins are stored in the semantic strategy registry, while
        current selected values remain identical to the former bbox margins.
        Both provider bboxes and OSM polygons now use this single API.
        """
        key, strategy = self.strategy_for(feature_type)
        base = float(strategy.get(
            "polygon_margin_base_m",
            strategy.get("bbox_margin_m", 0.0),
        ) or 0.0)
        minimum = float(strategy.get("polygon_margin_min_m", 0.0) or 0.0)
        maximum = float(strategy.get("polygon_margin_max_m", base) or 0.0)
        if maximum < minimum:
            maximum = minimum
        selected = base if requested_margin_m is None else float(requested_margin_m)
        selected = max(minimum, selected)
        selected = min(maximum, selected)
        return key, float(selected)

    def bbox_margin_for(self, feature_type):
        """Backward-compatible alias for the centralized polygon margin."""
        return self.polygon_margin_for(feature_type)
