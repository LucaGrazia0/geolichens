from .base_resolver import BaseResolver
from .geometry_helpers import clone_geometry, geometry_from_feature, geometry_type_name
from ..geometry_provenance import GeometryProvenance
from ..geometry_result import GeometryResult


class MunicipalityResolver(BaseResolver):
    """Resolve municipality documentary geometry from administrative hits.

    Phase 15.4.4 activates the resolver without pretending that an official
    municipal-layer provider already exists. A provider polygon/bbox is used
    when available; point-only hits remain an explicit failure so the proven
    semantic municipality fallback can still run.
    """

    semantic_type = "municipality"

    def resolve(self, context):
        context = context or {}
        feature = context.get("feature") if isinstance(context, dict) else None
        supplied_bbox = context.get("bbox_geometry") if isinstance(context, dict) else None

        geometry = clone_geometry(supplied_bbox)
        source = "geocoder_administrative_bbox" if geometry is not None else ""
        if geometry is None:
            geometry, decoded_source = geometry_from_feature(feature)
            source = decoded_source

        geometry_type = geometry_type_name(geometry)
        if geometry_type != "POLYGON":
            return self._failed(
                decision="ADMINISTRATIVE_POLYGON_UNAVAILABLE",
                method=source or "municipality_polygon_missing",
                metadata={
                    "context_received": bool(context),
                    "available_geometry_type": geometry_type,
                    "official_layer_lookup_implemented": False,
                },
            )

        confidence = self._confidence(feature, source)
        requires_review = source not in {"provider_geojson"}
        provenance = GeometryProvenance(
            resolver_name=self.__class__.__name__,
            source=source or "geocoder_administrative_geometry",
            geometry_type="POLYGON",
            confidence=confidence,
            fallback_used=False,
        )
        return GeometryResult(
            geometry=geometry,
            geometry_type="POLYGON",
            semantic_type=self.semantic_type,
            resolver=self.__class__.__name__,
            decision="ADMINISTRATIVE_POLYGON_ACCEPTED",
            source=provenance.source,
            method="provider_polygon" if source == "provider_geojson" else "provider_bbox",
            confidence=confidence,
            requires_review=requires_review,
            fallback_used=False,
            provenance=provenance,
            metadata={
                "authoritative_geometry": True,
                "official_layer_lookup_implemented": False,
                "review_reason": "bbox_requires_provider_verification" if requires_review else "",
            },
        )

    @staticmethod
    def _confidence(feature, source):
        if source == "provider_geojson":
            return 0.90
        if source in {"geocoder_administrative_bbox", "provider_bbox"}:
            return 0.78
        return 0.0

    def _failed(self, decision, method, metadata=None):
        provenance = GeometryProvenance(
            resolver_name=self.__class__.__name__,
            source="municipality_geometry_unavailable",
            geometry_type="NONE",
            confidence=0.0,
            fallback_used=True,
        )
        return GeometryResult(
            geometry=None,
            geometry_type="NONE",
            semantic_type=self.semantic_type,
            resolver=self.__class__.__name__,
            decision=decision,
            source=provenance.source,
            method=method,
            confidence=0.0,
            requires_review=True,
            fallback_used=True,
            provenance=provenance,
            metadata=dict(metadata or {}),
        )
