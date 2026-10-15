import re
from .lithology_classifier_service import LithologyClassifierService


class RecordConstraintsService:
    """Estrae e normalizza i vincoli ecologici.

    Ora separa esplicitamente:
    - vincoli del record: usati prima, insieme alla litologia/layer GIS;
    - vincoli ITALIC: usati dopo il primo overlay, come restringimento/validazione aggiuntiva.
    """

    def __init__(self):
        self.lithology_classifier = LithologyClassifierService()

    def extract_record_constraints(self, feature, mapping_model):
        def _val(field_name):
            if not field_name:
                return None
            try:
                if field_name in feature.fields().names():
                    v = feature[field_name]
                    if v not in [None, ""]:
                        return str(v).strip()
            except Exception:
                return None
            return None

        record_substrate = _val(mapping_model.substrate)
        record_rock_type = self._normalize_rock(_val(mapping_model.rock_type))
        record_tree_type = _val(mapping_model.tree_type)
        record_elevation = _val(mapping_model.elevation)

        aspect_sources = []
        for field_name in [
            getattr(mapping_model, "notes", None),
            getattr(mapping_model, "locality", None),
            getattr(mapping_model, "substrate", None),
        ]:
            v = _val(field_name)
            if v:
                aspect_sources.append(v)
        record_aspect_raw = " | ".join(aspect_sources)
        record_aspect = self._extract_aspect(record_aspect_raw)

        normalized = {
            "substrate": self._normalize_substrate(record_substrate),
            "rock_type": record_rock_type,
            "tree_type": self._normalize_text(record_tree_type),
            "elevation": record_elevation,
            "record_aspect": record_aspect,
            "record_aspect_raw": record_aspect_raw if record_aspect else None,
            "fallback_substrata": [],
            "fallback_habitat": [],
            "constraint_source": "record",
            "sources": {
                "substrate": "specimen_label" if record_substrate else None,
                "rock_type": "specimen_label" if record_rock_type else None,
                "tree_type": "specimen_label" if record_tree_type else None,
                "elevation": "specimen_label" if record_elevation else None,
                "record_aspect": "specimen_label" if record_aspect else None,
            },
        }
        normalized["constraint_metadata"] = self._build_metadata(
            normalized,
            source="specimen_label",
            affects_gbif_extent=True,
            affects_gss=True,
            explicit=True,
            raw_values={
                "substrate": record_substrate,
                "rock_type": _val(mapping_model.rock_type),
                "tree_type": record_tree_type,
                "elevation": record_elevation,
                "record_aspect": record_aspect_raw if record_aspect else None,
            },
        )
        return normalized

    def extract_italic_constraints(self, italic_profile):
        italic_profile = italic_profile or {}
        substrata = italic_profile.get("substrata", []) or []
        substrate = self._normalize_substrate(substrata[0]) if substrata else None
        rock_type = self._normalize_rock(italic_profile.get("rock_type"))
        tree_type = self._normalize_text(italic_profile.get("tree_type"))
        habitat = italic_profile.get("habitat", []) or []

        normalized = {
            "substrate": substrate,
            "substrate_raw": substrate,
            "rock_type": rock_type,
            "rock_raw": rock_type,
            "tree_type": tree_type,
            "tree_raw": tree_type,
            "elevation": None,
            "fallback_substrata": [self._normalize_substrate(x) for x in substrata if x],
            "fallback_habitat": habitat,
            "constraint_source": "italic",
            "sources": {
                "substrate": "ITALIC" if substrate or substrata else None,
                "rock_type": "ITALIC" if rock_type else None,
                "tree_type": "ITALIC" if tree_type else None,
                "elevation": None,
            },
        }
        normalized["constraint_metadata"] = self._build_metadata(
            normalized,
            source="ITALIC",
            affects_gbif_extent=False,
            affects_gss=True,
            explicit=False,
            raw_values={
                "substrate": substrata,
                "rock_type": italic_profile.get("rock_type"),
                "tree_type": italic_profile.get("tree_type"),
                "fallback_habitat": habitat,
            },
        )
        return normalized

    # Vecchia API mantenuta per compatibilità: record vince su ITALIC.
    def extract_constraints(self, feature, mapping_model, italic_profile=None):
        base = self.extract_record_constraints(feature, mapping_model)
        italic = self.extract_italic_constraints(italic_profile)
        merged = dict(base)
        for key in ["substrate", "rock_type", "tree_type", "elevation"]:
            if not merged.get(key) and italic.get(key):
                merged[key] = italic.get(key)
        merged["fallback_substrata"] = italic.get("fallback_substrata", [])
        merged["fallback_habitat"] = italic.get("fallback_habitat", [])
        merged["constraint_metadata"] = self.merge_constraint_metadata(
            base.get("constraint_metadata"), italic.get("constraint_metadata")
        )
        return merged

    def merge_constraint_metadata(self, *groups):
        """Unisce metadati dei vincoli senza alterare i valori usati dal motore."""
        merged = []
        seen = set()
        for group in groups:
            for item in group or []:
                key = (item.get("name"), item.get("source"), repr(item.get("value")))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(dict(item))
        return merged

    def add_derived_constraint(self, metadata, name, value, source,
                               affects_gbif_extent=False, affects_gss=True,
                               evidence=None):
        """Registra un vincolo derivato; non modifica scoring o geometrie."""
        if value in [None, "", [], {}]:
            return metadata or []
        result = list(metadata or [])
        result.append({
            "name": str(name),
            "value": value,
            "source": str(source),
            "evidence": evidence if evidence is not None else value,
            "explicit": False,
            "affects_gbif_extent": bool(affects_gbif_extent),
            "affects_gss": bool(affects_gss),
        })
        return self.merge_constraint_metadata(result)

    def _build_metadata(self, values, source, affects_gbif_extent,
                        affects_gss, explicit, raw_values=None):
        raw_values = raw_values or {}
        metadata = []
        for name in ["substrate", "rock_type", "tree_type", "elevation", "record_aspect", "fallback_habitat"]:
            value = values.get(name)
            if value in [None, "", [], {}]:
                continue
            metadata.append({
                "name": name,
                "value": value,
                "source": source,
                "evidence": raw_values.get(name, value),
                "explicit": bool(explicit),
                "affects_gbif_extent": bool(affects_gbif_extent),
                "affects_gss": bool(affects_gss),
            })
        return metadata


    def _extract_aspect(self, text):
        """Estrae una classe di versante dal cartellino."""
        if not text:
            return None

        t = str(text).lower()
        t = t.replace("–", "-").replace("—", "-")
        t = re.sub(r"\s+", " ", t)

        phrase_map = [
            (r"\b(nord[\s-]*est|nord[\s-]*orientale|nordest|ne)\b", "NE"),
            (r"\b(sud[\s-]*est|sud[\s-]*orientale|sudest|se)\b", "SE"),
            (r"\b(sud[\s-]*ovest|sud[\s-]*occidentale|sudovest|so|sw)\b", "SW"),
            (r"\b(nord[\s-]*ovest|nord[\s-]*occidentale|nordovest|no|nw)\b", "NW"),
            (r"\b(nord|settentrionale|n)\b", "N"),
            (r"\b(est|orientale|e)\b", "E"),
            (r"\b(sud|meridionale|s)\b", "S"),
            (r"\b(ovest|occidentale|o|w)\b", "W"),
        ]

        context_patterns = [
            r"(versante|esposizione|esposto|esposta|pendio|declivio|costone|fianco|lato)\s+(?:a|al|alla|verso|di|del|della)?\s*([a-zA-Z\- ]{1,25})",
            r"([a-zA-Z\- ]{1,25})\s+(?:versante|esposizione)",
        ]

        candidates = []
        for pat in context_patterns:
            for m in re.finditer(pat, t):
                candidates.append(m.group(0))
        candidates.append(t)

        for c in candidates:
            for pat, aspect in phrase_map:
                if re.search(pat, c):
                    return aspect
        return None


    def _normalize_rock(self, value):
        if not value:
            return None
        klass = self.lithology_classifier.classify(value)
        if klass in ("calcareo", "siliceo", "misto"):
            return klass
        v = str(value).strip().lower()
        if "calc" in v or "carbon" in v or "dolom" in v:
            return "calcareo"
        if "silic" in v or "quarz" in v or "gneiss" in v or "granit" in v:
            return "siliceo"
        if "mist" in v or "altern" in v or "compless" in v:
            return "misto"
        return v

    def _normalize_substrate(self, value):
        if not value:
            return None
        v = str(value).strip().lower()
        if any(k in v for k in ["legno morto", "legno marcescente", "legno decomposto", "tronco morto", "ramo morto", "ceppaia", "ceppo", "dead wood", "deadwood", "stump", "lignicol"]):
            return "lignicolo"
        if any(k in v for k in ["epif", "cortecc", "scorza", "tronco vivo", "ramo vivo", "bark"]):
            return "epifita"
        if any(k in v for k in ["sax", "rocc", "muro", "stone", "rock"]):
            return "saxicolo"
        if any(k in v for k in ["terr", "suolo", "soil", "ground"]):
            return "terricolo"
        if any(k in v for k in ["legno", "lign", "wood"]):
            return "lignicolo"
        return v

    def _normalize_text(self, value):
        return str(value).strip().lower() if value not in [None, ""] else None
