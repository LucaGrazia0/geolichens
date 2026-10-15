"""Semantic locality parser used by the GeoLichen SLGE (Block A).

The parser is deterministic and intentionally conservative.  It classifies
what the locality text *means* without creating a geometry or changing the
legacy geocoding pipeline.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Pattern

from .resolved_locality import LocalityInterpretation


@dataclass(frozen=True)
class _Rule:
    feature_type: str
    expected_geometry: str
    confidence: float
    name: str
    pattern: Pattern[str]


class SemanticLocalityParser:
    RULES: tuple[_Rule, ...] = (
        _Rule("municipality", "ADMIN", 0.99, "municipality", re.compile(r"\b(?:comune\s+di|nel\s+comune\s+di|in\s+comune\s+di)\b")),
        _Rule("mountain_group", "POLYGON", 0.96, "mountain_group", re.compile(r"\b(?:gruppo|massiccio|catena|dorsale)\b")),
        _Rule("mountain", "POLYGON", 0.94, "mountain", re.compile(r"\b(?:monte|montagna|mt\.)\b")),
        _Rule("hill", "POLYGON", 0.88, "hill", re.compile(r"\b(?:colle|dosso|poggio)\b")),
        _Rule("peak", "POINT", 0.94, "peak", re.compile(r"\b(?:cima|vetta|pizzo|punta|corno)\b")),
        _Rule("pass", "POINT", 0.93, "pass", re.compile(r"\b(?:passo|forcella|sella|bocchetta)\b")),
        _Rule("valley", "POLYGON", 0.94, "valley", re.compile(r"\b(?:valle|val\s+d[' ]|val\s+di|val\s+)\b")),
        _Rule("lake", "POLYGON", 0.94, "lake", re.compile(r"\b(?:lago|laguna|stagno|bacino)\b")),
        _Rule("river", "LINE", 0.91, "river", re.compile(r"\b(?:fiume|torrente|rio|rivo|canale)\b")),
        _Rule("glacier", "POLYGON", 0.94, "glacier", re.compile(r"\b(?:ghiacciaio|vedretta)\b")),
        _Rule("forest", "POLYGON", 0.94, "forest", re.compile(r"\b(?:foresta|bosco|selva)\b")),
        _Rule("trail", "LINE", 0.91, "trail", re.compile(r"\b(?:sentiero|mulattiera|traccia|cai\s*\d+)\b")),
        _Rule("road", "LINE", 0.88, "road", re.compile(r"\b(?:strada|via|carrareccia|statale|provinciale)\b")),
        _Rule("refuge", "POINT", 0.92, "refuge", re.compile(r"\b(?:rifugio|bivacco|malga|baita)\b")),
        _Rule("church", "POINT", 0.91, "church", re.compile(r"\b(?:chiesa|santuario|cappella|oratorio)\b")),
        _Rule("ridge", "LINE", 0.90, "ridge", re.compile(r"\b(?:cresta|crinale)\b")),
        _Rule("meadow", "POLYGON", 0.84, "meadow", re.compile(r"\b(?:prato|piana|pianoro|alpeggio|alpe)\b")),
    )

    RELATIONS = (
        ("between", re.compile(r"\b(?:tra|fra)\b")),
        ("near", re.compile(r"\b(?:presso|vicino\s+a|nei\s+pressi\s+di|in\s+prossimita\s+di)\b")),
        ("above", re.compile(r"\b(?:sopra|a\s+monte\s+di)\b")),
        ("below", re.compile(r"\b(?:sotto|a\s+valle\s+di)\b")),
        ("along", re.compile(r"\b(?:lungo|sul|sulla)\b")),
    )

    @staticmethod
    def normalize(text: str | None) -> str:
        value = str(text or "").strip().replace("’", "'").replace("`", "'")
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = re.sub(r"\s+", " ", value.lower()).strip(" ,;.-")
        return value

    def parse(self, locality_text: str | None, municipality: str | None = None) -> LocalityInterpretation:
        original = str(locality_text or "")
        normalized = self.normalize(original)
        municipality_norm = self.normalize(municipality)
        warnings: list[str] = []

        if not normalized:
            if municipality_norm:
                return LocalityInterpretation(original, municipality_norm, "municipality", "ADMIN", 0.88, "municipality_fallback", warnings=("Località vuota: usato il comune",))
            return LocalityInterpretation(original, normalized, "unknown", "UNKNOWN", 0.0, "empty", warnings=("Località vuota",))

        # Explicitly handle locality == municipality before generic rules.
        if municipality_norm and normalized == municipality_norm:
            return LocalityInterpretation(original, normalized, "municipality", "ADMIN", 0.99, "locality_equals_municipality", attributes={"municipality": municipality_norm})

        relation = next((name for name, pattern in self.RELATIONS if pattern.search(normalized)), None)
        for rule in self.RULES:
            match = rule.pattern.search(normalized)
            if match:
                return LocalityInterpretation(
                    original_text=original,
                    normalized_text=normalized,
                    feature_type=rule.feature_type,
                    expected_geometry=rule.expected_geometry,
                    confidence=rule.confidence,
                    matched_rule=rule.name,
                    relation=relation,
                    attributes={"match": match.group(0)},
                )

        warnings.append("Toponimo generico: tipo geografico non esplicito")
        return LocalityInterpretation(original, normalized, "generic_locality", "UNKNOWN", 0.55, "generic_fallback", relation=relation, warnings=tuple(warnings))
