"""Resolver for genuinely point-like named localities."""

from .base_resolver import BaseResolver
from .geometry_helpers import clone_geometry, point_geometry_from_feature, geometry_type_name


class PointResolver(BaseResolver):
    semantic_type = "point"
    resolver_family = "point"

    POINT_TYPES = {
        "pass", "summit", "summit_peak", "hill", "refuge_malga",
        "nearby_place", "generic_toponym", "locality", "place", "meadow",
    }

    def resolve(self, context):
        context = context or {}
        semantic_type = self._semantic_type(context, "point")
        feature = context.get("feature")

        geometry = clone_geometry(context.get("point_geometry"))
        source = "explicit_point_geometry" if geometry is not None else ""
        if geometry is None:
            decoded, decoded_source = point_geometry_from_feature(feature)
            geometry, source = decoded, decoded_source

        geometry_type = geometry_type_name(geometry)
        if geometry_type != "POINT":
            return self._failed(
                semantic_type,
                "POINT_GEOMETRY_UNAVAILABLE",
                source or "point_geometry_missing",
                {"available_geometry_type": geometry_type},
            )

        confidence = 0.84 if source == "provider_geojson_point" else 0.76
        if source in {"provider_center", "provider_coordinates"}:
            confidence = 0.72
        return self._result(
            geometry=geometry,
            geometry_type="POINT",
            semantic_type=semantic_type,
            decision="POINT_GEOMETRY_ACCEPTED",
            source=source or "provider_point",
            method="named_point",
            confidence=confidence,
            requires_review=confidence < 0.75,
            metadata={
                "geometry_role": "complete_documentary_geometry",
                "semantic_compatibility": True,
                "point_is_complete": True,
            },
        )
