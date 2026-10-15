"""Base classes shared by the SLGE 2.0 semantic resolvers."""

from ..geometry_provenance import GeometryProvenance
from ..geometry_result import GeometryResult


class BaseResolver:
    semantic_type = None
    resolver_family = "generic"

    def resolve(self, context):
        raise NotImplementedError

    @staticmethod
    def _semantic_type(context, fallback="place"):
        context = context or {}
        return str(context.get("semantic_type") or context.get("ref_type") or fallback).strip().lower()

    def _result(
        self,
        *,
        geometry=None,
        geometry_type="NONE",
        semantic_type="",
        decision="FAILED",
        source="",
        method="",
        confidence=0.0,
        requires_review=False,
        fallback_used=False,
        metadata=None,
    ):
        metadata = dict(metadata or {})
        metadata.setdefault("resolver_family", self.resolver_family)
        metadata.setdefault("semantic_resolver_version", "SLGE-2.0")
        provenance = GeometryProvenance(
            resolver_name=self.__class__.__name__,
            source=str(source or ""),
            geometry_type=str(geometry_type or "NONE").upper(),
            confidence=float(confidence or 0.0),
            fallback_used=bool(fallback_used),
        )
        return GeometryResult(
            geometry=geometry,
            geometry_type=geometry_type,
            semantic_type=semantic_type,
            resolver=self.__class__.__name__,
            decision=decision,
            source=source,
            method=method,
            confidence=confidence,
            requires_review=requires_review,
            fallback_used=fallback_used,
            provenance=provenance,
            metadata=metadata,
            stage="documented",
        )

    def _failed(self, semantic_type, decision, method, metadata=None):
        return self._result(
            semantic_type=semantic_type,
            decision=decision,
            source=f"{self.resolver_family}_geometry_unavailable",
            method=method,
            confidence=0.0,
            requires_review=True,
            fallback_used=True,
            metadata=metadata,
        )
