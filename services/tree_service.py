from .forest_type_service import ForestTypeService


class TreeService:
    """Collega cartellino, ITALIC e Carta Forestale.

    Priorità:
    1. Forofita indicato nel cartellino.
    2. Preferenze ricavate da ITALIC/note.
    3. Valore del layer forestale, es. TIP_RL.
    """

    TREE_TRAITS = {
        "picea": {"bark_ph": "acid", "humidity": "high", "forest_type": "conifer", "texture": "rough"},
        "abies": {"bark_ph": "acid", "humidity": "high", "forest_type": "conifer", "texture": "rough"},
        "larix": {"bark_ph": "acid", "humidity": "medium", "forest_type": "open_conifer", "texture": "rough"},
        "pinus": {"bark_ph": "acid", "humidity": "low", "forest_type": "conifer", "texture": "rough"},
        "fagus": {"bark_ph": "subneutral", "humidity": "medium", "forest_type": "broadleaf", "texture": "smooth"},
        "quercus": {"bark_ph": "subneutral", "humidity": "medium", "forest_type": "broadleaf", "texture": "rough"},
        "betula": {"bark_ph": "acid", "humidity": "medium", "forest_type": "broadleaf", "texture": "smooth"},
        "alnus": {"bark_ph": "basic", "humidity": "high", "forest_type": "riparian", "texture": "rough"},
        "fraxinus": {"bark_ph": "subneutral", "humidity": "medium", "forest_type": "broadleaf", "texture": "rough"},
        "acer": {"bark_ph": "subneutral", "humidity": "medium", "forest_type": "broadleaf", "texture": "smooth"},
        "castanea": {"bark_ph": "acid", "humidity": "medium", "forest_type": "broadleaf", "texture": "rough"},
        "populus": {"bark_ph": "subneutral", "humidity": "high", "forest_type": "riparian", "texture": "rough"},
        "salix": {"bark_ph": "subneutral", "humidity": "high", "forest_type": "riparian", "texture": "rough"},
    }

    def __init__(self):
        self.forest_type_service = ForestTypeService()

    def _clean(self, value):
        try:
            if value in [None, "", [], {}]:
                return ""
            return str(value).strip().lower()
        except Exception:
            return ""

    def _profile_text(self, profile):
        profile = profile or {}
        parts = [
            profile.get("ecology_traits"),
            profile.get("notes"),
            profile.get("raw_substrata"),
            " ".join(profile.get("habitat") or []),
            " ".join(profile.get("substrata") or []),
        ]
        raw = profile.get("ecology_raw") or {}
        if isinstance(raw, dict):
            parts.extend(str(v) for v in raw.values() if v not in [None, "", [], {}])
        return " ".join(str(p) for p in parts if p not in [None, "", [], {}]).lower()

    def is_epiphytic_or_lignicolous(self, profile):
        profile = profile or {}

        # Cartellino/record: se esiste un campo albero/forofita, è una forte evidenza.
        for key in [
            "tree_type", "forofita", "forophyte", "phorophyte", "host_tree",
            "forofita_record", "record_tree_raw", "albero", "Albero",
            "bark", "corteccia", "legno", "wood"
        ]:
            if profile.get(key) not in [None, "", [], {}]:
                return True

        for container_key in ["record", "raw_record", "record_constraints", "label_data", "fields", "row"]:
            container = profile.get(container_key)
            if isinstance(container, dict):
                for k, v in container.items():
                    kk = self._clean(k)
                    if any(term in kk for term in [
                        "albero", "forof", "phorophy", "forophy", "host",
                        "cortecc", "legno", "bark", "wood", "tronco", "ramo"
                    ]) and v not in [None, "", [], {}]:
                        return True

        text = self._profile_text(profile)
        return any(k in text for k in [
            "epif", "epiph", "corteccia", "bark", "forophy", "phorophy",
            "lign", "wood", "legno", "tronco", "ramo"
        ])


    def canonical_tree(self, value):
        traits = self.forest_type_service.forest_traits_from_value(value)
        if traits and traits.get("tree_type"):
            return traits.get("tree_type")
        txt = self._clean(value)
        if not txt:
            return None
        if txt in self.TREE_TRAITS:
            return txt
        if "conifer" in txt or "conifere" in txt:
            return "conifere"
        if "latifoglie" in txt or "broadleaf" in txt:
            return "latifoglie"
        if "ripar" in txt:
            return "ripariale"
        if "bosco" in txt or "forest" in txt:
            return "bosco"
        return txt

    def cartellino_tree_traits(self, profile):
        return self.forest_type_service.cartellino_traits_from_profile(profile)


    def infer_tree_type(self, profile):
        """Compatibilità con il controller esistente.

        Restituisce il tipo di forofita/albero atteso dal cartellino o da ITALIC.
        """
        try:
            traits = self.infer_tree_traits(profile)
            if traits:
                return traits.get("tree_type")
        except Exception:
            pass
        return None


    def infer_tree_traits(self, profile):
        # 1. Cartellino esplicito / interprete semantico
        if (profile or {}).get("tree_group") or (profile or {}).get("tree_type"):
            return {
                "tree_type": (profile or {}).get("tree_type") or (profile or {}).get("tree_group"),
                "forest_type": (profile or {}).get("tree_group") or (profile or {}).get("tree_type"),
                "forest_category": "record_semantic",
                "priority": "cartellino",
            }

        cart = self.cartellino_tree_traits(profile)
        if cart:
            out = dict(cart)
            out["priority"] = "cartellino"
            return out

        # 2. ITALIC/note
        text = self._profile_text(profile)
        traits = self.forest_type_service.forest_traits_from_value(text)
        if traits:
            traits["priority"] = "italic_notes"
            return traits

        # 3. Epifita generico
        if self.is_epiphytic_or_lignicolous(profile):
            return {
                "tree_type": "bosco",
                "forest_type": "forest",
                "bark_ph": None,
                "humidity": "medium",
                "texture": "mixed",
                "forest_category": "generic_epiphyte",
                "priority": "generic_epiphyte",
            }

        return {}

    def traits_from_layer_value(self, value):
        return self.forest_type_service.forest_traits_from_value(value)

    def tree_match_score(self, profile, layer_tree_value):
        profile = profile or {}

        if not self.is_epiphytic_or_lignicolous(profile):
            observed = self.traits_from_layer_value(layer_tree_value)
            return {
                "score": 0.0,
                "reason": "non applicato: taxon non epifita/lignicolo",
                "expected_traits": {},
                "observed_traits": observed or {},
                "used": False,
            }

        expected = self.infer_tree_traits(profile)
        observed = self.traits_from_layer_value(layer_tree_value)

        if not observed:
            return {
                "score": 0.0,
                "reason": "nessuna evidenza forestale nella carta; criterio non penalizzante perché possono esistere alberi isolati o microhabitat non cartografati",
                "expected_traits": expected,
                "observed_traits": {},
                "used": True,
            }

        score = 0.0
        reasons = []

        exp_tree = self.canonical_tree(expected.get("tree_type"))
        obs_tree = self.canonical_tree(observed.get("tree_type"))
        priority = expected.get("priority")

        # Se il cartellino dice esplicitamente il forofita, questa voce pesa di più.
        tree_weight = 14.0 if priority == "cartellino" else 10.0
        group_weight = 5.0 if priority == "cartellino" else 6.0

        if exp_tree and obs_tree:
            if exp_tree == obs_tree:
                score += tree_weight
                reasons.append(f"forofita del cartellino/ITALIC coerente con layer ({obs_tree}) +{tree_weight:g}")
            elif exp_tree == "bosco" or obs_tree == "bosco":
                score += 4.0
                reasons.append("bosco presente ma forofita non specifico +4")
            elif self._forest_group_match(expected.get("forest_type") or exp_tree, observed.get("forest_type")):
                score += group_weight
                reasons.append(f"gruppo forestale coerente ({observed.get('forest_type')}) +{group_weight:g}")
            else:
                penalty = 0.0
                score += penalty
                reasons.append(f"forofita del cartellino non confermata dal layer ({obs_tree}); nessuna penalità")
        else:
            score += 4.0
            reasons.append("ambiente arboreo presente +4")

        if expected.get("forest_type") and observed.get("forest_type"):
            if self._forest_group_match(expected.get("forest_type"), observed.get("forest_type")):
                score += 5.0
                reasons.append("tipo forestale coerente +5")
            else:
                score += 0.0
                reasons.append("tipo forestale non confermato; nessuna penalità")

        if expected.get("bark_ph") and observed.get("bark_ph"):
            if self._ph_match(expected.get("bark_ph"), observed.get("bark_ph")):
                score += 4.0
                reasons.append("pH corteccia coerente +4")
            elif observed.get("bark_ph") != "mixed":
                score += 0.0
                reasons.append("pH corteccia non confermato; nessuna penalità")

        if expected.get("humidity") and observed.get("humidity"):
            if self._humidity_match(expected.get("humidity"), observed.get("humidity")):
                score += 3.0
                reasons.append("umidità forestale coerente +3")
            else:
                score += 0.0
                reasons.append("umidità forestale non confermata; nessuna penalità")

        if observed.get("soil_lithology"):
            reasons.append(f"indicazione forestale/litologica: {observed.get('soil_lithology')}")

        return {
            "score": max(0.0, min(26.0, score)),
            "reason": "; ".join(reasons),
            "expected_traits": expected,
            "observed_traits": observed,
            "used": True,
        }

    def _forest_group_match(self, expected, observed):
        e = self._clean(expected)
        o = self._clean(observed)
        if e == o:
            return True
        if e in ["conifere", "conifer", "open_conifer", "shrub_conifer", "picea", "abies", "larix", "pinus"] and o in ["conifer", "open_conifer", "shrub_conifer"]:
            return True
        if e in ["latifoglie", "broadleaf", "fagus", "quercus", "acer", "fraxinus", "castanea", "betula"] and o == "broadleaf":
            return True
        if e in ["ripariale", "riparian", "alnus", "salix", "populus"] and o == "riparian":
            return True
        if e == "forest" or o in ["forest", "mixed"]:
            return True
        return False

    def _ph_match(self, expected, observed):
        e = self._clean(expected)
        o = self._clean(observed)
        if e == o:
            return True
        if e in ["subneutral", "neutral"] and o in ["subneutral", "neutral", "basic", "mixed"]:
            return True
        if e == "acid" and o in ["acid", "mixed"]:
            return True
        return False

    def _humidity_match(self, expected, observed):
        order = {"low": 1, "medium": 2, "high": 3, "bassa": 1, "media": 2, "alta": 3}
        e = order.get(self._clean(expected))
        o = order.get(self._clean(observed))
        if e is None or o is None:
            return False
        return abs(e - o) <= 1
