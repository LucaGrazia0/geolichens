"""Data models for Phase 13D.1 terrain-geometry validation.

The validation layer is deliberately independent from the later decision and
integration stages.  It evaluates the candidate polygon produced by Phase 13C
and returns a transparent, immutable set of checks without mutating SLGE,
DocumentedGeometry, SearchGeometry or the GBIF calculation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class TerrainGeometryCheck:
    """Result of one explicit validation rule."""

    name: str
    passed: bool
    required: bool = True
    value: Any = None
    threshold: Any = None
    score: float = 1.0
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name or "unnamed_check"))
        object.__setattr__(self, "passed", bool(self.passed))
        object.__setattr__(self, "required", bool(self.required))
        object.__setattr__(self, "score", max(0.0, min(1.0, float(self.score or 0.0))))
        object.__setattr__(self, "message", str(self.message or ""))

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "required": self.required,
            "value": self.value,
            "threshold": self.threshold,
            "score": self.score,
            "message": self.message,
        }


@dataclass(frozen=True)
class TerrainGeometryValidationResult:
    """Immutable Phase 13D.1 validation result."""

    available: bool
    valid: bool = False
    confidence: float = 0.0
    fallback_required: bool = True
    manual_review_recommended: bool = False
    checks: Tuple[TerrainGeometryCheck, ...] = field(default_factory=tuple)
    failed_required_checks: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "available", bool(self.available))
        object.__setattr__(self, "valid", bool(self.valid))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence or 0.0))))
        object.__setattr__(self, "fallback_required", bool(self.fallback_required))
        object.__setattr__(self, "manual_review_recommended", bool(self.manual_review_recommended))
        object.__setattr__(self, "checks", tuple(self.checks or ()))
        object.__setattr__(self, "failed_required_checks", tuple(self.failed_required_checks or ()))
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))

    @classmethod
    def unavailable(
        cls,
        *warnings: str,
        provenance: Optional[Mapping[str, Any]] = None,
    ) -> "TerrainGeometryValidationResult":
        return cls(
            available=False,
            valid=False,
            confidence=0.0,
            fallback_required=True,
            manual_review_recommended=True,
            warnings=tuple(str(value) for value in warnings if value),
            provenance=dict(provenance or {}),
        )

    @property
    def passed_check_count(self) -> int:
        return sum(1 for check in self.checks if check.passed)

    @property
    def check_count(self) -> int:
        return len(self.checks)

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "valid": self.valid,
            "confidence": self.confidence,
            "fallback_required": self.fallback_required,
            "manual_review_recommended": self.manual_review_recommended,
            "passed_check_count": self.passed_check_count,
            "check_count": self.check_count,
            "failed_required_checks": list(self.failed_required_checks),
            "checks": [check.summary_dict() for check in self.checks],
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }
