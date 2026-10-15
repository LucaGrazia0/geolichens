"""Resolver for named area localities such as valleys, forests and water bodies."""

from .base_resolver import BaseResolver
from .geometry_helpers import clone_geometry, geometry_from_feature, geometry_type_name


class AreaResolver(BaseResolver):
    semantic_type = "area"
    resolver_family = "area"

    AREA_TYPES = {
        "valley", "forest_area", "hydro", "mountain_area", "mountain_group",
        "area", "plateau", "basin", "plain",
    }

    def resolve(self, context):
        context = context or {}
        semantic_type = self._semantic_type(context, "area")
        feature = context.get("feature")

        candidates = (
            (context.get("official_polygon_geometry"), "official_polygon", "official_polygon"),
            (context.get("osm_polygon_geometry"), "osm_polygon", "osm_polygon"),
            (context.get("terrain_polygon_geometry"), "terrain_reconstruction", "terrain_polygon"),
        )
        for value, source, method in candidates:
            geometry = clone_geometry(value)
            if geometry_type_name(geometry) == "POLYGON":
                confidence = {"official_polygon": 0.96, "osm_polygon": 0.90, "terrain_reconstruction": 0.76}[source]
                return self._result(
                    geometry=geometry,
                    geometry_type="POLYGON",
                    semantic_type=semantic_type,
                    decision="AREA_POLYGON_ACCEPTED",
                    source=source,
                    method=method,
                    confidence=confidence,
                    requires_review=source == "terrain_reconstruction",
                    metadata={"geometry_priority": source, "semantic_compatibility": True},
                )

        decoded, decoded_source = geometry_from_feature(feature)
        if geometry_type_name(decoded) == "POLYGON" and decoded_source == "provider_geojson":
            return self._result(
                geometry=decoded,
                geometry_type="POLYGON",
                semantic_type=semantic_type,
                decision="PROVIDER_AREA_POLYGON_ACCEPTED",
                source=decoded_source,
                method="provider_polygon",
                confidence=0.86,
                metadata={"geometry_priority": "provider_polygon", "semantic_compatibility": True},
            )

        bbox = clone_geometry(context.get("bbox_geometry"))
        if bbox is None and geometry_type_name(decoded) == "POLYGON":
            bbox = decoded
        if geometry_type_name(bbox) == "POLYGON":
            return self._result(
                geometry=bbox,
                geometry_type="POLYGON",
                semantic_type=semantic_type,
                decision="AREA_BBOX_ACCEPTED_WITH_REVIEW",
                source="geocoder_bbox",
                method="provider_bbox",
                confidence=0.70,
                requires_review=True,
                metadata={
                    "geometry_priority": "provider_bbox",
                    "semantic_compatibility": True,
                    "review_reason": "bbox_is_cartographic_extent_not_verified_feature_boundary",
                },
            )

        return self._failed(
            semantic_type,
            "AREA_POLYGON_UNAVAILABLE",
            "area_polygon_hierarchy_exhausted",
            {
                "available_geometry_type": geometry_type_name(decoded),
                "fallback_expected": "semantic_extent_builder",
            },
        )
