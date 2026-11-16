"""Explicit candidate evidence, kept separate from species requirements.

Scores and proxy qualities are conservative model heuristics, not calibrated
probabilities. Missing evidence never proves compatibility or incompatibility.
"""

from ._shared_geo_utils import to_float


class EnvironmentalEvidenceService:
    COMPONENTS = ("substrate", "lithology", "ph", "habitat", "tree_forest")

    @staticmethod
    def _text(value):
        return str(value or "").strip().lower()

    @staticmethod
    def _item(score=None, reason="Dato del candidato non disponibile", source="", quality=1.0,
              applicable=True):
        return {
            "score": score,
            "status": "non applicabile" if not applicable else "mancante" if score is None else "valutato",
            "reason": reason,
            "source": source,
            "quality": quality if score is not None and applicable else 0.0,
        }

    def evaluate(self, env, constraints=None):
        env = env or {}
        constraints = constraints or {}
        group = constraints.get("substrate_group") or env.get("substrate_group") or "unknown"
        woody = group in ("epiphyte", "lignicolous")
        result = {key: self._item() for key in self.COMPONENTS}
        observed = self._text(env.get("substrate"))
        expected = self._text(constraints.get("substrate"))
        if woody:
            for key in ("substrate", "lithology", "ph"):
                result[key] = self._item(reason="Dato del terreno non applicabile al supporto legnoso", applicable=False)
        else:
            # A forest polygon describes cover, not the ground substrate.
            ground = {"roccia", "suolo", "muschio", "rock", "soil", "moss"}
            aliases = {"rock": "roccia", "soil": "suolo", "moss": "muschio"}
            if observed in ground and expected:
                compatible = aliases.get(observed, observed) == aliases.get(expected, expected)
                result["substrate"] = self._item(
                    100.0 if compatible else 40.0,
                    f"Substrato GIS {observed}; atteso {expected}; confronto morbido",
                    "candidate_substrate", quality=0.75,
                )
            rock = self._text(env.get("rock_type"))
            wanted_rock = self._text(constraints.get("rock_type"))
            if rock in {"siliceo", "calcareo", "misto"} and wanted_rock in {"siliceo", "calcareo", "misto"}:
                compatible = rock == wanted_rock or "misto" in (rock, wanted_rock)
                score = 50.0 if "misto" in (rock, wanted_rock) else 100.0 if compatible else 30.0
                result["lithology"] = self._item(
                    score, f"Litologia GIS {rock}; attesa {wanted_rock}", "candidate_lithology", quality=0.75,
                )
            result["ph"] = self._ph(env, group, result["lithology"])

        result["habitat"] = self._habitat(env, constraints)
        if woody:
            result["tree_forest"] = self._tree(env, group)
        else:
            result["tree_forest"] = self._item(
                reason="Copertura forestale valutabile solo come habitat, senza bonus arboreo generico",
                applicable=False,
            )
        return result

    def _ph(self, env, group, lithology):
        if group not in ("soil", "moss"):
            return self._item(reason="Il pH del suolo non misura la reazione della superficie rocciosa", applicable=False)
        expected = self._text(env.get("expected_ph"))
        if expected not in {"acid", "neutral", "basic", "broad"}:
            return self._item(reason="Preferenza di reazione non disponibile; nessun confronto pH")
        numeric = to_float(env.get("soil_ph_num"))
        bonus = to_float(env.get("ph_score"))
        if numeric is not None and bonus is not None and env.get("litho_soil_ph_match") == "numeric_ph":
            score = 50.0 if expected == "broad" else max(0.0, min(100.0, 50.0 + 4.0 * bonus))
            # SoilService returns +6 for a numeric value inside its preferred
            # range. Diagnostic wording must not control the numerical score.
            if expected != "broad" and bonus >= 6.0:
                score = max(85.0, score)
            return self._item(score, env.get("ph_reason") or "Confronto pH numerico del suolo", "soil_ph_numeric")
        observed = self._text(env.get("soil_ph"))
        source, quality = "soil_ph_class", 0.75
        if observed not in {"acid", "neutral", "basic", "broad"}:
            observed = self._text(env.get("litho_soil_ph"))
            source, quality = "lithology_ph_proxy", 0.35
            if lithology.get("score") is not None:
                return self._item(reason="Proxy pH da litologia già usata nel confronto litologico", source=source)
        if observed not in {"acid", "neutral", "basic", "broad"}:
            return self._item(reason="pH del suolo e proxy interpretabili assenti")
        score = 50.0 if "broad" in (expected, observed) else 100.0 if expected == observed else 30.0
        return self._item(score, f"Reazione {observed}; attesa {expected}; fonte {source}", source, quality)

    def _habitat(self, env, constraints):
        raw = constraints.get("habitat") or []
        terms = {self._text(value) for value in (raw if isinstance(raw, (list, tuple, set)) else [raw])}
        assessments = []
        # Forest presence is a cover proxy. Distance alone cannot prove openness.
        forest = bool(env.get("observed_tree") or env.get("tree_type") or env.get("forest_category"))
        forest = forest or to_float(env.get("forest_dist_m")) == 0.0
        wants_forest = bool(terms & {"bosco", "forestale", "forest", "woodland"})
        wants_open = bool(terms & {"aperto", "open", "prateria", "grassland"})
        woody = constraints.get("substrate_group") in ("epiphyte", "lignicolous")
        # The same forest polygon already supplies the woody-support proxy.
        # It must not cast a second vote through habitat for woody groups.
        if forest and not woody and (wants_forest or wants_open):
            score = 50.0 if wants_forest and wants_open else 100.0 if wants_forest else 30.0
            assessments.append((score, 0.5, "Copertura arborea GIS; proxy di habitat forestale/aperto"))
        humidity = self._text(env.get("humidity"))
        wants_wet = bool(terms & {"umido", "wet", "humid"})
        wants_dry = bool(terms & {"secco", "xerico", "dry", "xeric"})
        if humidity in {"alta", "bassa", "high", "low"} and (wants_wet or wants_dry):
            wet = humidity in {"alta", "high"}
            score = 50.0 if wants_wet and wants_dry else 100.0 if wet == wants_wet else 30.0
            assessments.append((score, 1.0, "Umidità del candidato confrontata con l'habitat richiesto"))
        # Quota, slope and lithology already have dedicated components. They
        # cannot independently confirm alpine, rupicolous or dry habitat here.
        if not assessments:
            return self._item(reason="Nessuna osservazione indipendente di habitat; quota e pendenza non replicate")
        quality = sum(item[1] for item in assessments) / len(assessments)
        score = sum(item[0] * item[1] for item in assessments) / sum(item[1] for item in assessments)
        evidence = self._item(score, "; ".join(item[2] for item in assessments), "candidate_habitat", quality)
        evidence["assessments"] = [{"score": score, "quality": quality, "reason": reason}
                                   for score, quality, reason in assessments]
        return evidence

    def _tree(self, env, group):
        observed = self._text(env.get("observed_tree"))
        expected = self._text(env.get("expected_tree"))
        forest = bool(observed or env.get("forest_category") or env.get("tree_type"))
        distance = to_float(env.get("forest_dist_m"))
        exact = bool(expected and observed and expected == observed)
        mapped_cover = env.get("tree_observation_source") == "forest_polygon"
        if group == "epiphyte" and exact:
            return self._item(100.0, "Tipo arboreo atteso presente nel dato GIS", "candidate_phorophyte",
                              quality=0.75 if mapped_cover else 1.0)
        if group == "epiphyte" and expected and observed:
            if mapped_cover:
                return self._item(50.0, "Tipo forestale diverso dal forofita atteso; alberi isolati non esclusi",
                                  "forest_host_unconfirmed", quality=0.35)
            return self._item(30.0, "Forofita osservata diversa da quella attesa; incompatibilità morbida",
                              "candidate_phorophyte")
        if not forest and distance is None:
            return self._item(reason="Nessuna osservazione arborea; la preferenza della specie non è un'osservazione")
        if group == "lignicolous":
            if not forest and distance > 250.0:
                return self._item(reason="Bosco distante; legno morto non verificato e non escluso", source="forest_context")
            return self._item(68.0, "Contesto forestale; legno morto non verificato", "forest_context", quality=0.35)
        if forest:
            bonus = to_float(env.get("tree_match_score")) or 0.0
            score = min(90.0, max(70.0, 50.0 + max(0.0, bonus) * 2.5))
            return self._item(score, "Presenza arborea osservata; forofita specifica non confermata",
                              "candidate_tree_cover", quality=0.75)
        if distance <= 250.0:
            score = 70.0 - max(0.0, distance) * 20.0 / 250.0
            return self._item(score, "Prossimità al bosco; supporto nel punto non verificato",
                              "forest_context", quality=0.5)
        return self._item(reason="Assenza di bosco mappato non esclude alberi isolati", source="forest_context")
