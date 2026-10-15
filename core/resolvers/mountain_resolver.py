"""Hierarchical resolver for mountain names and mountain systems."""

from .area_resolver import AreaResolver
from .point_resolver import PointResolver


class MountainResolver(AreaResolver):
    semantic_type = "mountain"
    resolver_family = "mountain"

    POINT_MOUNTAIN_TYPES = {"summit", "summit_peak", "pass", "hill"}
    AREA_MOUNTAIN_TYPES = {"mountain_area", "mountain_group", "mountain", "massif", "ridge"}

    def __init__(self):
        self._point = PointResolver()

    def resolve(self, context):
        context = dict(context or {})
        semantic_type = self._semantic_type(context, "mountain")

        # Peaks and passes are genuinely point-like documentary features. Their
        # operational search area is still built later by the Search Geometry
        # pipeline and must not be confused with the documented point.
        if semantic_type in self.POINT_MOUNTAIN_TYPES:
            result = self._point.resolve(context)
            result.metadata["resolver_family"] = self.resolver_family
            result.metadata["mountain_geometry_mode"] = "named_point"
            return result

        # Area-like mountain names follow the explicit polygon hierarchy:
        # official -> OSM -> terrain -> provider polygon -> provider bbox.
        result = super().resolve(context)
        result.metadata["resolver_family"] = self.resolver_family
        result.metadata["mountain_geometry_mode"] = "area_hierarchy"
        result.metadata["mountain_polygon_hierarchy"] = [
            "official_polygon", "osm_polygon", "terrain_polygon",
            "provider_polygon", "provider_bbox", "semantic_fallback",
        ]
        return result
