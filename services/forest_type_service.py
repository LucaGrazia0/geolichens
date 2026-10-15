class ForestTypeService:
    """Interpreta valori della Carta Forestale Lombardia e del cartellino.

    Questo servizio normalizza due sorgenti:
    1. Layer forestale, es. TIP_RL = "Abieteto dei substrati carbonatici"
    2. Cartellino, es. Albero/Forofita = "su Fagus", "abete", "larice"

    Restituisce sempre un profilo ecologico standard:
    tree_type, forest_type, bark_ph, humidity, texture, soil_lithology.
    """

    def _clean(self, value):
        try:
            if value in [None, "", [], {}]:
                return ""
            return str(value).strip().lower()
        except Exception:
            return ""

    def forest_traits_from_value(self, value):
        """Traduce un valore del layer forestale, preferibilmente TIP_RL."""
        return self._traits_from_text(value, source="forest_layer")

    def cartellino_traits_from_profile(self, profile):
        """Estrae forofita/albero direttamente dal cartellino/profilo record."""
        profile = profile or {}

        keys = [
            "tree_type", "forofita", "forophyte", "phorophyte",
            "albero", "Albero", "host_tree", "host", "substrate_host",
            "record_tree", "label_tree", "forofita_record", "record_forophyte",
            "bark", "corteccia", "legno", "wood",
        ]

        parts = []
        for k in keys:
            v = profile.get(k)
            if v not in [None, "", [], {}]:
                parts.append(str(v))

        # Cerca anche nei vincoli/record originali se presenti
        for container_key in ["record", "raw_record", "record_constraints", "label_data", "fields", "row"]:
            container = profile.get(container_key)
            if isinstance(container, dict):
                for k, v in container.items():
                    kk = self._clean(k)
                    if any(term in kk for term in ["albero", "forof", "phorophy", "forophy", "host", "cortecc", "legno", "bark", "wood"]):
                        if v not in [None, "", [], {}]:
                            parts.append(str(v))

        # Fallback: se ITALIC o note citano forofite, usale come preferenza debole.
        for k in ["ecology_traits", "notes", "raw_substrata"]:
            v = profile.get(k)
            if v not in [None, "", [], {}]:
                parts.append(str(v))

        raw = profile.get("ecology_raw") or {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                kk = self._clean(k)
                if any(term in kk for term in ["substr", "forof", "phorophy", "host", "bark", "wood"]):
                    if v not in [None, "", [], {}]:
                        parts.append(str(v))

        text = " ".join(parts)
        traits = self._traits_from_text(text, source="cartellino")
        if traits:
            traits["source"] = "cartellino"
        return traits

    def _traits_from_text(self, value, source="unknown"):
        txt = self._clean(value)
        if not txt:
            return {}

        traits = {
            "raw": str(value),
            "source": source,
            "tree_type": None,
            "forest_type": None,
            "bark_ph": None,
            "humidity": None,
            "texture": None,
            "soil_lithology": None,
            "forest_category": None,
        }

        # Rimuove parole di contesto del cartellino, ma mantiene il nome utile.
        txt = txt.replace("su ", " ").replace("on ", " ").replace("corteccia di", " ")
        txt = txt.replace("tronco di", " ").replace("rami di", " ").replace("legno di", " ")

        if any(k in txt for k in ["abieteto", "abieteti", "abies", "abete bianco"]):
            traits.update({"tree_type": "abies", "forest_type": "conifer", "bark_ph": "acid", "humidity": "high", "texture": "rough", "forest_category": "abieteto"})
        elif any(k in txt for k in ["pecceta", "peccete", "picea", "abete rosso", "peccio"]):
            traits.update({"tree_type": "picea", "forest_type": "conifer", "bark_ph": "acid", "humidity": "high", "texture": "rough", "forest_category": "pecceta"})
        elif any(k in txt for k in ["lariceto", "lariceti", "larix", "larice"]):
            traits.update({"tree_type": "larix", "forest_type": "open_conifer", "bark_ph": "acid", "humidity": "medium", "texture": "rough", "forest_category": "lariceto"})
        elif any(k in txt for k in ["pineta", "pinete", "pinus", "pino", "mugheta", "pino mugo"]):
            traits.update({"tree_type": "pinus", "forest_type": "conifer", "bark_ph": "acid", "humidity": "low", "texture": "rough", "forest_category": "pineta"})
        elif any(k in txt for k in ["faggeta", "faggete", "fagus", "faggio"]):
            traits.update({"tree_type": "fagus", "forest_type": "broadleaf", "bark_ph": "subneutral", "humidity": "medium", "texture": "smooth", "forest_category": "faggeta"})
        elif any(k in txt for k in ["querceto", "querceti", "quercus", "quercia", "roverella", "rovere", "cerro"]):
            traits.update({"tree_type": "quercus", "forest_type": "broadleaf", "bark_ph": "subneutral", "humidity": "medium", "texture": "rough", "forest_category": "querceto"})
        elif any(k in txt for k in ["castagneto", "castagneti", "castanea", "castagno"]):
            traits.update({"tree_type": "castanea", "forest_type": "broadleaf", "bark_ph": "acid", "humidity": "medium", "texture": "rough", "forest_category": "castagneto"})
        elif any(k in txt for k in ["ontaneta", "ontaneti", "alnus", "ontano"]):
            traits.update({"tree_type": "alnus", "forest_type": "riparian", "bark_ph": "basic", "humidity": "high", "texture": "rough", "forest_category": "ontaneta"})
        elif any(k in txt for k in ["saliceto", "saliceti", "salix", "salice"]):
            traits.update({"tree_type": "salix", "forest_type": "riparian", "bark_ph": "subneutral", "humidity": "high", "texture": "rough", "forest_category": "saliceto"})
        elif any(k in txt for k in ["pioppeto", "pioppeti", "populus", "pioppo"]):
            traits.update({"tree_type": "populus", "forest_type": "riparian", "bark_ph": "subneutral", "humidity": "high", "texture": "rough", "forest_category": "pioppeto"})
        elif any(k in txt for k in ["acereto", "acereti", "acer", "acero"]):
            traits.update({"tree_type": "acer", "forest_type": "broadleaf", "bark_ph": "subneutral", "humidity": "medium", "texture": "smooth", "forest_category": "acereto"})
        elif any(k in txt for k in ["frassineto", "frassineti", "fraxinus", "frassino"]):
            traits.update({"tree_type": "fraxinus", "forest_type": "broadleaf", "bark_ph": "subneutral", "humidity": "medium", "texture": "rough", "forest_category": "frassineto"})
        elif any(k in txt for k in ["betuleto", "betuleti", "betula", "betulla"]):
            traits.update({"tree_type": "betula", "forest_type": "broadleaf", "bark_ph": "acid", "humidity": "medium", "texture": "smooth", "forest_category": "betuleto"})
        elif any(k in txt for k in ["bosco misto", "misto", "formazioni miste"]):
            traits.update({"tree_type": "bosco", "forest_type": "mixed", "bark_ph": "mixed", "humidity": "medium", "texture": "mixed", "forest_category": "bosco_misto"})
        elif any(k in txt for k in ["latifoglie", "latifoglia", "broadleaf", "deciduo", "decidua"]):
            traits.update({"tree_type": "latifoglie", "forest_type": "broadleaf", "bark_ph": "subneutral", "humidity": "medium", "texture": "mixed", "forest_category": "latifoglie"})
        elif any(k in txt for k in ["conifere", "conifera", "aghifoglie", "resinose", "conifer"]):
            traits.update({"tree_type": "conifere", "forest_type": "conifer", "bark_ph": "acid", "humidity": "medium", "texture": "rough", "forest_category": "conifere"})
        elif any(k in txt for k in ["corteccia", "bark", "tronco", "ramo", "legno", "wood"]):
            traits.update({"tree_type": "bosco", "forest_type": "forest", "bark_ph": None, "humidity": "medium", "texture": "mixed", "forest_category": "generic_tree_substrate"})
        elif source == "forest_layer" and any(k in txt for k in ["bosco", "forest", "foresta"]):
            traits.update({"tree_type": "bosco", "forest_type": "forest", "bark_ph": None, "humidity": "medium", "texture": "mixed", "forest_category": "forest_unknown"})
        else:
            return {}

        if any(k in txt for k in ["carbonatic", "calcare", "calcari", "dolomit"]):
            traits["soil_lithology"] = "calcareo"
        elif any(k in txt for k in ["silic", "silice", "acidi", "acidof", "cristallin"]):
            traits["soil_lithology"] = "siliceo"
        elif any(k in txt for k in ["alluvial", "riparial", "igrofil", "palud"]):
            traits["soil_lithology"] = "umido_ripariale"

        return traits
