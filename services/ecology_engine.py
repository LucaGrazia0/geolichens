from ._shared_geo_utils import to_float as _shared_to_float


class EcologyEngine:
    """
    Motore ecologico per trasformare profili ITALIC in:
    - vincoli GIS
    - score ecologico 0-100

    Versione GeoLichen 1.8 - Ecological Weighted Scoring:
    - evita pareggi sistematici che selezionano sempre il punto basso-sinistra
    - penalizza incompatibilità forti
    - usa quota, pendenza, litologia, substrato, umidità
    - restituisce dettagli leggibili
    """

    def compute_constraints(self, profile):
        """Build GIS constraints from one resolved ecological context.

        The canonical ``substrate_group`` produced by
        :class:`SubstrateResolutionService` is authoritative. ITALIC text is
        used only as a fallback when no resolved group is available.
        """
        profile = profile or {}
        habitat = self._as_list(profile.get("habitat"))
        substrata = self._as_list(profile.get("substrata"))
        rock_type = self._clean(profile.get("rock_type"))
        layer_decision = profile.get("layer_decision") or {}
        locks = profile.get("record_locks") or {}

        group = self._canonical_substrate_group(profile)
        substrate_value = self._legacy_substrate_value(group)

        constraints = {
            "layer_decision": layer_decision,
            "soil_ph_preference": layer_decision.get("soil_ph_preference"),
            "altitude_min": None,
            "altitude_max": None,
            "substrate": substrate_value,
            "substrate_group": group,
            "substrate_source": profile.get("substrate_source") or "unknown",
            "substrate_locked": bool(profile.get("substrate_locked") or locks.get("substrate")),
            "substrate_confidence": profile.get("substrate_confidence"),
            "substrate_resolution_reason": profile.get("substrate_resolution_reason"),
            "rock_type": None,
            "slope": "alto" if group == "rock" else None,
            "humidity": None,
            "habitat": habitat,
        }

        if "alpino" in habitat:
            constraints["altitude_min"] = 1800
            constraints["altitude_max"] = 3500
        elif "subalpino" in habitat:
            constraints["altitude_min"] = 1200
            constraints["altitude_max"] = 2400

        if rock_type in {"siliceo", "calcareo", "misto"}:
            constraints["rock_type"] = rock_type

        # Legacy ITALIC fallback only when the central resolver did not return
        # a supported group. This branch must never override a locked record.
        if group == "unknown":
            fallback_group = self._substrate_group_from_italic(substrata, habitat)
            if fallback_group != "unknown":
                group = fallback_group
                constraints["substrate_group"] = group
                constraints["substrate"] = self._legacy_substrate_value(group)
                constraints["substrate_source"] = "ITALIC_fallback"
                constraints["substrate_locked"] = False
                constraints["slope"] = "alto" if group == "rock" else None

        if "umido" in habitat:
            constraints["humidity"] = "alta"
        elif "secco" in habitat:
            constraints["humidity"] = "bassa"

        try:
            ad_min, ad_max = self._italic_altitudinal_distribution_range(profile)
            if ad_min is not None:
                constraints["altitude_min"] = ad_min
                constraints["altitudinal_distribution_min"] = ad_min
            if ad_max is not None:
                constraints["altitude_max"] = ad_max
                constraints["altitudinal_distribution_max"] = ad_max
            if ad_min is not None or ad_max is not None:
                constraints["altitudinal_distribution_source"] = profile.get("altitudinal_distribution_source") or "ITALIC"
                if profile.get("italic_altitude_class_min") is not None:
                    constraints["italic_altitude_class_min"] = profile.get("italic_altitude_class_min")
                if profile.get("italic_altitude_class_max") is not None:
                    constraints["italic_altitude_class_max"] = profile.get("italic_altitude_class_max")
        except Exception:
            pass

        # Explicit record values remain authoritative for their own fields.
        if locks.get("rock_type") and profile.get("rock_type"):
            constraints["rock_type"] = profile.get("rock_type")
        if locks.get("tree_type") and profile.get("tree_type"):
            constraints["tree_type"] = profile.get("tree_type")
        if locks.get("aspect") and profile.get("record_aspect"):
            constraints["record_aspect"] = profile.get("record_aspect")

        return constraints

    @staticmethod
    def _legacy_substrate_value(group):
        return {
            "soil": "suolo",
            "rock": "roccia",
            "epiphyte": "albero",
            "lignicolous": "legno",
            "moss": "muschio",
        }.get(group)

    def _canonical_substrate_group(self, profile):
        """Return the central resolver result without reclassifying text."""
        group = self._clean(profile.get("substrate_group"))
        aliases = {
            "soil": "soil", "suolo": "soil", "terricolo": "soil",
            "rock": "rock", "roccia": "rock", "saxicolo": "rock",
            "epiphyte": "epiphyte", "epifita": "epiphyte", "albero": "epiphyte",
            "lignicolous": "lignicolous", "lignicolo": "lignicolous", "legno": "lignicolous",
            "moss": "moss", "muschio": "moss", "muscicolo": "moss",
        }
        if group in aliases:
            return aliases[group]

        # Compatibility with profiles produced before substrate_group existed.
        legacy = self._clean(profile.get("substrate"))
        if legacy in aliases:
            return aliases[legacy]
        return "unknown"

    @staticmethod
    def _substrate_group_from_italic(substrata, habitat):
        """Conservative fallback for legacy/ITALIC-only profiles."""
        values = {str(value).strip().lower() for value in (substrata or [])}
        habitats = {str(value).strip().lower() for value in (habitat or [])}
        if "saxicolo" in values or "rupicolo" in habitats:
            return "rock"
        if "terricolo" in values:
            return "soil"
        if "epifita" in values:
            return "epiphyte"
        if "lignicolo" in values:
            return "lignicolous"
        if "muscicolo" in values:
            return "moss"
        return "unknown"


    def _italic_altitude_classes_to_meters(self, cmin, cmax):
        bands = {
            1: (0, 600),
            2: (400, 1000),
            3: (800, 1700),
            4: (1600, 2400),
            5: (2200, 3000),
            6: (2800, 4000),
        }

        def to_class(v):
            try:
                if v in [None, "", [], {}]:
                    return None
                x = int(round(float(str(v).replace(",", "."))))
                return x if x in bands else None
            except Exception:
                return None

        lo_c = to_class(cmin)
        hi_c = to_class(cmax)
        if lo_c is None and hi_c is None:
            return None, None
        if lo_c is None:
            lo_c = hi_c
        if hi_c is None:
            hi_c = lo_c
        if lo_c > hi_c:
            lo_c, hi_c = hi_c, lo_c
        return bands[lo_c][0], bands[hi_c][1]

    def _italic_altitudinal_distribution_range(self, profile):
        profile = profile or {}

        def parse(v):
            try:
                if v in [None, "", [], {}]:
                    return None
                x = float(str(v).replace(",", "."))
                if x <= 0 or x > 9000:
                    return None
                return x
            except Exception:
                return None

        amin = parse(profile.get("altitudinal_distribution_min"))
        amax = parse(profile.get("altitudinal_distribution_max"))

        # Fallback nuovo: classi ITALIC 1-6 convertite in metri.
        if amin is None and amax is None:
            cmin = profile.get("italic_altitude_class_min")
            cmax = profile.get("italic_altitude_class_max")
            amin, amax = self._italic_altitude_classes_to_meters(cmin, cmax)

        raw = profile.get("ecology_raw") or {}
        if isinstance(raw, dict):
            if amin is None:
                amin = parse(raw.get("altitudinal_distribution_min"))
            if amax is None:
                amax = parse(raw.get("altitudinal_distribution_max"))

        # Fallback ulteriore: se raw contiene classi ordinali.
        if amin is None and amax is None and isinstance(raw, dict):
            cmin = raw.get("altitudinal_distribution_min") or raw.get("altitudinal_distribution")
            cmax = raw.get("altitudinal_distribution_max") or raw.get("altitudinal_distribution")
            amin, amax = self._italic_altitude_classes_to_meters(cmin, cmax)

        if amin is not None and amax is not None and amin > amax:
            amin, amax = amax, amin
        return amin, amax

    def compute_score(self, profile, env):
        """
        GeoLichen 1.8.2 - ITALIC ecological similarity.

        Obiettivo:
        - usare di più gli indici ITALIC;
        - mantenere il substrato come indicatore morbido, non come esclusione;
        - far prevalere l'ecologia sull'accessibilità.

        Score:
        ecological_score = 0-100
        final score = calcolato dal servizio habitat usando anche accessibilità.
        """
        profile = profile or {}
        env = env or {}

        habitat = self._as_list(profile.get("habitat"))
        substrata = self._as_list(profile.get("substrata"))
        profile_rock = self._clean(profile.get("rock_type"))
        constraints = self.compute_constraints(profile)
        layer_decision = constraints.get("layer_decision") or {}
        use_geology = layer_decision.get("use_geology", True)
        use_soil = layer_decision.get("use_soil", True)
        use_trees = layer_decision.get("use_trees", True)

        details = []
        ecological_score = 0.0

        env_rock = self._clean(env.get("rock_type"))
        env_substrate = self._clean(env.get("substrate"))
        altitude = self._to_float(env.get("altitude"))
        slope = self._to_float(env.get("slope"))
        aspect_cls = self._clean(env.get("aspect_class"))
        exposure = self._clean(env.get("exposure"))
        env_humidity = self._clean(env.get("humidity"))
        env_soil = self._clean(env.get("soil_ph") or env.get("soil_raw") or "")
        env_tree = self._clean(env.get("tree_raw") or env.get("tree_type"))
        wanted_substrate = constraints.get("substrate")

        # 1) Litologia/roccia - max 15
        lithology_score = 0.0
        if profile_rock and use_geology:
            if env_rock:
                if self._rock_compatible(profile_rock, env_rock):
                    lithology_score = 15.0
                    details.append("litologia compatibile (+15)")
                else:
                    lithology_score = -12.0
                    details.append("litologia poco compatibile (-12)")
            else:
                lithology_score = 3.0
                details.append("litologia richiesta ma dato GIS assente (+3 prudenziale)")
        ecological_score += lithology_score

        # 2) Substrato - max 12, morbido
        substrate_score = 0.0
        if wanted_substrate:
            if env_substrate:
                if self._substrate_compatible(wanted_substrate, env_substrate):
                    substrate_score = 12.0
                    details.append("substrato compatibile (+12)")
                else:
                    # Non è esclusione: layer grossolani possono classificare come suolo
                    # aree con micro-affioramenti o rocce sparse.
                    substrate_score = -6.0
                    details.append("substrato non ideale ma mantenuto come candidato (-6)")
            else:
                if wanted_substrate == "roccia" and slope is not None and slope >= 30:
                    substrate_score = 6.0
                    details.append("substrato non letto ma pendenza compatibile con rupicolo (+6)")
                else:
                    substrate_score = 2.0
                    details.append("substrato richiesto ma dato GIS assente (+2 prudenziale)")
        ecological_score += substrate_score

        # 3) Quota ITALIC + record - max 22
        altitude_score = 0.0
        alt_min = constraints.get("altitude_min")
        alt_max = constraints.get("altitude_max")
        if alt_min is not None and altitude is not None:
            italic_alt_score = self._altitude_score_v18(altitude, alt_min, alt_max, max_score=10.0)
            altitude_score += italic_alt_score
            details.append(f"quota ITALIC {round(altitude)} m: {round(italic_alt_score,1)} punti")
        elif alt_min is not None:
            altitude_score += 2.0
            details.append("quota ITALIC richiesta ma DEM assente (+2 prudenziale)")

        record_altitude = self._record_altitude(profile, env)
        if record_altitude is not None and altitude is not None:
            rec_score = self._record_altitude_match_score_v18(altitude, record_altitude)
            # nella 1.8.2 la quota record resta importante ma non deve schiacciare ITALIC
            rec_score = max(-10.0, min(12.0, rec_score))
            altitude_score += rec_score
            delta_alt = abs(float(altitude) - float(record_altitude))
            if rec_score >= 0:
                details.append(f"quota record compatibile: record {round(record_altitude)} m, DEM {round(altitude)} m, Δ={round(delta_alt)} m (+{round(rec_score,1)})")
            else:
                details.append(f"quota record poco compatibile: record {round(record_altitude)} m, DEM {round(altitude)} m, Δ={round(delta_alt)} m ({round(rec_score,1)})")
        altitude_score = max(-18.0, min(22.0, altitude_score))
        ecological_score += altitude_score

        # 4) Habitat sintetico - max 16
        habitat_score = 0.0
        if "alpino" in habitat and altitude is not None and altitude >= 1800:
            habitat_score += 4
        if "rupicolo" in habitat and (env_substrate == "roccia" or (slope is not None and slope >= 25) or env_rock):
            habitat_score += 4
        if "aperto" in habitat and env_substrate not in {"bosco", "albero"}:
            habitat_score += 3
        if "bosco" in habitat and env_substrate in {"bosco", "albero"}:
            habitat_score += 4
        if "secco" in habitat:
            if env_humidity == "bassa":
                habitat_score += 3
            elif slope is not None and slope >= 30:
                habitat_score += 2
            elif env_humidity == "alta":
                habitat_score -= 2
        if "umido" in habitat:
            if env_humidity == "alta":
                habitat_score += 3
            elif env_humidity == "bassa":
                habitat_score -= 2
        habitat_score = max(-8.0, min(16.0, habitat_score))
        ecological_score += habitat_score
        if habitat_score:
            details.append(f"coerenza habitat ITALIC/GIS ({round(habitat_score,1)})")

        # 5) Pendenza/topografia - max 7
        topo_score = 0.0
        if "rupicolo" in habitat or "saxicolo" in substrata:
            if slope is not None:
                topo_score = min(7.0, self._slope_score_v18(slope) * 0.7)
                details.append(f"pendenza {round(slope,1)}°: {round(topo_score,1)} punti")
            else:
                topo_score = 1.5
                details.append("pendenza richiesta ma dato assente (+1.5 prudenziale)")
        ecological_score += topo_score

        # 6) ITALIC pH - max 12
        ph_score = self._italic_ph_similarity_score(profile, env)
        ecological_score += ph_score
        if ph_score:
            details.append(f"compatibilità pH ITALIC/GIS ({round(ph_score,1)})")

        # 7) ITALIC aridità - max 10
        aridity_score = self._italic_aridity_similarity_score(profile, env)
        ecological_score += aridity_score
        if aridity_score:
            details.append(f"compatibilità aridità ITALIC/GIS ({round(aridity_score,1)})")

        # 8) ITALIC irraggiamento - max 8
        solar_score = self._italic_solar_similarity_score(profile, env)
        ecological_score += solar_score
        if solar_score:
            details.append(f"compatibilità irraggiamento ITALIC/GIS ({round(solar_score,1)})")

        # 9) ITALIC eutrofizzazione/poleotolleranza - max 3 informativo
        # Per ora non abbiamo layer robusti; usiamo solo una micro-compatibilità
        # legata ad accessibilità/antropizzazione, senza farla dominare.
        micro_anthro = self._italic_anthro_similarity_score(profile, env)
        ecological_score += micro_anthro
        if micro_anthro:
            details.append(f"compatibilità eutrofizzazione/poleotolleranza ITALIC proxy ({round(micro_anthro,1)})")

        # 10) Profilo ITALIC presente - max 5
        profile_score = 0.0
        confidence = self._clean(profile.get("ecology_confidence"))
        source = self._clean(profile.get("ecology_source"))
        if source in {"fallback_species", "fallback_genus"} or confidence == "bassa":
            profile_score = 2.0
            details.append("profilo ecologico da fallback: confidenza bassa (+2)")
        elif profile.get("ecology_traits") or profile.get("notes"):
            profile_score = 5.0
            details.append("profilo ecologico ITALIC presente (+5)")
        ecological_score += profile_score

        ecological_score = max(0.0, min(100.0, ecological_score))

        # Accessibilità provvisoria, se non viene sovrascritta dal servizio habitat.
        trail_dist = self._to_float(env.get("trail_dist_m"))
        accessibility_score = env.get("accessibility_score")
        if accessibility_score is None:
            accessibility_score = self._accessibility_score_from_trail(trail_dist)

        if trail_dist is not None:
            details.append(f"accessibilità sentiero: distanza {round(trail_dist)} m, score {round(float(accessibility_score),1)}/100")
        else:
            details.append("accessibilità sentiero non valutata")

        # Formula base conservativa: più ITALIC/ecologia, meno accessibilità.
        final_score = (0.85 * ecological_score) + (0.15 * float(accessibility_score or 50.0))
        tie = min(0.3, self._tie_break(env))
        final_score += tie
        if tie:
            details.append(f"tie-break spaziale (+{round(tie,3)})")

        final_score = max(0.0, min(100.0, final_score))

        return {
            "score": int(round(final_score)),
            "raw_score": final_score,
            "ecological_score": ecological_score,
            "accessibility_score": accessibility_score,
            "details": details,
            "constraints": constraints,
        }

    def _italic_range(self, profile, base_name):
        profile = profile or {}
        raw = profile.get("ecology_raw") or {}
        mn = profile.get(base_name + "_min")
        mx = profile.get(base_name + "_max")
        if mn in [None, "", [], {}] and isinstance(raw, dict):
            mn = raw.get(base_name + "_min")
        if mx in [None, "", [], {}] and isinstance(raw, dict):
            mx = raw.get(base_name + "_max")
        try:
            mn = None if mn in [None, "", [], {}] else float(str(mn).replace(",", "."))
        except Exception:
            mn = None
        try:
            mx = None if mx in [None, "", [], {}] else float(str(mx).replace(",", "."))
        except Exception:
            mx = None
        if mn is not None and mx is not None and mn > mx:
            mn, mx = mx, mn
        return mn, mx

    def _range_similarity(self, value, mn, mx, max_score=10.0, tolerance=1.0):
        try:
            if value is None or (mn is None and mx is None):
                return 0.0
            v = float(value)
            if mn is None:
                mn = mx
            if mx is None:
                mx = mn
            if mn <= v <= mx:
                return float(max_score)
            if v < mn:
                diff = mn - v
            else:
                diff = v - mx
            if diff >= tolerance:
                return -float(max_score) * 0.4
            return float(max_score) * (1.0 - diff / tolerance)
        except Exception:
            return 0.0

    def _env_ph_class(self, env):
        env = env or {}

        def safe_clean(value):
            try:
                cleaned = self._clean(value)
                return "" if cleaned is None else str(cleaned)
            except Exception:
                return ""

        txt = safe_clean(env.get("soil_ph") or env.get("soil_raw") or "")
        rock = safe_clean(env.get("rock_type") or "")
        litho_ph = safe_clean(env.get("litho_soil_ph") or "")

        joined = " ".join([txt, rock, litho_ph]).lower()

        if any(k in joined for k in ["acid", "acido", "acida", "silic", "silice", "gneiss", "granito", "paragneiss", "quarz"]):
            return 2.0
        if any(k in joined for k in ["neutral", "neutro", "neutra"]):
            return 3.0
        if any(k in joined for k in ["basic", "basico", "basica", "calcare", "calcari", "dolomit", "carbonat"]):
            return 5.0
        return None

    def _italic_ph_similarity_score(self, profile, env):
        mn, mx = self._italic_range(profile, "ph_of_the_substrata")
        env_ph = self._env_ph_class(env)
        return self._range_similarity(env_ph, mn, mx, max_score=12.0, tolerance=1.5)

    def _env_aridity_class(self, env):
        env = env or {}
        slope = self._to_float(env.get("slope"))
        exposure = self._clean(env.get("exposure"))
        humidity = self._clean(env.get("humidity"))

        score = 3.0
        if humidity == "bassa":
            score += 0.8
        elif humidity == "alta":
            score -= 0.8
        if slope is not None:
            if slope >= 35:
                score += 0.8
            elif slope >= 20:
                score += 0.4
            elif slope < 8:
                score -= 0.3
        if exposure == "south":
            score += 0.6
        elif exposure == "north":
            score -= 0.5
        return max(1.0, min(5.0, score))

    def _italic_aridity_similarity_score(self, profile, env):
        mn, mx = self._italic_range(profile, "aridity")
        arid = self._env_aridity_class(env)
        return self._range_similarity(arid, mn, mx, max_score=10.0, tolerance=1.3)

    def _env_solar_class(self, env):
        env = env or {}
        exposure = self._clean(env.get("exposure"))
        substrate = self._clean(env.get("substrate"))
        tree = self._clean(env.get("tree_type") or env.get("tree_raw"))
        slope = self._to_float(env.get("slope"))

        score = 3.0
        if substrate in {"bosco", "albero"} or tree:
            score -= 1.0
        if exposure == "south":
            score += 1.0
        elif exposure in {"east", "west"}:
            score += 0.4
        elif exposure == "north":
            score -= 0.7
        if slope is not None and slope >= 25:
            score += 0.3
        return max(1.0, min(5.0, score))

    def _italic_solar_similarity_score(self, profile, env):
        mn, mx = self._italic_range(profile, "solar_irradiation")
        sol = self._env_solar_class(env)
        return self._range_similarity(sol, mn, mx, max_score=8.0, tolerance=1.3)

    def _italic_anthro_similarity_score(self, profile, env):
        eu_min, eu_max = self._italic_range(profile, "eutrophication")
        po_min, po_max = self._italic_range(profile, "poleotolerance")
        trail = self._to_float(env.get("trail_dist_m"))

        if trail is None:
            anthropic = 2.0
        elif trail <= 50:
            anthropic = 3.0
        elif trail <= 200:
            anthropic = 2.5
        elif trail <= 700:
            anthropic = 2.0
        else:
            anthropic = 1.5

        score = 0.0
        score += self._range_similarity(anthropic, eu_min, eu_max, max_score=1.5, tolerance=1.5)
        score += self._range_similarity(anthropic, po_min, po_max, max_score=1.5, tolerance=1.5)
        return max(-2.0, min(3.0, score))



    def _accessibility_score_from_trail(self, distance_m):
        """Fallback interno per accessibilità da sentiero.

        Serve quando compute_score viene chiamato fuori da HabitatSuitabilityService,
        ad esempio durante l'analisi del record nel controller, prima della griglia.
        """
        try:
            if distance_m is None:
                return 50.0
            d = float(distance_m)
            if d <= 20:
                return 100.0
            if d <= 50:
                return 95.0
            if d <= 100:
                return 88.0
            if d <= 200:
                return 75.0
            if d <= 400:
                return 55.0
            if d <= 700:
                return 35.0
            if d <= 1000:
                return 15.0
            if d <= 1500:
                return 5.0
            return 0.0
        except Exception:
            return 50.0



    def _record_altitude_match_score_v18(self, dem_altitude, record_altitude):
        """Punteggio morbido per quota da cartellino."""
        try:
            delta = abs(float(dem_altitude) - float(record_altitude))
        except Exception:
            return 0.0
        if delta <= 25:
            return 15.0
        if delta <= 50:
            return 13.0
        if delta <= 100:
            return 10.0
        if delta <= 150:
            return 6.0
        if delta <= 250:
            return 2.0
        if delta <= 350:
            return 0.0
        if delta <= 500:
            return -6.0
        return -10.0


    def _altitude_score_v18(self, altitude, alt_min, alt_max, max_score=10.0):
        """Compatibilità con fascia altitudinale ITALIC."""
        try:
            altitude = float(altitude)
            alt_min = float(alt_min)
            alt_max = float(alt_max) if alt_max is not None else alt_min + 1500
        except Exception:
            return 0.0

        if alt_min <= altitude <= alt_max:
            return float(max_score)

        if altitude < alt_min:
            diff = alt_min - altitude
        else:
            diff = altitude - alt_max

        if diff >= 800:
            return -4.0
        if diff >= 500:
            return 0.0
        return max(0.0, float(max_score) * (1.0 - diff / 500.0))


    def _slope_score_v18(self, slope):
        """Compatibilità morfologica per taxa rupicoli/saxicoli."""
        try:
            slope = float(slope)
        except Exception:
            return 0.0
        if slope >= 45:
            return 10.0
        if slope >= 30:
            return 8.0
        if slope >= 20:
            return 5.0
        if slope >= 10:
            return 2.0
        return 0.0


    def _rock_compatible(self, wanted, actual):
        wanted = self._clean(wanted)
        actual = self._clean(actual)
        if not wanted or not actual:
            return False
        return wanted == actual or wanted == "misto" or actual == "misto"

    def _substrate_compatible(self, wanted, actual):
        wanted = self._clean(wanted)
        actual = self._clean(actual)
        if wanted == actual:
            return True
        if wanted == "roccia" and actual in {"roccia", "parete", "rupicolo"}:
            return True
        if wanted == "albero" and actual in {"albero", "bosco"}:
            return True
        if wanted == "suolo" and actual in {"suolo", "terra", "acid", "acido", "acida", "basic", "basico", "basica", "neutral", "neutro", "neutra"}:
            return True
        if wanted == "muschio" and actual in {"muschio", "suolo"}:
            return True
        return False

    def _ph_match_score(self, wanted, actual):
        wanted = self._clean(wanted)
        actual = self._clean(actual)
        if not wanted or not actual:
            return 0.0
        acid_terms = ["acid", "acido", "acidico", "silic", "silice", "torb", "peat"]
        basic_terms = ["basic", "basico", "alcalino", "calcare", "calc", "limestone", "dolomit", "carbonat"]
        neutral_terms = ["neutral", "neutro", "subneutral"]
        if wanted == "broad":
            return 4.0
        if wanted == "acid":
            if any(t in actual for t in acid_terms):
                return 12.0
            if any(t in actual for t in basic_terms):
                return -10.0
        if wanted == "basic":
            if any(t in actual for t in basic_terms):
                return 12.0
            if any(t in actual for t in acid_terms):
                return -10.0
        if wanted == "neutral" and any(t in actual for t in neutral_terms):
            return 8.0
        return 0.0

    def _record_altitude(self, profile, env):
        keys = [
            "record_altitude", "label_altitude", "altitude_record",
            "quota_record", "quota", "elevation_record", "record_elevation"
        ]
        for source in (env or {}, profile or {}):
            for key in keys:
                value = source.get(key) if isinstance(source, dict) else None
                parsed = self._parse_altitude_value(value)
                if parsed is not None:
                    return parsed
        return None

    def _parse_altitude_value(self, value):
        if value in [None, "", [], {}]:
            return None
        try:
            if isinstance(value, (int, float)):
                if -500 <= float(value) <= 9000:
                    return float(value)
                return None
            text = str(value).lower().replace(",", ".")
            import re
            nums = re.findall(r"-?\d+(?:\.\d+)?", text)
            for n in nums:
                v = float(n)
                if -500 <= v <= 9000:
                    return v
        except Exception:
            return None
        return None

    def _record_altitude_match_score(self, dem_altitude, record_altitude):
        """Peso forte della quota del record.

        La quota riportata nel cartellino è spesso una delle informazioni più
        affidabili nei record storici montani. Per questo viene usata come
        vincolo pesato forte, ma non come filtro rigido.

        Schema:
        - Δ <= 50 m: +25
        - Δ <= 100 m: +20
        - Δ <= 150 m: +12
        - Δ <= 250 m: +5
        - Δ <= 300 m: 0
        - Δ <= 500 m: -20
        - Δ > 500 m: -35
        """
        try:
            delta = abs(float(dem_altitude) - float(record_altitude))
        except Exception:
            return 0.0
        if delta <= 50:
            return 25.0
        if delta <= 100:
            return 20.0
        if delta <= 150:
            return 12.0
        if delta <= 250:
            return 5.0
        if delta <= 300:
            return 0.0
        if delta <= 500:
            return -20.0
        return -35.0

    def _altitude_score(self, altitude, alt_min, alt_max):
        altitude = float(altitude)
        alt_min = float(alt_min)
        alt_max = float(alt_max) if alt_max is not None else alt_min + 1500

        if alt_min <= altitude <= alt_max:
            return 20.0

        # tolleranza progressiva di 500 m sotto/sopra
        if altitude < alt_min:
            diff = alt_min - altitude
        else:
            diff = altitude - alt_max

        if diff >= 800:
            return -8.0
        if diff >= 500:
            return 0.0
        return max(0.0, 20.0 * (1.0 - diff / 500.0))

    def _slope_score(self, slope):
        slope = float(slope)
        if slope >= 45:
            return 15.0
        if slope >= 30:
            return 12.0
        if slope >= 20:
            return 8.0
        if slope >= 10:
            return 4.0
        return 0.0

    def _tie_break(self, env):
        # massimo circa 0.9: non cambia ecologia, rompe solo i pareggi
        altitude = self._to_float(env.get("altitude"))
        slope = self._to_float(env.get("slope"))
        dist = self._to_float(env.get("distance_to_center_m"))

        tie = 0.0
        if altitude is not None:
            tie += (altitude % 37) / 100.0
        if slope is not None:
            tie += min(slope, 60) / 200.0
        if dist is not None:
            # lievissima preferenza verso punti non troppo periferici
            tie += max(0.0, 0.2 - min(dist, 2000) / 10000.0)

        # se mancano tutti i dati, comunque niente rumore casuale: resta deterministico
        return min(0.9, tie)

    def summarize(self, profile, env=None):
        constraints = self.compute_constraints(profile)
        score_result = self.compute_score(profile, env or {})

        lines = []
        lines.append("Vincoli ecologici da ITALIC:")
        if constraints.get("rock_type"):
            lines.append(f"- Litologia: {constraints['rock_type']}")
        if constraints.get("substrate"):
            lines.append(f"- Substrato: {constraints['substrate']}")
        if constraints.get("altitude_min") is not None:
            lines.append(f"- Quota: {constraints['altitude_min']}-{constraints['altitude_max']} m")
        if constraints.get("slope"):
            lines.append(f"- Pendenza: {constraints['slope']}")
        if constraints.get("humidity"):
            lines.append(f"- Umidità: {constraints['humidity']}")
        if constraints.get("habitat"):
            lines.append("- Habitat: " + ", ".join(constraints["habitat"]))

        lines.append(f"Score ecologico: {score_result['score']}/100")
        if score_result.get("details"):
            lines.append("Dettagli score:")
            for d in score_result["details"]:
                lines.append(f"- {d}")

        return "\n".join(lines)

    def _as_list(self, value):
        if value is None:
            return []
        if isinstance(value, list):
            return [self._clean(v) for v in value if self._clean(v)]
        if isinstance(value, tuple):
            return [self._clean(v) for v in value if self._clean(v)]
        text = str(value).strip()
        if not text:
            return []
        return [self._clean(x) for x in text.replace(";", ",").split(",") if self._clean(x)]

    def _clean(self, value):
        try:
            if value in [None, "", [], {}]:
                return ""
            return str(value).strip().lower()
        except Exception:
            return ""


    def _to_float(self, value):
        return _shared_to_float(value)


    def compute_functional_bonus(self, profile, env):
        """
        Bonus leggero ecologico per alberi/suolo.
        NON modifica il comportamento precedente se i dati mancano.
        """
        profile = profile or {}
        env = env or {}

        substrata = " ".join(profile.get("substrata") or []).lower()

        score = 0
        details = []

        # Epifite -> alberi importanti
        if any(k in substrata for k in ["epif", "corticol", "bark"]):
            tree = str(env.get("tree_type") or "").lower()

            if tree:
                score += 6
                details.append("forofita presente (+6)")

                if any(k in tree for k in ["abies", "picea", "larix", "pinus"]):
                    score += 3
                    details.append("conifera compatibile (+3)")

        # Terricoli -> suolo importante
        if "terricolo" in substrata:
            soil = str(env.get("soil_type") or "").lower()

            if soil:
                score += 5
                details.append("suolo presente (+5)")

                if any(k in soil for k in ["acid", "torb", "organic"]):
                    score += 3
                    details.append("suolo ecologicamente coerente (+3)")

        return score, details
