import re


class ContextEngine:
    """Context-aware locality model for GeoLichen.

    Distingue il tipo di località indicata nel cartellino e decide quale
    riferimento spaziale deve pesare di più nel ranking.

    Esempi:
    - "Passo Gallinera" -> pass: priorità alla distanza dal centro del passo
    - "Lago Nero" -> hydro/lake: priorità alla distanza dal lago
    - "Sentiero 525" -> trail: priorità alla distanza dai sentieri
    - "Corno Gallinera" -> summit: priorità alla cima
    """

    TYPE_WEIGHTS = {
        "pass": 0.40,
        "summit": 0.35,
        "refuge_malga": 0.35,
        "hydro": 0.30,
        "lake": 0.30,
        "trail": 0.30,
        "valley": 0.20,
        "meadow": 0.20,
        "nearby_place": 0.20,
        "generic_toponym": 0.18,
        "locality": 0.15,
        "municipality": 0.05,
    }

    POINT_LIKE_TYPES = {"pass", "summit", "refuge_malga", "meadow", "nearby_place", "generic_toponym", "locality"}
    AREA_LIKE_TYPES = {"hydro", "lake", "valley", "municipality"}
    TRAIL_LIKE_TYPES = {"trail"}

    def infer_context(self, geocoding_result=None, locality_parse_result=None, locality_text=None):
        ref_type = None
        reference_name = None
        confidence = 0.5
        relation = None

        # 1) Preferisci il riferimento estratto dal parser con confidenza massima.
        refs = getattr(locality_parse_result, "references", None) or []
        if refs:
            try:
                best = sorted(refs, key=lambda r: float(getattr(r, "confidence", 0.0) or 0.0), reverse=True)[0]
                ref_type = getattr(best, "ref_type", None)
                reference_name = getattr(best, "normalized_name", None) or getattr(best, "raw_text", None)
                relation = getattr(best, "relation", None)
                confidence = float(getattr(best, "confidence", 0.8) or 0.8)
            except Exception:
                pass

        # 2) Se manca, usa matched_source/geocoder.
        if not ref_type and geocoding_result is not None:
            ref_type = getattr(geocoding_result, "matched_source", None)
            try:
                feature = getattr(geocoding_result, "feature", None) or {}
                reference_name = feature.get("place_name") or feature.get("text")
            except Exception:
                pass
            confidence = 0.65

        # 3) Fallback lessicale dal testo.
        if not ref_type:
            ref_type = self.infer_type_from_text(locality_text or reference_name or "")
            reference_name = reference_name or locality_text
            confidence = 0.55 if ref_type else 0.3

        ref_type = self.normalize_type(ref_type)
        return {
            "type": ref_type or "locality",
            "reference_name": reference_name or "",
            "relation": relation or "",
            "confidence": confidence,
            "weight": self.TYPE_WEIGHTS.get(ref_type or "locality", 0.15),
            "is_point_like": (ref_type in self.POINT_LIKE_TYPES),
            "is_area_like": (ref_type in self.AREA_LIKE_TYPES),
            "is_trail_like": (ref_type in self.TRAIL_LIKE_TYPES),
        }

    def normalize_type(self, value):
        v = str(value or "").lower().strip()
        if not v:
            return None
        if v in {"passo", "forcella", "sella", "bocchetta"}:
            return "pass"
        if v in {"monte", "cima", "vetta", "corno", "pizzo", "punta", "colle"}:
            return "summit"
        if v in {"rifugio", "malga", "bivacco", "baita"}:
            return "refuge_malga"
        if v in {"lago", "torrente", "rio", "fiume", "hydro"}:
            return "hydro"
        if v in {"sentiero", "cai", "trail", "path"}:
            return "trail"
        if v in {"val", "valle"}:
            return "valley"
        return v

    def infer_type_from_text(self, text):
        t = str(text or "").lower()
        patterns = [
            ("pass", r"\b(passo|forcella|sella|bocchetta)\b"),
            ("summit", r"\b(monte|cima|vetta|corno|pizzo|punta|colle)\b"),
            ("refuge_malga", r"\b(rifugio|malga|bivacco|baita)\b"),
            ("hydro", r"\b(lago|torrente|rio|fiume)\b"),
            ("trail", r"\b(sentiero|cai)\s*[0-9a-z]*\b"),
            ("valley", r"\b(valle|val\s+)"),
            ("meadow", r"\b(prato|piana|pianoro|alpe|alpeggio)\b"),
        ]
        for typ, pat in patterns:
            if re.search(pat, t):
                return typ
        return "locality"
