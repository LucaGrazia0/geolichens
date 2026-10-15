from ._shared_geo_utils import to_float as _shared_to_float


class EcologicalLayerDecisionService:
    """
    Decide quali layer ambientali usare in base al profilo ecologico del taxon.

    È volutamente conservativo: non rimuove dati dal profilo ITALIC, ma aggiunge
    un dizionario 'layer_decision' che gli altri servizi possono usare per non
    applicare sempre la litologia anche quando il lichene è terricolo/epifita.
    """

    SAXICOLOUS = ["sax", "rupicol", "rock", "rocks", "stone", "rocc", "muro", "wall", "cliff"]
    TERRICOLOUS = ["terr", "soil", "ground", "earth", "suolo", "terreno", "humus"]
    EPIPHYTIC = ["epif", "epiph", "bark", "cortecc", "tree", "phorophy", "forophy", "tronco"]
    LIGNICOLOUS = ["lign", "wood", "dead wood", "legno", "ceppaia"]
    MUSCICOLOUS = ["moss", "mosses", "muschi", "bryophy", "muscicol"]

    ACID = ["acid", "acidoph", "acidic", "acid substrata", "silic", "silice", "siliceous", "torb", "peat"]
    BASIC = ["basic", "basiph", "base-rich", "calcare", "calcareous", "calcicol", "limestone", "dolomit", "carbonat"]

    def decide(self, profile, record_constraints=None):
        profile = profile or {}
        record_constraints = record_constraints or {}

        # La decisione usa prima il risultato centralizzato. Quando il
        # substrato è locked, le classi sono mutuamente esclusive e ITALIC non
        # può riattivare una pipeline diversa.
        group = str(
            profile.get("substrate_group")
            or record_constraints.get("substrate_group")
            or ""
        ).strip().lower()
        locked = bool(
            profile.get("substrate_locked")
            or record_constraints.get("substrate_locked")
            or (profile.get("record_locks") or {}).get("substrate")
        )

        text = self._profile_text(profile)
        substrata = " ".join(str(x) for x in (profile.get("substrata") or []))
        habitat = " ".join(str(x) for x in (profile.get("habitat") or []))
        all_text = (text + " " + substrata + " " + habitat).lower()

        if group in ("rock", "soil", "epiphyte", "lignicolous", "moss"):
            is_sax = group == "rock"
            is_terr = group == "soil"
            is_epi = group == "epiphyte"
            is_lign = group == "lignicolous"
            is_musc = group == "moss"
        else:
            is_sax = self._has_any(all_text, self.SAXICOLOUS)
            is_terr = self._has_any(all_text, self.TERRICOLOUS)
            is_epi = self._has_any(all_text, self.EPIPHYTIC)
            is_lign = self._has_any(all_text, self.LIGNICOLOUS)
            is_musc = self._has_any(all_text, self.MUSCICOLOUS)

            rec_sub = str(record_constraints.get("substrate") or "").lower()
            if rec_sub:
                is_sax = is_sax or self._has_any(rec_sub, self.SAXICOLOUS)
                is_terr = is_terr or self._has_any(rec_sub, self.TERRICOLOUS)
                is_epi = is_epi or self._has_any(rec_sub, self.EPIPHYTIC)
                is_lign = is_lign or self._has_any(rec_sub, self.LIGNICOLOUS)
                is_musc = is_musc or self._has_any(rec_sub, self.MUSCICOLOUS)

        ph = self._infer_ph(profile, all_text)
        use_geology = bool(is_sax)
        use_soil = bool(is_terr or is_musc)
        use_trees = bool(is_epi or is_lign)

        if group == "rock":
            primary = "geology"
        elif group in ("soil", "moss"):
            primary = "soil"
        elif group in ("epiphyte", "lignicolous"):
            primary = "trees"
        elif not (use_geology or use_soil or use_trees):
            primary = "unknown"
            use_geology = bool(profile.get("rock_type")) and not locked
        elif use_trees:
            primary = "trees"
        elif use_soil:
            primary = "soil"
        else:
            primary = "geology"

        return {
            "substrate_group": group or "unknown",
            "substrate_locked": locked,
            "primary_layer": primary,
            "use_geology": use_geology,
            "use_soil": use_soil,
            "use_trees": use_trees,
            "is_saxicolous": is_sax,
            "is_terricolous": is_terr,
            "is_epiphytic": is_epi,
            "is_lignicolous": is_lign,
            "is_muscicolous": is_musc,
            "soil_ph_preference": ph,
            "explain": self._explain(primary, use_geology, use_soil, use_trees, ph)
                + f"; substrate_group={group or 'unknown'}; locked={locked}",
        }

    def _infer_ph(self, profile, text):
        ecology = profile.get("ecology_raw") or {}
        lo = self._to_float(self._value(ecology, "ph_of_the_substrata_min"))
        hi = self._to_float(self._value(ecology, "ph_of_the_substrata_max"))
        if lo is not None or hi is not None:
            lo = lo if lo is not None else hi
            hi = hi if hi is not None else lo
            if hi is not None and hi <= 2:
                return "acid"
            if lo is not None and lo >= 4:
                return "basic"
            if lo is not None and hi is not None and lo <= 2 and hi >= 4:
                return "broad"
        has_acid = self._has_any(text, self.ACID)
        has_basic = self._has_any(text, self.BASIC)
        if has_acid and has_basic:
            return "broad"
        if has_acid:
            return "acid"
        if has_basic:
            return "basic"
        return None

    def _explain(self, primary, geo, soil, trees, ph):
        bits = ["layer primario: " + str(primary)]
        enabled = []
        if geo:
            enabled.append("geologia")
        if soil:
            enabled.append("suolo")
        if trees:
            enabled.append("alberi")
        bits.append("layer usati: " + (", ".join(enabled) if enabled else "nessun filtro forte"))
        if ph:
            bits.append("preferenza pH: " + ph)
        return "; ".join(bits)

    def _profile_text(self, profile):
        parts = [
            profile.get("ecology_traits"), profile.get("notes"), profile.get("raw_substrata"),
            profile.get("regions_distribution"), profile.get("ecoregions_distribution"),
            profile.get("ecology_source_note"), profile.get("rock_type"), profile.get("tree_type"),
        ]
        raw = profile.get("ecology_raw") or {}
        if isinstance(raw, dict):
            parts.extend(str(v) for v in raw.values() if v not in [None, "", [], {}])
        return " ".join(str(p) for p in parts if p not in [None, "", [], {}])

    def _has_any(self, text, needles):
        text = str(text or "").lower()
        return any(n in text for n in needles)

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
