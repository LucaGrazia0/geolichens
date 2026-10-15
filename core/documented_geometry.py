"""Immutable documentary geometry model for the GeoLichen SLGE.

This module deliberately contains no geocoding or buffering logic.  It stores
what is known (or explicitly estimated) about the locality described by the
source record.  Later phases may use it for point-radius calculations, reports
and provenance, but must not mutate it for ecological search purposes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional


def _bounded_confidence(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class DocumentedGeometry:
    """Documented representation of the locality named by the record.

    ``geometry`` is normally a ``QgsGeometry`` at runtime, but remains typed as
    ``Any`` so this core data model is importable in tests outside QGIS.
    """

    geometry: Any
    feature_type: str
    geometry_type: str
    source: str
    method: str
    confidence: float = 0.0
    estimated: bool = False
    requires_review: bool = False
    source_identifier: Optional[str] = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_type", str(self.feature_type or "unknown"))
        object.__setattr__(self, "geometry_type", str(self.geometry_type or "unknown").upper())
        object.__setattr__(self, "source", str(self.source or "unknown"))
        object.__setattr__(self, "method", str(self.method or "unknown"))
        object.__setattr__(self, "confidence", _bounded_confidence(self.confidence))
        object.__setattr__(self, "notes", tuple(self.notes or ()))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @property
    def is_available(self) -> bool:
        if self.geometry is None:
            return False
        try:
            return not self.geometry.isEmpty()
        except AttributeError:
            return True
        except Exception:
            return False

    @property
    def confidence_percent(self) -> int:
        return int(round(self.confidence * 100.0))

    def provenance_dict(self) -> Dict[str, Any]:
        return {
            "feature_type": self.feature_type,
            "geometry_type": self.geometry_type,
            "source": self.source,
            "source_identifier": self.source_identifier,
            "method": self.method,
            "confidence": self.confidence,
            "estimated": bool(self.estimated),
            "requires_review": bool(self.requires_review),
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
        }
