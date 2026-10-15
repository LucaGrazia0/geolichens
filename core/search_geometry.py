"""Mutable operational search geometry model for GeoLichen.

Unlike :class:`DocumentedGeometry`, this object may evolve during the search
pipeline (altitude expansion, environmental clipping, water masks, etc.).
Those operations must never mutate the documentary geometry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


@dataclass
class SearchGeometry:
    geometry: Any
    strategy: str
    source: str = "derived_from_documented_geometry"
    expanded: bool = False
    clipped: bool = False
    filters: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

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

    def add_filter(self, name: str, geometry_changed: bool = True, **details: Any) -> None:
        name = str(name or "").strip()
        if name and name not in self.filters:
            self.filters.append(name)
        if details:
            self.metadata.setdefault("filter_details", {})[name] = dict(details)
        if geometry_changed:
            self.clipped = True

    def record_expansion(self, reason: str, **details: Any) -> None:
        self.expanded = True
        reason = str(reason or "unspecified")
        self.notes.append(f"Expansion: {reason}")
        if details:
            self.metadata.setdefault("expansions", []).append({"reason": reason, **details})

    def replace_geometry(self, geometry: Any, reason: Optional[str] = None) -> None:
        self.geometry = geometry
        if reason:
            self.notes.append(str(reason))

    def provenance_dict(self) -> Mapping[str, Any]:
        return {
            "strategy": self.strategy,
            "source": self.source,
            "expanded": bool(self.expanded),
            "clipped": bool(self.clipped),
            "filters": list(self.filters),
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
        }
