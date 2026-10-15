"""Unified geometry-resolution result for GeoLichen 15.4.5 Geometry Core.

The object is deliberately QGIS-agnostic at import time: ``geometry`` may be a
QgsGeometry in the running plugin, but no QGIS import is required here.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .geometry_provenance import GeometryProvenance
from .geometry_validation import validate_geometry


@dataclass
class GeometryResult:
    geometry: Any = None
    geometry_type: str = "NONE"
    semantic_type: str = ""
    resolver: str = ""
    decision: str = "FAILED"
    source: str = ""
    method: str = ""
    confidence: float = 0.0
    requires_review: bool = False
    fallback_used: bool = False
    provenance: Optional[GeometryProvenance] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    stage: str = "documented"

    def __post_init__(self):
        self.geometry_type = str(self.geometry_type or "NONE").upper()
        self.semantic_type = str(self.semantic_type or "")
        self.resolver = str(self.resolver or "")
        self.stage = str(self.stage or "documented").lower()
        try:
            self.confidence = max(0.0, min(1.0, float(self.confidence or 0.0)))
        except Exception:
            self.confidence = 0.0
        self.metadata = dict(self.metadata or {})
        self._apply_validation()

    def _apply_validation(self):
        report = validate_geometry(self.geometry, self.geometry_type)
        self.metadata["geometry_validation"] = report.to_dict()
        # Normalize stale/unknown declarations to the actual runtime type.
        if report.available and report.actual_type not in {"UNKNOWN", "EMPTY", "NONE"}:
            if self.geometry_type in {"NONE", "UNKNOWN", "EMPTY"}:
                self.geometry_type = report.actual_type
            elif self.geometry_type != report.actual_type:
                self.requires_review = True
                self.metadata.setdefault("declared_geometry_type", self.geometry_type)
        if report.available and not report.valid:
            self.requires_review = True

    @property
    def validation(self) -> Dict[str, Any]:
        return dict(self.metadata.get("geometry_validation") or {})

    @property
    def success(self) -> bool:
        validation = self.validation
        if validation:
            return bool(validation.get("available"))
        try:
            return self.geometry is not None and not self.geometry.isEmpty()
        except Exception:
            return self.geometry is not None

    @property
    def valid(self) -> bool:
        return bool(self.validation.get("valid", self.success))

    def revalidate(self):
        self._apply_validation()
        return self

    def to_dict(self, include_geometry: bool = True) -> Dict[str, Any]:
        provenance = self.provenance.to_dict() if self.provenance is not None else {}
        value = {
            "geometry_type": self.geometry_type,
            "semantic_type": self.semantic_type,
            "resolver": self.resolver,
            "decision": self.decision,
            "source": self.source,
            "method": self.method,
            "confidence": float(self.confidence or 0.0),
            "requires_review": bool(self.requires_review),
            "fallback_used": bool(self.fallback_used),
            "provenance": provenance,
            "metadata": dict(self.metadata or {}),
            "stage": self.stage,
            "success": self.success,
            "valid": self.valid,
        }
        if include_geometry:
            value["geometry"] = self.geometry
        return value

    @classmethod
    def from_legacy(cls, value: Any, semantic_type: str = "", resolver: str = "", stage: str = "documented"):
        if isinstance(value, cls):
            if stage and not value.stage:
                value.stage = stage
            return value.revalidate()
        if not isinstance(value, dict):
            return cls(semantic_type=semantic_type, resolver=resolver, decision="FAILED", stage=stage)
        provenance = value.get("provenance")
        if isinstance(provenance, dict):
            provenance = GeometryProvenance.from_dict(provenance)
        return cls(
            geometry=value.get("geometry"),
            geometry_type=str(value.get("geometry_type") or "NONE"),
            semantic_type=str(value.get("semantic_type") or semantic_type or ""),
            resolver=str(value.get("resolver") or getattr(provenance, "resolver_name", "") or resolver or ""),
            decision=str(value.get("decision") or ("SUCCESS" if value.get("geometry") is not None else "FAILED")),
            source=str(value.get("source") or getattr(provenance, "source", "") or ""),
            method=str(value.get("method") or value.get("strategy") or ""),
            confidence=float(value.get("confidence", getattr(provenance, "confidence", 0.0)) or 0.0),
            requires_review=bool(value.get("requires_review", False)),
            fallback_used=bool(value.get("fallback_used", getattr(provenance, "fallback_used", False))),
            provenance=provenance,
            metadata=dict(value.get("metadata") or {}),
            stage=str(value.get("stage") or stage or "documented"),
        )
