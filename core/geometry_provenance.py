from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class GeometryProvenance:
    resolver_name: str
    source: str
    geometry_type: str
    confidence: float = 1.0
    fallback_used: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolver_name": self.resolver_name,
            "source": self.source,
            "geometry_type": self.geometry_type,
            "confidence": float(self.confidence or 0.0),
            "fallback_used": bool(self.fallback_used),
        }

    @classmethod
    def from_dict(cls, value):
        value = value or {}
        return cls(
            resolver_name=str(value.get("resolver_name") or value.get("resolver") or ""),
            source=str(value.get("source") or ""),
            geometry_type=str(value.get("geometry_type") or "NONE"),
            confidence=float(value.get("confidence", 0.0) or 0.0),
            fallback_used=bool(value.get("fallback_used", False)),
        )
