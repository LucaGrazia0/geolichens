"""Unified geometry strategies for the Semantic Locality & Geometry Engine.

The resolver centralises the documentary representation rules for every
semantic locality type.  It does not build the operational candidate-search
extent and therefore cannot alter GSS, ranking or heatmaps.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class GeometryStrategy:
    feature_type: str
    expected_geometry: str
    preferred_sources: tuple[str, ...]
    fallback_mode: str
    fallback_radius_m: Optional[float] = None
    point_is_valid: bool = False
    manual_review_on_fallback: bool = True


class UnifiedGeometryStrategyResolver:
    """Return one coherent documentary-geometry strategy per feature type."""

    STRATEGIES = {
        "municipality": GeometryStrategy("municipality", "ADMIN", ("official_admin_polygon", "geocoder_bbox"), "admin_extent"),
        "mountain_group": GeometryStrategy("mountain_group", "POLYGON", ("official_polygon", "osm_polygon", "geocoder_bbox", "dem_reconstructed"), "semantic_buffer", 2000.0),
        "hill": GeometryStrategy("hill", "POLYGON", ("official_polygon", "osm_polygon", "geocoder_bbox", "dem_reconstructed"), "semantic_buffer", 500.0),
        "mountain": GeometryStrategy("mountain", "POLYGON", ("official_polygon", "osm_polygon", "geocoder_bbox", "dem_reconstructed"), "semantic_buffer", 800.0),
        "valley": GeometryStrategy("valley", "POLYGON", ("official_polygon", "osm_polygon", "geocoder_bbox"), "semantic_buffer", 2000.0),
        "lake": GeometryStrategy("lake", "POLYGON", ("official_polygon", "osm_polygon", "geocoder_polygon", "geocoder_bbox"), "semantic_buffer", 300.0),
        "glacier": GeometryStrategy("glacier", "POLYGON", ("official_polygon", "osm_polygon", "geocoder_polygon", "geocoder_bbox"), "semantic_buffer", 500.0),
        "forest": GeometryStrategy("forest", "POLYGON", ("official_polygon", "osm_polygon", "geocoder_polygon", "geocoder_bbox"), "semantic_buffer", 1000.0),
        "meadow": GeometryStrategy("meadow", "POLYGON", ("official_polygon", "osm_polygon", "geocoder_bbox"), "semantic_buffer", 500.0),
        "peak": GeometryStrategy("peak", "POINT", ("official_point", "osm_point", "geocoder_point", "dem_summit"), "point", point_is_valid=True, manual_review_on_fallback=False),
        "pass": GeometryStrategy("pass", "POINT", ("official_point", "osm_point", "geocoder_point", "dem_saddle"), "point", point_is_valid=True, manual_review_on_fallback=False),
        "refuge": GeometryStrategy("refuge", "POINT", ("official_point", "osm_point", "geocoder_point"), "point", point_is_valid=True, manual_review_on_fallback=False),
        "church": GeometryStrategy("church", "POINT", ("official_point", "osm_point", "geocoder_point"), "point", point_is_valid=True, manual_review_on_fallback=False),
        "river": GeometryStrategy("river", "LINE", ("official_line", "osm_line", "geocoder_line"), "point_proxy", point_is_valid=False),
        "trail": GeometryStrategy("trail", "LINE", ("official_line", "osm_line", "geocoder_line"), "point_proxy", point_is_valid=False),
        "road": GeometryStrategy("road", "LINE", ("official_line", "osm_line", "geocoder_line"), "point_proxy", point_is_valid=False),
        "ridge": GeometryStrategy("ridge", "LINE", ("official_line", "osm_line", "dem_ridge"), "point_proxy", point_is_valid=False),
        "generic_locality": GeometryStrategy("generic_locality", "UNKNOWN", ("official_polygon", "osm_polygon", "geocoder_bbox", "geocoder_point"), "best_available", point_is_valid=True),
        "unknown": GeometryStrategy("unknown", "UNKNOWN", ("geocoder_bbox", "geocoder_point"), "best_available", point_is_valid=True),
    }

    # Legacy reference/semantic names used by InitialBoundaryService.
    FEATURE_ALIASES = {
        "mountain_area": "mountain",
        "summit": "peak",
        "summit_peak": "peak",
        "refuge_malga": "refuge",
        "forest_area": "forest",
        "hydro": "lake",
        "locality": "generic_locality",
        "generic_toponym": "generic_locality",
        "nearby_place": "generic_locality",
    }

    SOURCE_LABELS = {
        "official_admin_polygon": "Confine amministrativo ufficiale",
        "official_polygon": "Poligono ufficiale",
        "official_line": "Tracciato ufficiale",
        "official_point": "Punto ufficiale",
        "osm_polygon": "Poligono OpenStreetMap",
        "osm_line": "Tracciato OpenStreetMap",
        "osm_point": "Punto OpenStreetMap",
        "geocoder_polygon": "Poligono del geocoder",
        "geocoder_bbox": "Estensione del geocoder",
        "geocoder_line": "Tracciato del geocoder",
        "geocoder_point": "Punto del geocoder",
        "semantic_estimate": "Ricostruzione semantica",
        "point_proxy": "Punto rappresentativo del geocoder",
        "dem_reconstructed": "Ricostruzione morfologica da DEM",
        "fallback": "Fallback geometrico dichiarato",
        "missing": "Geometria non disponibile",
    }

    METHOD_LABELS = {
        "geocoder_feature_center": "Rappresentazione puntuale coerente con il tipo di località",
        "geocoder_point_proxy": "Punto rappresentativo in attesa della geometria lineare",
        "geocoder_area_bbox": "Estensione geografica fornita dal geocoder",
        "geocoder_admin_bbox": "Estensione amministrativa fornita dal geocoder",
        "municipality_geometry_missing": "Confine amministrativo non disponibile",
        "area_geometry_missing": "Geometria areale non disponibile",
        "missing_geometry": "Geometria non disponibile",
    }

    def strategy_for(self, feature_type: str | None, expected_geometry: str | None = None) -> GeometryStrategy:
        key = self.FEATURE_ALIASES.get(str(feature_type or "").lower(), str(feature_type or "unknown").lower())
        strategy = self.STRATEGIES.get(key)
        if strategy is not None:
            return strategy
        expected = str(expected_geometry or "UNKNOWN").upper()
        fallback = "point" if expected == "POINT" else ("semantic_buffer" if expected in {"POLYGON", "ADMIN"} else "best_available")
        return GeometryStrategy(key or "unknown", expected, ("geocoder_bbox", "geocoder_point"), fallback, point_is_valid=expected == "POINT")

    @classmethod
    def source_label(cls, source: str | None) -> str:
        value = str(source or "missing")
        return cls.SOURCE_LABELS.get(value, value.replace("_", " ").strip().capitalize())

    @classmethod
    def method_label(cls, method: str | None) -> str:
        value = str(method or "missing_geometry")
        if value in cls.METHOD_LABELS:
            return cls.METHOD_LABELS[value]
        if value.startswith("estimated_") and "_extent_" in value:
            stem, radius = value.rsplit("_extent_", 1)
            feature = stem.replace("estimated_", "").replace("_", " ")
            return f"Estensione semantica stimata per {feature} ({radius})"
        return value.replace("_", " ").strip().capitalize()

    def enrich_metadata(self, metadata: Optional[Mapping[str, Any]], *, feature_type: str, source: str, method: str) -> dict[str, Any]:
        result = dict(metadata or {})
        strategy = self.strategy_for(feature_type)
        result.update({
            "unified_slge": True,
            "strategy_feature_type": strategy.feature_type,
            "strategy_expected_geometry": strategy.expected_geometry,
            "source_label": self.source_label(source),
            "method_label": self.method_label(method),
            "fallback_mode": strategy.fallback_mode,
        })
        return result
