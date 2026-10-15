import re
import unicodedata

from ..models.locality_parse_result_model import LocalityParseResultModel, LocalityReference


class LocalityParserService:
    """Parsa il testo località ed estrae toponimi preservando il nome intero.
    Non cambia il geocoding di base: arricchisce solo il dizionario dei riferimenti geografici.
    """

    def normalize_text(self, text: str) -> str:
        if text is None:
            return ""
        text = str(text).strip()
        text = str(text).replace("’", "'").replace("`", "'")
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = text.lower()
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _clean(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text)).strip(" ,;.-")

    def _add(self, result, ref_type, raw_text, normalized_name, relation, confidence):
        normalized_name = self._clean(normalized_name)
        if not normalized_name:
            return
        result.references.append(LocalityReference(ref_type=ref_type, raw_text=raw_text, normalized_name=normalized_name, relation=relation, confidence=confidence))

    def _update_context_from_result(self, locality_context, result):
        """Aggiorna solo metadati descrittivi del contesto."""
        if locality_context is None or result is None:
            return
        try:
            locality_context.apply_parse_result(result)
        except Exception:
            # Compatibilità con eventuali contesti legacy o incompleti.
            cleaned = getattr(result, "cleaned_text", None)
            if cleaned:
                locality_context.normalized_locality = cleaned

    def parse(self, locality_text: str = None, locality_context=None) -> LocalityParseResultModel:
        """Parsa la località mantenendo la compatibilità con le chiamate storiche.

        Fase 5.5c: quando viene fornito ``locality_context`` il testo viene
        letto dal contesto solo se ``locality_text`` non è stato passato.
        Il risultato del parsing viene inoltre riportato nel contesto senza
        modificare le regole semantiche o il contenuto del risultato.
        """
        if locality_text is None and locality_context is not None:
            try:
                locality_text = locality_context.parsing_text()
            except Exception:
                locality_text = (
                    getattr(locality_context, "locality", None)
                    or getattr(locality_context, "search_name", None)
                    or ""
                )

        cleaned = self.normalize_text(locality_text)
        result = LocalityParseResultModel(original_text=locality_text or "", cleaned_text=cleaned)
        if not cleaned:
            result.warnings.append("Località vuota")
            self._update_context_from_result(locality_context, result)
            return result

        # Comune esplicito nel testo
        for m in re.findall(r"(?:nel comune di|in comune di|comune di) ([a-z0-9\s'\-]+)", cleaned):
            self._add(result, "municipality", str(m), m, "in", 0.98)


        # Foreste / boschi / aree forestali: sono aree, non punti.
        for m in re.findall(r"\b(foresta|bosco|selva)\s+([a-z0-9\s'\-]+)", cleaned):
            prefix, name = m
            full = f"{prefix} {name}"
            self._add(result, "forest_area", full, full, "in", 0.96)

        # Foresta ERSAF Legnoli, Foresta demaniale X, ecc.
        for m in re.findall(r"\b(foresta\s+(?:ersaf|demaniale|regionale|statale)\s+[a-z0-9\s'\-]+)", cleaned):
            full = self._clean(m)
            self._add(result, "forest_area", full, full, "in", 0.98)


        # Valli
        for m in re.findall(r"\bval\s+d[' ]\s*([a-z0-9][a-z0-9\s'\-]*)", cleaned):
            name = self._clean(m)
            if name:
                self._add(result, "valley", f"val d'{name}", f"val d'{name}", "in", 0.96)
        for m in re.findall(r"\bval\s+di\s+([a-z0-9][a-z0-9\s'\-]*)", cleaned):
            name = self._clean(m)
            if name:
                self._add(result, "valley", f"val di {name}", f"val di {name}", "in", 0.95)
        for m in re.findall(r"\bvalle\s+([a-z0-9\s'\-]+)", cleaned):
            self._add(result, "valley", str(m), f"valle {m}", "in", 0.93)
        for m in re.findall(r"\bval\s+([a-ce-z0-9][a-z0-9\s'\-]*)", cleaned):
            self._add(result, "valley", str(m), f"val {m}", "in", 0.90)

        # Passi / forcelle / selle / bocchette
        for prefix, name in re.findall(r"\b(passo|forcella|sella|bocchetta)\s+([a-z0-9\s'\-]+)", cleaned):
            self._add(result, "pass", f"{prefix} {name}", f"{prefix} {name}", "at", 0.91)

        # Rifugi/malghe/bivacchi
        for prefix, name in re.findall(r"\b(rifugio|malga|bivacco|baita)\s+([a-z0-9\s'\-]+)", cleaned):
            self._add(result, "refuge_malga", f"{prefix} {name}", f"{prefix} {name}", "at", 0.86)

        # GeoLichen 2.4 - Monti e cime non sono la stessa cosa.
        # "Monte X" indica spesso un intero rilievo/versante/massiccio,
        # non necessariamente il punto di vetta.
        for prefix, name in re.findall(r"\b(gruppo|massiccio|catena|dorsale)\s+(?:del|della|di)?\s*([a-z0-9\s'\-]+)", cleaned):
            full = self._clean(f"{prefix} {name}")
            self._add(result, "mountain_group", full, full, "area_of", 0.94)

        for prefix, name in re.findall(r"\b(monte|montagna|monte\.|mt\.)\s+([a-z0-9\s'\-]+)", cleaned):
            full = self._clean(f"{prefix} {name}".replace("monte.", "monte").replace("mt.", "monte"))
            self._add(result, "mountain_area", full, full, "area_of", 0.93)

        # Espressioni che indicano versanti/pendici di un monte: area, non cima.
        for m in re.findall(r"\b(?:versante|pendici|pendio|sotto|alle pendici|sulle pendici)\s+(?:del|della|di)?\s*(monte\s+[a-z0-9\s'\-]+)", cleaned):
            full = self._clean(m)
            self._add(result, "mountain_area", full, full, "area_of", 0.92)

        # Cima / vetta / pizzo / punta / corno: riferimento puntuale o quasi.
        for prefix, name in re.findall(r"\b(cima|vetta|pizzo|punta|corno)\s+([a-z0-9\s'\-]+)", cleaned):
            full = self._clean(f"{prefix} {name}")
            self._add(result, "summit_peak", full, full, "at", 0.91)

        # Colle può essere un rilievo basso/ampio: buffer intermedio.
        for prefix, name in re.findall(r"\b(colle|dosso|poggio)\s+([a-z0-9\s'\-]+)", cleaned):
            full = self._clean(f"{prefix} {name}")
            self._add(result, "hill", full, full, "area_of", 0.86)

        # "sotto le cime del Monte X" -> usa l'area del monte come riferimento principale.
        for m in re.findall(r"sotto le cime?(?: del| di| della)?\s+([a-z0-9\s'\-]+)", cleaned):
            name = self._clean(m)
            if name:
                if not name.startswith("monte"):
                    name = "monte " + name
                self._add(result, "mountain_area", name, name, "below", 0.89)

        # Prati, piane, alpeggi
        for prefix, name in re.findall(r"\b(prato|piana|pianoro|alpe|alpeggio)\b(?: di| del| della)?\s+([a-z0-9\s'\-]+)", cleaned):
            self._add(result, "meadow", f"{prefix} {name}", f"{prefix} {name}", "area_of", 0.82)

        # Idrografia
        for prefix, name in re.findall(r"\b(torrente|rio|fiume|lago)\s+([a-z0-9\s'\-]+)", cleaned):
            self._add(result, "hydro", f"{prefix} {name}", f"{prefix} {name}", "along", 0.80)

        # Nearby / sopra / sotto / presso ...
        for rel, name in re.findall(r"\b(nei pressi di|vicino a|presso|sopra|sotto)\s+([a-z0-9\s'\-]+)", cleaned):
            relation = {"nei pressi di": "near", "vicino a": "near", "presso": "near", "sopra": "above", "sotto": "below"}.get(rel, "near")
            self._add(result, "nearby_place", f"{rel} {name}", name, relation, 0.78)

        # Sentieri CAI
        for code in re.findall(r"\bcai\s*([0-9]+)\b", cleaned):
            self._add(result, "trail", f"CAI {code}", f"CAI {code}", "along", 0.82)

        # Sentieri tra due località
        for a, b in re.findall(r"(?:sentiero|mulattiera|traccia)\s+(?:tra|fra)\s+([a-z0-9\s'\-]+)\s+e\s+([a-z0-9\s'\-]+)", cleaned):
            self._add(result, "trail", f"sentiero tra {a} e {b}", f"sentiero tra {a} e {b}", "between", 0.84)
            self._add(result, "generic_toponym", a, a, None, 0.62)
            self._add(result, "generic_toponym", b, b, None, 0.62)

        # Tra due località generico
        for a, b in re.findall(r"(?:tra|fra)\s+([a-z0-9\s'\-]+)\s+e\s+([a-z0-9\s'\-]+)", cleaned):
            self._add(result, "generic_toponym", a, a, "between", 0.60)
            self._add(result, "generic_toponym", b, b, "between", 0.60)

        # Generic fallback
        if not result.references and cleaned:
            self._add(result, "generic_toponym", cleaned, cleaned, None, 0.45)

        # dedup per nome+tipo
        seen = set()
        deduped = []
        for ref in sorted(result.references, key=lambda r: r.confidence, reverse=True):
            key = (ref.ref_type, ref.normalized_name, ref.relation)
            if key not in seen:
                seen.add(key)
                deduped.append(ref)
        result.references = deduped
        self._update_context_from_result(locality_context, result)
        return result
