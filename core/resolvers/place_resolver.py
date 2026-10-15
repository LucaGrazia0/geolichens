from .base_resolver import BaseResolver
from .geometry_helpers import clone_geometry, geometry_from_feature, geometry_type_name
from ..geometry_provenance import GeometryProvenance
from ..geometry_result import GeometryResult


class PlaceResolver(BaseResolver):
    """Resolve provider geometry for non-administrative localities.

    It accepts explicit provider polygons/lines. Point geometries are accepted
    only for point-like semantic classes; area-like localities deliberately
    fall back to the existing semantic extent builder.
    """

    semantic_type = "place"

    AREA_LIKE = {
        "valley", "forest_area", "hydro", "mountain_area", "mountain_group",
    }
    LINE_LIKE = {"trail"}
    POINT_LIKE = {
        "pass", "summit", "summit_peak", "hill", "refuge_malga",
        "nearby_place", "generic_toponym", "locality", "place", "meadow",
    }

    def resolve(self, context):
        context = context or {}
        semantic_type = str(context.get("semantic_type") or context.get("ref_type") or "place")
        feature = context.get("feature")
        supplied_bbox = context.get("bbox_geometry")

        geometry = None
        source = ""
        # Prefer an explicit provider geometry over the generic bbox.
        decoded, decoded_source = geometry_from_feature(feature)
        decoded_type = geometry_type_name(decoded)
        if decoded_type in {"POLYGON", "LINE"}:
            geometry, source = decoded, decoded_source
        elif supplied_bbox is not None:
            geometry, source = clone_geometry(supplied_bbox), "geocoder_bbox"
        elif decoded is not None:
            geometry, source = decoded, decoded_source

        geometry_type = geometry_type_name(geometry)
        accepted = self._is_compatible(semantic_type, geometry_type)
        if not accepted:
            return self._failed(
                semantic_type,
                geometry_type,
                source or "place_geometry_missing",
                "SEMANTIC_GEOMETRY_REQUIRED" if geometry_type == "POINT" else "COMPATIBLE_GEOMETRY_UNAVAILABLE",
            )

        confidence = self._confidence(geometry_type, source)
        requires_review = source in {"geocoder_bbox", "provider_bbox"}
        provenance = GeometryProvenance(
            resolver_name=self.__class__.__name__,
            source=source or "provider_geometry",
            geometry_type=geometry_type,
            confidence=confidence,
            fallback_used=False,
        )
        return GeometryResult(
            geometry=geometry,
            geometry_type=geometry_type,
            semantic_type=semantic_type,
            resolver=self.__class__.__name__,
            decision="PROVIDER_GEOMETRY_ACCEPTED",
            source=provenance.source,
            method="provider_geometry",
            confidence=confidence,
            requires_review=requires_review,
            fallback_used=False,
            provenance=provenance,
            metadata={
                "semantic_compatibility": True,
                "canonical_semantic_type": semantic_type,
                "review_reason": "bbox_extent_requires_verification" if requires_review else "",
            },
        )

    def _is_compatible(self, semantic_type, geometry_type):
        if geometry_type == "POLYGON":
            return True
        if geometry_type == "LINE":
            return semantic_type in self.LINE_LIKE or semantic_type not in self.AREA_LIKE
        if geometry_type == "POINT":
            return semantic_type in self.POINT_LIKE
        return False

    @staticmethod
    def _confidence(geometry_type, source):
        if source == "provider_geojson":
            return 0.88 if geometry_type == "POLYGON" else 0.84
        if source in {"geocoder_bbox", "provider_bbox"}:
            return 0.72
        if geometry_type == "POINT":
            return 0.68
        return 0.60

    def _failed(self, semantic_type, geometry_type, method, decision):
        provenance = GeometryProvenance(
            resolver_name=self.__class__.__name__,
            source="place_geometry_unavailable",
            geometry_type="NONE",
            confidence=0.0,
            fallback_used=True,
        )
        return GeometryResult(
            geometry=None,
            geometry_type="NONE",
            semantic_type=semantic_type,
            resolver=self.__class__.__name__,
            decision=decision,
            source=provenance.source,
            method=method,
            confidence=0.0,
            requires_review=True,
            fallback_used=True,
            provenance=provenance,
            metadata={
                "available_geometry_type": geometry_type,
                "semantic_compatibility": False,
            },
        )
