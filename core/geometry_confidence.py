"""Geometry Confidence Index (GCI) for GeoLichen SLGE Phase 12, Block D.

The index estimates how trustworthy the *documentary* locality geometry is.
It never measures ecological suitability and must not be mixed with GSS, MCI
or SSI.  The calculation is deterministic and exposes every adjustment used.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple


@dataclass(frozen=True)
class GeometryConfidenceResult:
    score: float
    confidence_class: str
    reasons: Tuple[str, ...]
    components: Dict[str, float]


class GeometryConfidenceService:
    SOURCE_BASE = {
        "official_admin_polygon": 1.00,
        "official_polygon": 0.98,
        "osm_polygon": 0.92,
        "osm_line": 0.90,
        "geocoder_polygon": 0.88,
        "geocoder_bbox": 0.82,
        "dem_reconstructed": 0.72,
        "semantic_estimate": 0.60,
        "geocoder_point": 0.68,
        "osm_point": 0.82,
        "official_point": 0.92,
        "point_proxy": 0.52,
        "geocoder_line": 0.76,
        "official_line": 0.94,
        "fallback": 0.40,
        "missing": 0.0,
    }

    @staticmethod
    def classify(score: float) -> str:
        score = max(0.0, min(1.0, float(score or 0.0)))
        if score >= 0.90:
            return "molto_alta"
        if score >= 0.75:
            return "alta"
        if score >= 0.50:
            return "media"
        if score >= 0.30:
            return "bassa"
        return "molto_bassa"

    def calculate(
        self,
        *,
        source_kind: str,
        documented_geometry: Any,
        actual_geometry_type: str,
        expected_geometry_type: str,
        semantic_confidence: float,
        estimated: bool,
        requires_review: bool,
    ) -> GeometryConfidenceResult:
        source_kind = str(source_kind or "missing")
        base = float(self.SOURCE_BASE.get(source_kind, self.SOURCE_BASE["fallback"]))
        reasons = [f"Affidabilità base della sorgente '{source_kind}': {base:.2f}"]
        components: Dict[str, float] = {"source_base": base}

        actual = str(actual_geometry_type or "UNKNOWN").upper()
        expected = str(expected_geometry_type or "UNKNOWN").upper()
        geometry_available = documented_geometry is not None
        try:
            geometry_available = geometry_available and not documented_geometry.isEmpty()
        except Exception:
            pass

        match_adjustment = 0.0
        if not geometry_available:
            match_adjustment = -0.30
            reasons.append("Geometria documentale assente: −0.30")
        elif expected == "ADMIN":
            if actual == "POLYGON":
                match_adjustment = 0.06
                reasons.append("Geometria amministrativa areale coerente: +0.06")
            else:
                match_adjustment = -0.15
                reasons.append(f"Geometria {actual} non adeguata a un confine amministrativo: −0.15")
        elif expected == "UNKNOWN":
            match_adjustment = 0.02
            reasons.append("Toponimo generico con geometria disponibile: +0.02")
        elif actual == expected:
            # A matching point for a pass/peak/refuge is a complete geometry,
            # not a lower-quality substitute for an area.
            match_adjustment = 0.10 if expected == "POINT" else 0.06
            reasons.append(f"Geometria {actual} pienamente coerente con quella attesa: +{match_adjustment:.2f}")
        elif expected == "LINE" and actual == "POINT":
            match_adjustment = -0.08
            reasons.append("Punto rappresentativo disponibile, ma manca il tracciato lineare: −0.08")
        else:
            match_adjustment = -0.12
            reasons.append(f"Geometria {actual} diversa da quella attesa {expected}: −0.12")
        components["geometry_match"] = match_adjustment

        try:
            semantic_confidence = max(0.0, min(1.0, float(semantic_confidence)))
        except (TypeError, ValueError):
            semantic_confidence = 0.0
        semantic_adjustment = (semantic_confidence - 0.50) * 0.10
        components["semantic_interpretation"] = semantic_adjustment
        reasons.append(
            f"Confidenza dell'interpretazione semantica {semantic_confidence:.2f}: "
            f"{semantic_adjustment:+.2f}"
        )

        estimated_penalty = -0.10 if estimated else 0.0
        complete_point = bool(geometry_available and expected == "POINT" and actual == "POINT")
        review_penalty = -0.05 if (requires_review and not complete_point) else 0.0
        components["estimated_penalty"] = estimated_penalty
        components["review_penalty"] = review_penalty
        if estimated:
            reasons.append("Geometria stimata: −0.10")
        if requires_review:
            reasons.append("Verifica manuale richiesta: −0.05")

        score = max(0.0, min(1.0, base + match_adjustment + semantic_adjustment + estimated_penalty + review_penalty))
        reasons.append(f"GCI finale: {score:.2f}")
        return GeometryConfidenceResult(
            score=score,
            confidence_class=self.classify(score),
            reasons=tuple(reasons),
            components=components,
        )
