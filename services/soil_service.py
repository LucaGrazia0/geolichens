from .knowledge_base import GeoLichenKnowledgeBase
from ._shared_geo_utils import to_float as _shared_to_float
import re

class SoilService:
    def __init__(self):
        self.kb = GeoLichenKnowledgeBase()


    SOIL_TRAITS = {
        "torboso": {"ph": "acid", "humidity": "high", "organic": "high"},
        "acido": {"ph": "acid", "humidity": "medium", "organic": "medium"},
        "basico": {"ph": "basic", "humidity": "medium", "organic": "medium"},
        "roccioso": {"ph": "variable", "humidity": "low", "organic": "low"},
        "organico": {"ph": "acid", "humidity": "high", "organic": "high"},
    }

    """Traduce ecologia ITALIC in vincoli GIS per suolo/substrato e roccia."""

    def infer_constraints(self, profile):
        profile = profile or {}
        substrate = self.infer_soil_constraint(profile)
        rock_type = self.infer_rock_type(profile)
        habitats = self.classify_habitat(profile)
        ph_preference = self.infer_ph_preference(profile)
        out = {
            "substrate": substrate,
            "rock_type": rock_type,
            "soil_ph_preference": ph_preference,
            "fallback_substrata": [],
            "fallback_habitat": habitats,
            "habitat_classes": habitats,
        }
        if substrate:
            out["fallback_substrata"].append(substrate)
        for s in (profile.get("substrata") or []):
            ns = self._normalize_substrate(s)
            if ns and ns not in out["fallback_substrata"]:
                out["fallback_substrata"].append(ns)
        return out

    def infer_soil_constraint(self, profile):
        substrata = profile.get("substrata") or []
        raw = " ".join(str(x) for x in substrata) + " " + self._profile_text(profile)
        return self._normalize_substrate(raw)

    def infer_rock_type(self, profile):
        if profile.get("rock_type"):
            return self._normalize_rock(profile.get("rock_type"))
        ecology = profile.get("ecology_raw") or {}
        ph_min = self._to_float(self._value(ecology, "ph_of_the_substrata_min"))
        ph_max = self._to_float(self._value(ecology, "ph_of_the_substrata_max"))
        if ph_min is not None or ph_max is not None:
            lo = ph_min if ph_min is not None else ph_max
            hi = ph_max if ph_max is not None else ph_min
            if hi is not None and hi <= 2:
                return "siliceo"
            if lo is not None and lo >= 4:
                return "calcareo"
            if lo is not None and hi is not None and lo <= 2 and hi >= 4:
                return "misto"
        return self._normalize_rock(self._profile_text(profile))

    def infer_ph_preference(self, profile):
        """Inferisce preferenza pH per taxa terricoli/muscicoli o substrati generali."""
        profile = profile or {}
        ecology = profile.get("ecology_raw") or {}
        ph_min = self._to_float(self._value(ecology, "ph_of_the_substrata_min"))
        ph_max = self._to_float(self._value(ecology, "ph_of_the_substrata_max"))
        if ph_min is not None or ph_max is not None:
            lo = ph_min if ph_min is not None else ph_max
            hi = ph_max if ph_max is not None else ph_min
            if hi is not None and hi <= 2:
                return "acid"
            if lo is not None and lo >= 4:
                return "basic"
            if lo is not None and hi is not None and lo <= 2 and hi >= 4:
                return "broad"
        text = self._profile_text(profile).lower()
        acid = any(k in text for k in ["acid", "acidoph", "silic", "silice", "torb", "peat"])
        basic = any(k in text for k in ["basic", "basiph", "base-rich", "calcare", "calcicol", "limestone", "dolomit"])
        if acid and basic:
            return "broad"
        if acid:
            return "acid"
        if basic:
            return "basic"
        return None

    def classify_habitat(self, profile):
        text = self._profile_text(profile).lower()
        ecology = profile.get("ecology_raw") or {}
        classes = []
        alt_max = self._to_float(self._value(ecology, "altitudinal_distribution_max"))
        if (alt_max is not None and alt_max >= 1800) or any(k in text for k in ["alpine", "nival", "subalpine", "treeline", "above timberline"]):
            classes.append("alpino")
        if any(k in text for k in ["rock", "rocks", "saxicol", "rupicol", "cliff", "stone", "siliceous", "calcareous"]):
            classes.append("rupicolo")
        if any(k in text for k in ["forest", "wood", "woodland", "bark", "tree", "epiph"]):
            classes.append("forestale")
        if any(k in text for k in ["open habitats", "open situations", "grassland", "meadow", "aperto", "prato"]):
            classes.append("aperto")
        if any(k in text for k in ["humid", "wet", "moist", "water", "umid"]):
            classes.append("umido")
        if any(k in text for k in ["dry", "xeric", "arid", "secco"]):
            classes.append("xerico")
        eut_max = self._to_float(self._value(ecology, "eutrophication_max"))
        if (eut_max is not None and eut_max >= 4) or "nitroph" in text:
            classes.append("nitrofilo")
        rock = self.infer_rock_type(profile)
        if rock and rock not in classes:
            classes.append(rock)
        return list(dict.fromkeys(classes))



    def extract_numeric_ph_from_feature(self, feature):
        """Estrae un pH numerico da una feature di un layer suolo.

        È generale: cerca prima campi noti dalla knowledge base, poi qualunque
        campo che contenga 'ph' o 'reazione/reaction' nel nome.
        """
        if feature is None:
            return None, "", ""

        try:
            names = list(feature.fields().names())
        except Exception:
            return None, "", ""

        kb = self.kb.soil_ph()
        preferred = [str(x).lower() for x in (kb.get("numeric_fields") or [])]

        candidates = []
        for n in names:
            ln = str(n).lower()
            if ln in preferred:
                candidates.insert(0, n)
            elif "ph" in ln or "reazione" in ln or "reaction" in ln:
                candidates.append(n)

        for name in candidates:
            try:
                value = feature[name]
            except Exception:
                continue
            ph = self.parse_numeric_ph(value)
            if ph is not None:
                return ph, str(name), str(value)

        return None, "", ""

    def parse_numeric_ph(self, value):
        if value in [None, ""]:
            return None
        if isinstance(value, (int, float)):
            try:
                ph = float(value)
                return ph if 0.0 <= ph <= 14.5 else None
            except Exception:
                return None
        txt = str(value).strip().replace(",", ".")
        m = re.search(r"(?<!\d)(\d{1,2}(?:\.\d+)?)(?!\d)", txt)
        if not m:
            return None
        try:
            ph = float(m.group(1))
            return ph if 0.0 <= ph <= 14.5 else None
        except Exception:
            return None

    def ph_class_from_numeric(self, ph):
        try:
            ph = float(ph)
        except Exception:
            return None
        if ph < 5.5:
            return "acid"
        if ph <= 7.2:
            return "neutral"
        return "basic"

    def numeric_ph_compatibility(self, ph, expected_ph):
        """Confronta pH numerico del layer con preferenza attesa.

        Ritorna score piccolo compatibile con la scala attuale del plugin.
        """
        ph_class = self.ph_class_from_numeric(ph)
        expected = str(expected_ph or "").lower().strip()
        if not expected or expected == "none":
            return ph_class, 0.0, "pH numerico letto; nessuna preferenza pH disponibile"

        if expected == "broad":
            return ph_class, 2.0, f"pH numerico {ph:g} ({ph_class}); taxon a preferenza ampia"

        ranges = {
            "acid": (3.5, 5.8),
            "neutral": (5.6, 7.2),
            "basic": (7.0, 8.6),
        }
        lo, hi = ranges.get(expected, (None, None))
        if lo is None:
            return ph_class, 0.0, f"pH numerico {ph:g}; preferenza {expected} non interpretabile"

        center = (lo + hi) / 2.0
        half = (hi - lo) / 2.0
        d = abs(float(ph) - center)

        if lo <= float(ph) <= hi:
            score = 6.0
            reason = f"pH numerico {ph:g} ({ph_class}) dentro range preferito {expected} [{lo}-{hi}]"
        elif d <= half + 0.7:
            score = 2.0
            reason = f"pH numerico {ph:g} ({ph_class}) vicino al range preferito {expected} [{lo}-{hi}]"
        else:
            score = -4.0
            reason = f"pH numerico {ph:g} ({ph_class}) lontano dal range preferito {expected} [{lo}-{hi}]"

        return ph_class, score, reason


    def normalize_soil_ph(self, value):
        """Normalizza valori del layer suolo in classi pH."""
        txt = str(value or "").strip().lower()
        if not txt:
            return None
        if any(k in txt for k in ["subac", "acid", "acida", "acido", "acidico", "silic", "silice", "torb", "peat"]):
            return "acid"
        if any(k in txt for k in ["subbas", "basic", "basica", "basico", "alcal", "calc", "calcare", "carbonat", "dolom"]):
            return "basic"
        if any(k in txt for k in ["neutr", "subneutral"]):
            return "neutral"
        if any(k in txt for k in ["misto", "variabile", "broad"]):
            return "broad"
        return None

    def lithology_to_soil_ph(self, lithology_group):
        """Stima pH potenziale del suolo dalla roccia madre."""
        v = str(lithology_group or "").strip().lower()
        if not v:
            return None
        if any(k in v for k in ["silice", "silic", "gran", "gneiss", "quarz", "arenaria"]):
            return "acid"
        if any(k in v for k in ["calc", "carbon", "dolom", "calcare"]):
            return "basic"
        if any(k in v for k in ["misto", "mixed", "altern", "compless"]):
            return "broad"
        return None

    def soil_confidence_from_ph_and_lithology(self, soil_ph, lithology_group):
        """Valuta l'affidabilità del pH del suolo rispetto alla litologia.

        Applicazione prudente: non esclude punti, restituisce solo un piccolo
        bonus/malus e una diagnostica leggibile.
        """
        soil_ph = str(soil_ph or "").strip().lower()
        litho_ph = self.lithology_to_soil_ph(lithology_group)

        if not soil_ph and not litho_ph:
            return "unknown", 0.0, litho_ph, "pH suolo e litologia non disponibili"
        if soil_ph and not litho_ph:
            return "medium", 0.0, litho_ph, "pH suolo disponibile, litologia non interpretabile"
        if litho_ph and not soil_ph:
            return "medium", 0.0, litho_ph, "pH stimato solo da litologia"

        if soil_ph == "broad" or litho_ph == "broad":
            return "medium", 0.0, litho_ph, "litologia o pH a risposta ampia/variabile"

        if soil_ph == litho_ph:
            return "high", 5.0, litho_ph, "pH del suolo coerente con la litologia"

        return "low", -3.0, litho_ph, "pH del suolo non coerente con la litologia"

    def _normalize_substrate(self, value):
        v = str(value or "").lower()
        if any(k in v for k in ["legno morto", "legno marcescente", "legno decomposto", "tronco morto", "ramo morto", "ceppaia", "ceppo", "dead wood", "deadwood", "stump", "lignicol"]):
            return "lignicolo"
        if any(k in v for k in ["epif", "bark", "cortecc", "scorza", "tree", "forophy", "phorophy", "tronco vivo", "ramo vivo"]):
            return "epifita"
        if any(k in v for k in ["sax", "rock", "rocks", "rocc", "stone", "wall", "muro", "cliff", "rupicol"]):
            return "saxicolo"
        if any(k in v for k in ["soil", "ground", "earth", "terr", "suolo"]):
            return "terricolo"
        if any(k in v for k in ["lign", "wood", "dead wood", "legno"]):
            return "lignicolo"
        if any(k in v for k in ["moss", "mosses", "muschi", "bryophy"]):
            return "muscicolo"
        return None

    def _normalize_rock(self, value):
        v = str(value or "").lower()
        if not v:
            return None
        calc = any(k in v for k in ["calcare", "calcicol", "calcareous", "limestone", "dolomit", "carbonat", "base-rich", "basic substrata"])
        sil = any(k in v for k in ["silice", "silicicol", "siliceous", "acid substrata", "acid rocks", "quartz", "granite", "gneiss"])
        if calc and sil:
            return "misto"
        if calc:
            return "calcareo"
        if sil:
            return "siliceo"
        if any(k in v for k in ["misto", "mixed", "wide range", "various substrata"]):
            return "misto"
        return None

    def _profile_text(self, profile):
        parts = [
            profile.get("ecology_traits"),
            profile.get("notes"),
            profile.get("raw_substrata"),
            profile.get("regions_distribution"),
            profile.get("ecoregions_distribution"),
            profile.get("ecology_source_note"),
            " ".join(profile.get("habitat") or []),
        ]
        raw = profile.get("ecology_raw") or {}
        if isinstance(raw, dict):
            parts.extend(str(v) for v in raw.values() if v not in [None, "", [], {}])
        return " ".join(str(p) for p in parts if p not in [None, "", [], {}])

    def _value(self, data, key):
        if not isinstance(data, dict):
            return None
        if key in data:
            return data.get(key)
        kn = key.lower().replace("_", "").replace("-", "")
        for k, v in data.items():
            if str(k).lower().replace("_", "").replace("-", "") == kn:
                return v
        return None

    def _to_float(self, value):
        return _shared_to_float(value)


    def infer_soil_traits(self, profile):
        """Converte il suolo in traits ecologici."""
        substrate = self.infer_soil_constraint(profile)
        if not substrate:
            return {}

        text = str(substrate).lower()

        if "torb" in text:
            return dict(self.SOIL_TRAITS["torboso"])

        if any(k in text for k in ["acid", "acido", "silic", "silice"]):
            return dict(self.SOIL_TRAITS["acido"])

        if any(k in text for k in ["calc", "calcare", "basic", "basico"]):
            return dict(self.SOIL_TRAITS["basico"])

        if any(k in text for k in ["rock", "rocc"]):
            return dict(self.SOIL_TRAITS["roccioso"])

        if any(k in text for k in ["organic", "umus"]):
            return dict(self.SOIL_TRAITS["organico"])

        return {}
