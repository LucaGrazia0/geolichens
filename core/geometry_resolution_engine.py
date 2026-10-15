"""Geometry Resolution Engine orchestrator — GeoLichen 15.4.5 Sprint 3 / SLGE 2.0."""
from .geometry_result import GeometryResult
from .resolvers.registry import ResolverRegistry


class GeometryResolutionEngine:
    def __init__(self, registry=None):
        self.registry = registry or ResolverRegistry()

    def resolve(self, semantic_type, context):
        semantic_type = str(semantic_type or "").strip().lower()
        context = dict(context or {})
        context.setdefault("semantic_type", semantic_type)
        resolver = self.registry.get(semantic_type)
        if resolver is None:
            return GeometryResult(
                semantic_type=semantic_type,
                resolver="SemanticFallbackResolver",
                decision="NO_REGISTERED_RESOLVER",
                source="",
                method="resolver_not_registered",
                confidence=0.0,
                requires_review=True,
                fallback_used=True,
                metadata={"registered": False},
                stage="documented",
            )
        try:
            value = resolver.resolve(context)
            result = GeometryResult.from_legacy(
                value,
                semantic_type=semantic_type,
                resolver=resolver.__class__.__name__,
                stage="documented",
            )
            if not result.resolver:
                result.resolver = resolver.__class__.__name__
            result.metadata.setdefault("registry_semantic_type", semantic_type)
            result.metadata.setdefault("resolver_class", resolver.__class__.__name__)
            result.metadata.setdefault("resolver_family", getattr(resolver, "resolver_family", "generic"))
            result.metadata.setdefault("semantic_resolver_version", "SLGE-2.0")
            result.metadata.setdefault("semantic_confidence_components", {
                "interpretation": float(getattr(context.get("interpretation"), "confidence", 0.0) or 0.0),
                "geometry": float(result.confidence or 0.0),
                "source": float(result.confidence or 0.0),
            })
            # Invalid non-empty geometry remains visible for diagnostics but is
            # not silently treated as an authoritative success.
            if result.success and not result.valid:
                result.requires_review = True
                result.metadata.setdefault("core_warning", "geometry_requires_validation_review")
            return result
        except Exception as exc:
            return GeometryResult(
                semantic_type=semantic_type,
                resolver=resolver.__class__.__name__,
                decision="ERROR",
                method="resolver_exception",
                confidence=0.0,
                requires_review=True,
                fallback_used=True,
                metadata={"error": str(exc)},
                stage="documented",
            )
