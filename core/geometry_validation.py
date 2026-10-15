"""Central geometry validation for GeoLichen 15.4.5 Geometry Core.

The module deliberately avoids importing QGIS. Runtime geometries are inspected
through their public methods, which also makes the validator usable in light
unit tests with geometry doubles.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


_GEOMETRY_TYPE_NAMES = {0: "POINT", 1: "LINE", 2: "POLYGON"}


def actual_geometry_type(geometry: Any) -> str:
    if geometry is None:
        return "NONE"
    try:
        if geometry.isEmpty():
            return "EMPTY"
    except Exception:
        pass
    try:
        return _GEOMETRY_TYPE_NAMES.get(int(geometry.type()), "UNKNOWN")
    except Exception:
        return "UNKNOWN"


@dataclass(frozen=True)
class GeometryValidationReport:
    valid: bool
    available: bool
    declared_type: str
    actual_type: str
    type_matches: bool
    bbox_valid: bool
    bbox_width: float = 0.0
    bbox_height: float = 0.0
    issues: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": bool(self.valid),
            "available": bool(self.available),
            "declared_type": self.declared_type,
            "actual_type": self.actual_type,
            "type_matches": bool(self.type_matches),
            "bbox_valid": bool(self.bbox_valid),
            "bbox_width": float(self.bbox_width),
            "bbox_height": float(self.bbox_height),
            "issues": list(self.issues),
        }


def validate_geometry(geometry: Any, declared_type: str = "") -> GeometryValidationReport:
    declared = str(declared_type or "").strip().upper() or "UNKNOWN"
    actual = actual_geometry_type(geometry)
    issues = []
    available = actual not in {"NONE", "EMPTY"}

    if not available:
        issues.append("geometry_missing_or_empty")

    type_matches = declared in {"", "UNKNOWN", "NONE"} or declared == actual
    if available and not type_matches:
        issues.append("declared_actual_type_mismatch")

    bbox_valid = False
    bbox_width = 0.0
    bbox_height = 0.0
    if available:
        try:
            bbox = geometry.boundingBox()
            bbox_width = float(bbox.width())
            bbox_height = float(bbox.height())
            if actual == "POINT":
                bbox_valid = True
            elif actual == "LINE":
                bbox_valid = bbox_width > 0.0 or bbox_height > 0.0
            elif actual == "POLYGON":
                bbox_valid = bbox_width > 0.0 and bbox_height > 0.0
            else:
                bbox_valid = bbox_width >= 0.0 and bbox_height >= 0.0
        except Exception:
            issues.append("bounding_box_unavailable")

    if available and not bbox_valid:
        issues.append("degenerate_bounding_box")

    valid = bool(available and type_matches and bbox_valid)
    return GeometryValidationReport(
        valid=valid,
        available=available,
        declared_type=declared,
        actual_type=actual,
        type_matches=type_matches,
        bbox_valid=bbox_valid,
        bbox_width=bbox_width,
        bbox_height=bbox_height,
        issues=tuple(issues),
    )
