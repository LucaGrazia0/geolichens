from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SubstrateResolutionResult:
    """Esito unico e propagabile della risoluzione del substrato del record."""

    group: str = "unknown"
    raw: str = ""
    source: str = "unknown"
    locked: bool = False
    confidence: float = 0.0
    reason: str = "Nessuna evidenza sufficiente"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["substrate_group"] = data.pop("group")
        data["substrate_raw"] = data.pop("raw")
        data["substrate_source"] = data.pop("source")
        data["substrate_locked"] = data.pop("locked")
        data["substrate_confidence"] = data.pop("confidence")
        data["substrate_resolution_reason"] = data.pop("reason")
        return data


class SubstrateResolutionService:
    """Risoluzione centralizzata del substrato.

    Gerarchia:
    1. campo Substrato esplicito;
    2. campi specialistici (forofita, roccia, suolo);
    3. note ecologiche, solo se univoche;
    4. profilo ITALIC;
    5. unknown.

    Un valore esplicito del cartellino viene bloccato e non può essere
    sovrascritto dal profilo ecologico generale del taxon.
    """

    LIGNICOLOUS = (
        "legno morto", "legno marcescente", "legno decomposto", "legno in decomposizione",
        "tronco morto", "ramo morto", "ceppaia", "ceppo", "dead wood", "deadwood",
        "decaying wood", "rotting wood", "fallen trunk", "stump", "lignicol",
    )
    EPIPHYTE = (
        "scorza", "corteccia", "bark", "epifit", "epiphyt", "tronco vivo",
        "ramo vivo", "forofita", "phorophyte", "forophyte",
    )
    ROCK = (
        "roccia", "sassicol", "saxicol", "rupicol", "rupestre", "masso", "pietra",
        "parete rocciosa", "rock", "stone", "cliff",
    )
    SOIL = (
        "suolo", "terricol", "terra", "terreno", "soil", "ground", "humus", "torba",
        "peat", "sabbia", "argilla", "ghiaia", "detrito", "morena",
    )
    MOSS = ("muschio", "muschi", "muscicol", "moss", "bryophyte", "bryophytes")

    def resolve(
        self,
        substrate: Any = None,
        forophyte: Any = None,
        rock: Any = None,
        soil: Any = None,
        notes: Any = None,
        italic_profile: Optional[Dict[str, Any]] = None,
    ) -> SubstrateResolutionResult:
        raw_substrate = self._text(substrate)
        if raw_substrate:
            group = self._classify(raw_substrate)
            if group:
                return SubstrateResolutionResult(
                    group=group,
                    raw=str(substrate).strip(),
                    source="specimen_label_substrate",
                    locked=True,
                    confidence=1.0,
                    reason="Campo Substrato esplicito del cartellino",
                )
            return SubstrateResolutionResult(
                group="unknown",
                raw=str(substrate).strip(),
                source="specimen_label_substrate",
                locked=True,
                confidence=0.55,
                reason="Campo Substrato esplicito ma non classificabile; scelta mantenuta come unknown",
            )

        if self._text(forophyte):
            return SubstrateResolutionResult(
                group="epiphyte", raw=str(forophyte).strip(), source="specimen_label_forophyte",
                locked=True, confidence=0.98, reason="Forofita esplicita con campo Substrato assente",
            )
        if self._text(rock):
            return SubstrateResolutionResult(
                group="rock", raw=str(rock).strip(), source="specimen_label_rock",
                locked=True, confidence=0.95, reason="Roccia esplicita con campo Substrato assente",
            )
        if self._text(soil):
            return SubstrateResolutionResult(
                group="soil", raw=str(soil).strip(), source="specimen_label_soil",
                locked=True, confidence=0.95, reason="Suolo terricolo esplicito con campo Substrato assente",
            )

        note_text = self._text(notes)
        note_group = self._classify_unambiguous(note_text)
        if note_group:
            return SubstrateResolutionResult(
                group=note_group, raw=str(notes).strip(), source="ecological_notes",
                locked=False, confidence=0.65, reason="Indicazione univoca nelle note ecologiche",
            )

        italic_group, italic_raw = self._from_italic(italic_profile or {})
        if italic_group:
            return SubstrateResolutionResult(
                group=italic_group, raw=italic_raw, source="ITALIC",
                locked=False, confidence=0.50, reason="Fallback dal profilo ecologico del taxon",
            )
        return SubstrateResolutionResult()

    def _from_italic(self, profile: Dict[str, Any]):
        candidates = []
        for key in ("substrate", "substrate_raw", "raw_substrata", "ecology_traits", "ecology_source_note"):
            value = profile.get(key)
            if value not in (None, "", [], {}):
                candidates.append(str(value))
        for value in profile.get("substrata") or []:
            candidates.append(str(value))
        text = " | ".join(candidates)
        return self._classify_unambiguous(self._text(text)), text

    def _classify_unambiguous(self, text: str):
        matches = []
        for group, terms in (
            ("lignicolous", self.LIGNICOLOUS), ("epiphyte", self.EPIPHYTE),
            ("rock", self.ROCK), ("soil", self.SOIL), ("moss", self.MOSS),
        ):
            if any(term in text for term in terms):
                matches.append(group)
        return matches[0] if len(matches) == 1 else None

    def _classify(self, text: str):
        # Ordine intenzionale: legno morto prima di scorza/legno generico.
        for group, terms in (
            ("lignicolous", self.LIGNICOLOUS), ("epiphyte", self.EPIPHYTE),
            ("rock", self.ROCK), ("soil", self.SOIL), ("moss", self.MOSS),
        ):
            if any(term in text for term in terms):
                return group
        return None

    @staticmethod
    def _text(value: Any) -> str:
        if value in (None, "", [], {}):
            return ""
        return str(value).strip().lower()
