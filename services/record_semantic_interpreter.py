import re

from .substrate_resolution_service import SubstrateResolutionService


class RecordSemanticInterpreter:
    """Interpreta semanticamente le informazioni esplicite del cartellino.

    Principio:
    - il cartellino è fonte primaria;
    - i campi espliciti diventano LOCK;
    - ITALIC può arricchire, ma non sovrascrivere i LOCK.
    """

    EPIPHYTE_TERMS = [
        "scorza", "corteccia", "bark", "trunk", "tronco", "ramo", "branch",
        "legno", "wood", "lign", "epif", "epiph", "forofita", "phorophyte",
        "forophyte"
    ]

    ROCK_TERMS = [
        "roccia", "rocc", "rock", "sasso", "masso", "pietra", "parete",
        "rup", "sax", "silice", "siliceo", "silicea", "calcare", "calcareo",
        "calcarea", "dolomia", "dolomit"
    ]

    SOIL_TERMS = [
        "suolo", "soil", "terra", "terric", "humus", "torba", "sabbia",
        "argilla", "ghiaia"
    ]

    MOSS_TERMS = [
        "muschio", "muschi", "musc", "bryophy", "bryophyte", "bryophytes",
        "moss"
    ]

    SILICEOUS_TERMS = [
        "silice", "siliceo", "silicea", "granito", "graniti", "gneiss",
        "quarz", "micasc", "fillad", "porfid", "arenaria", "scisto",
        "scisti", "metamorfic"
    ]

    CALCAREOUS_TERMS = [
        "calcare", "calcari", "calcareo", "calcarea", "dolomia", "dolomie",
        "dolomit", "carbonat", "marmo", "marna"
    ]

    TREE_GROUPS = {
        "acer": "latifoglia",
        "fagus": "latifoglia",
        "quercus": "latifoglia",
        "fraxinus": "latifoglia",
        "betula": "latifoglia",
        "castanea": "latifoglia",
        "alnus": "ripariale",
        "populus": "ripariale",
        "salix": "ripariale",
        "picea": "conifera",
        "abies": "conifera",
        "larix": "conifera",
        "pinus": "conifera",
        "juniperus": "conifera",
    }

    def __init__(self):
        self.substrate_resolver = SubstrateResolutionService()

    def _txt(self, value):
        if value in [None, "", [], {}]:
            return ""
        try:
            return str(value).strip().lower()
        except Exception:
            return ""

    def _has_any(self, text, terms):
        text = self._txt(text)
        return any(t in text for t in terms)

    def substrate_from_text(self, value, forophyte_value=None):
        """Compatibilità legacy: risolve prima il solo campo Substrato.

        Il forofita viene usato esclusivamente quando il campo Substrato è vuoto.
        """
        result = self.substrate_resolver.resolve(
            substrate=value,
            forophyte=forophyte_value if not self._txt(value) else None,
        )
        return {
            "soil": "suolo",
            "rock": "roccia",
            "epiphyte": "epifita",
            "lignicolous": "lignicolo",
            "moss": "muschio",
        }.get(result.group)

    def rock_from_text(self, value):
        text = self._txt(value)
        if not text:
            return None
        sil = self._has_any(text, self.SILICEOUS_TERMS)
        cal = self._has_any(text, self.CALCAREOUS_TERMS)
        if sil and cal:
            return "misto"
        if sil:
            return "siliceo"
        if cal:
            return "calcareo"
        return None

    def tree_from_text(self, value):
        text = self._txt(value)
        if not text:
            return {}
        out = {
            "tree_raw": str(value).strip(),
            "tree_type": "",
            "tree_group": "",
        }
        for genus, group in self.TREE_GROUPS.items():
            if genus in text:
                out["tree_type"] = genus
                out["tree_group"] = group
                break
        if not out["tree_group"]:
            if any(k in text for k in ["latifog", "broadleaf"]):
                out["tree_group"] = "latifoglia"
            elif any(k in text for k in ["conifer", "aghifog", "conif"]):
                out["tree_group"] = "conifera"
        return out

    def aspect_from_text(self, value):
        text = self._txt(value)
        if not text:
            return None
        t = text.replace("–", "-").replace("—", "-").replace("/", "-")
        t = re.sub(r"\s+", "", t.upper())
        t = t.replace("O", "W")  # ovest
        # gestisce combinazioni come E-NE, NNE, ENE, SO, OSO, ecc.
        valid = [
            "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
        ]
        if t in valid:
            return t
        low = text
        replacements = {
            "nord": "N", "settentrionale": "N",
            "sud": "S", "meridionale": "S",
            "est": "E", "orientale": "E",
            "ovest": "W", "occidentale": "W",
        }
        # prima combinazioni testuali
        if ("nord" in low or "settentrionale" in low) and ("est" in low or "orientale" in low):
            return "NE"
        if ("sud" in low or "meridionale" in low) and ("est" in low or "orientale" in low):
            return "SE"
        if ("sud" in low or "meridionale" in low) and ("ovest" in low or "occidentale" in low):
            return "SW"
        if ("nord" in low or "settentrionale" in low) and ("ovest" in low or "occidentale" in low):
            return "NW"
        for k, v in replacements.items():
            if k in low:
                return v
        return None

    def interpret(self, constraints):
        constraints = constraints or {}
        substrate_raw = constraints.get("substrate_raw") or constraints.get("substrate")
        tree_raw = constraints.get("tree_raw") or constraints.get("tree_type")
        rock_raw = constraints.get("rock_raw") or constraints.get("rock_type")
        aspect_raw = constraints.get("aspect_raw") or constraints.get("aspect")

        out = {
            "record_locks": {},
            "record_sources": {},
            "semantic_details": [],
        }

        # Risoluzione centralizzata: il campo Substrato esplicito ha priorità
        # assoluta. Il forofita entra solo se Substrato è assente.
        resolution = self.substrate_resolver.resolve(
            substrate=substrate_raw,
            forophyte=tree_raw,
            rock=rock_raw,
            soil=constraints.get("soil_raw") or constraints.get("soil_type"),
            notes=constraints.get("ecological_notes") or constraints.get("notes"),
        )
        out.update(resolution.to_dict())
        legacy_substrate = {
            "soil": "suolo", "rock": "roccia", "epiphyte": "epifita",
            "lignicolous": "lignicolo", "moss": "muschio",
        }.get(resolution.group)
        if legacy_substrate:
            out["substrate"] = legacy_substrate
        if resolution.locked:
            out["record_locks"]["substrate"] = True
        out["record_sources"]["substrate"] = resolution.source
        out["semantic_details"].append(
            f"substrato risolto={resolution.group}; fonte={resolution.source}; "
            f"locked={resolution.locked}; confidenza={resolution.confidence:.2f}"
        )

        # Il forofita resta un attributo separato. Non può sovrascrivere un
        # substrato esplicito già risolto dal cartellino.
        tree_info = self.tree_from_text(tree_raw)
        if tree_info:
            out.update({k: v for k, v in tree_info.items() if v})
            out["record_locks"]["tree_type"] = True
            out["record_sources"]["tree_type"] = "cartellino"
            if tree_info.get("tree_group"):
                out["record_locks"]["tree_group"] = True
                out["record_sources"]["tree_group"] = "cartellino"

        rock = self.rock_from_text(rock_raw)
        if rock:
            out["rock_type"] = rock
            out["record_locks"]["rock_type"] = True
            out["record_sources"]["rock_type"] = "cartellino"
            out["semantic_details"].append(f"roccia cartellino interpretata come {rock}")

        aspect = self.aspect_from_text(aspect_raw)
        if aspect:
            out["record_aspect"] = aspect
            out["record_locks"]["aspect"] = True
            out["record_sources"]["aspect"] = "cartellino"
            out["semantic_details"].append(f"esposizione cartellino interpretata come {aspect}")

        return out

    def merge_record_and_italic(self, record_profile, italic_profile):
        """Unisce cartellino e ITALIC senza sovrascrivere i lock del record."""
        record_profile = record_profile or {}
        italic_profile = italic_profile or {}

        merged = dict(italic_profile)
        locks = dict(record_profile.get("record_locks") or {})

        # I campi locked del cartellino vincono sempre.
        for key, value in record_profile.items():
            if key in ["record_locks", "record_sources", "semantic_details"]:
                continue
            if locks.get(key) or value not in [None, "", [], {}]:
                merged[key] = value

        merged["record_locks"] = locks
        merged["record_sources"] = record_profile.get("record_sources") or {}
        merged["semantic_details"] = record_profile.get("semantic_details") or []

        # ITALIC resta prezioso: manteniamo tutti i dati grezzi e normalizzati.
        merged["italic_profile"] = italic_profile
        merged["italic_enrichment_used"] = True

        # Se il cartellino non ha risolto il substrato, usa ITALIC come fallback.
        # Un risultato locked non viene mai sovrascritto.
        if not merged.get("substrate_locked") and merged.get("substrate_group") in (None, "", "unknown"):
            fallback = self.substrate_resolver.resolve(italic_profile=italic_profile)
            merged.update(fallback.to_dict())
            legacy = {"soil": "suolo", "rock": "roccia", "epiphyte": "epifita", "lignicolous": "lignicolo", "moss": "muschio"}.get(fallback.group)
            if legacy:
                merged["substrate"] = legacy

        return merged
