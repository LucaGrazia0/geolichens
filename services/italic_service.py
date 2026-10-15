import json
import os
import re
import time
import urllib.parse
from html import unescape

from .network_service import fetch_text
from .storage_service import profile_data_path

try:
    from .italic_index_service import ItalicIndexService
except Exception:
    ItalicIndexService = None


class ItalicService:
    """Motore ITALIC stabile per GeoLichen.

    Flusso v16:
    1. cache fresca
    2. indice locale costruito con /checklist/ + /name-usage/
    3. API ufficiali v2 usando accepted_name o taxon_id
    4. taxonpage diretta solo se l'indice fornisce un URL
    5. API match ufficiale /match/{name}
    6. fallback ecologico locale solo alla fine

    Non usa più ricerca HTML fragile via qtaxon/DuckDuckGo.
    """

    USER_AGENT = "GeoLichen/1.0"
    CACHE_TTL_SECONDS = 30 * 24 * 3600
    ENGINE_VERSION = "italic_engine_v16_clean_api_index"
    DEBUG_ITALIC_JSON = False

    API_BASE = "https://italic.units.it/api/v2"
    MATCH_ENDPOINT = API_BASE + "/match/"
    ECOLOGY_ENDPOINT = API_BASE + "/ecology-traits/"
    DESCRIPTION_ENDPOINT = API_BASE + "/description/"
    REGIONS_ENDPOINT = API_BASE + "/regions-distribution/"
    ECOREGIONS_ENDPOINT = API_BASE + "/ecoregions-distribution/"
    NAME_USAGE_ENDPOINT = API_BASE + "/name-usage/"

    LOCAL_SYNONYMS = {
        "platysma fahlunense": "Cetraria commixta",
    }

    # Seed manuale utile anche se l'indice completo non è ancora stato costruito.
    LOCAL_TAXONPAGES = {
        "cladonia botrytes": "https://italic.units.it/index.php?procedure=taxonpage&num=600",
        "sporastatia testudinea var. coracina": "https://italic.units.it/index.php?procedure=taxonpage&num=2237",
    }

    def __init__(self, cache_path=None, timeout=20):
        self.timeout = timeout
        self.cache_path = cache_path or profile_data_path("italic_cache.json")
        self.cache_path = os.path.abspath(self.cache_path)
        self._ensure_cache()
        self.index_service = ItalicIndexService() if ItalicIndexService is not None else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_profile(self, scientific_name):
        original_name = (scientific_name or "").strip()
        normalized_name = self._normalize_taxon_name(original_name)

        diag = {
            "original_name": original_name,
            "normalized_name": normalized_name,
            "candidate_names": [],
            "selected_name": None,
            "selected_taxon_id": None,
            "final_status": None,
            "final_reason": None,
            "match_attempts": [],
            "api_attempts": [],
            "taxonpage_attempts": [],
            "index_attempts": [],
        }

        if not normalized_name:
            profile = self._fallback_profile(original_name, reason="taxon mancante")
            profile["diagnostic_info"] = self._ui_diag(diag)
            self._print_debug_summary(original_name, normalized_name, None, diag, profile)
            return profile

        # 1. Cache
        cached = self._get_cache(original_name, allow_expired=False) or self._get_cache(normalized_name, allow_expired=False)
        if cached and not self._is_fallback_profile(cached):
            cached.setdefault("cache_status", "fresh")
            cached.setdefault("diagnostic_info", self._ui_diag(diag))
            self._print_debug_summary(original_name, normalized_name, cached.get("nomenclature_match"), diag, cached)
            return cached

        # 2. Indice locale: nome -> accepted_name/taxon_id/taxonpage
        profile = self._fetch_profile_from_index(original_name, normalized_name, diag)
        if self._profile_has_useful_data(profile):
            return self._finalize_profile(profile, original_name, normalized_name, diag)

        # 3. Sinonimi locali
        synonym = self.LOCAL_SYNONYMS.get(normalized_name.lower())
        if synonym:
            profile = self._fetch_profile_from_identifier(
                identifier=synonym,
                original_name=original_name,
                normalized_name=normalized_name,
                match={
                    "matched_name": normalized_name,
                    "accepted_name": synonym,
                    "taxon_id": None,
                    "status": "local_synonym",
                    "match_url": "local://LOCAL_SYNONYMS",
                },
                diag=diag,
                source_note="LOCAL_SYNONYMS",
            )
            if self._profile_has_useful_data(profile):
                return self._finalize_profile(profile, original_name, normalized_name, diag)

        # 4. API match ufficiale /match/{name}
        best_match = self.match_taxon(normalized_name, diag=diag)
        if best_match:
            accepted = best_match.get("accepted_name") or best_match.get("matched_name") or normalized_name
            taxon_id = best_match.get("taxon_id")
            diag["selected_name"] = accepted
            diag["selected_taxon_id"] = taxon_id

            identifier = taxon_id or accepted
            profile = self._fetch_profile_from_identifier(
                identifier=identifier,
                original_name=original_name,
                normalized_name=normalized_name,
                match=best_match,
                diag=diag,
                source_note="ITALIC_API_MATCH",
            )
            if self._profile_has_useful_data(profile):
                return self._finalize_profile(profile, original_name, normalized_name, diag)

            # Se il nome accettato ha una taxonpage seed, prova quella.
            profile = self._fetch_profile_from_known_taxonpage(accepted, original_name, normalized_name, best_match, diag)
            if self._profile_has_useful_data(profile):
                return self._finalize_profile(profile, original_name, normalized_name, diag)

        # 5. Taxonpage seed dal nome normalizzato
        profile = self._fetch_profile_from_known_taxonpage(normalized_name, original_name, normalized_name, best_match if "best_match" in locals() else None, diag)
        if self._profile_has_useful_data(profile):
            return self._finalize_profile(profile, original_name, normalized_name, diag)

        # 6. Cache scaduta, se disponibile
        stale = self._get_cache(original_name, allow_expired=True) or self._get_cache(normalized_name, allow_expired=True)
        if stale and not self._is_fallback_profile(stale):
            stale["cache_status"] = "expired_used_as_fallback"
            stale["diagnostic"] = "ITALIC senza dati utili; usata cache scaduta."
            stale["diagnostic_info"] = self._ui_diag(diag)
            self._print_debug_summary(original_name, normalized_name, stale.get("nomenclature_match"), diag, stale)
            return stale

        # 7. Fallback ecologico locale
        fallback = self._nomenclature_or_fallback_profile(
            original_name=original_name,
            normalized_name=normalized_name,
            match=best_match if "best_match" in locals() else None,
            diag=diag,
            reason="Indice/API/taxonpage senza dati ecologici utili",
        )
        self._print_debug_summary(original_name, normalized_name, best_match if "best_match" in locals() else None, diag, fallback)
        return fallback

    # ------------------------------------------------------------------
    # Main retrieval paths
    # ------------------------------------------------------------------
    def _finalize_profile(self, profile, original_name, normalized_name, diag):
        profile = profile or {}
        profile["cache_status"] = "fresh"
        profile["engine_version"] = self.ENGINE_VERSION
        profile["diagnostic_info"] = self._ui_diag(diag)
        self._save_cache(original_name, profile)
        if normalized_name and normalized_name != original_name:
            self._save_cache(normalized_name, profile)
        searched = profile.get("searched_name")
        if searched and searched not in {original_name, normalized_name}:
            self._save_cache(searched, profile)
        self._print_debug_summary(original_name, normalized_name, profile.get("nomenclature_match"), diag, profile)
        return profile

    def _fetch_profile_from_index(self, original_name, normalized_name, diag):
        if self.index_service is None:
            diag["index_attempts"].append({"ok": False, "method": "index_service_missing", "error": "ItalicIndexService non disponibile"})
            return None

        entry = self.index_service.lookup(original_name) or self.index_service.lookup(normalized_name)
        if not entry:
            diag["index_attempts"].append({"ok": False, "method": "local_index", "name": normalized_name, "error": "taxon non presente in data/italic_index.json"})
            return None

        diag["index_attempts"].append({
            "ok": True,
            "method": "local_index",
            "name": normalized_name,
            "accepted_name": entry.get("accepted_name"),
            "taxon_id": entry.get("taxon_id") or entry.get("related_taxon_id"),
        })

        match = {
            "matched_name": entry.get("display_name") or entry.get("scientific_name_full") or entry.get("scientific_name"),
            "accepted_name": entry.get("accepted_name") or entry.get("related_accepted_name") or entry.get("scientific_name_full") or entry.get("scientific_name"),
            "taxon_id": entry.get("taxon_id") or entry.get("related_taxon_id"),
            "status": entry.get("status") or "local_index",
            "match_url": "local://italic_index.json",
            "taxonpage_num": entry.get("taxonpage_num") or entry.get("num"),
        }

        identifier = self.index_service.preferred_api_identifier(entry)
        diag["selected_name"] = match.get("accepted_name")
        diag["selected_taxon_id"] = match.get("taxon_id")

        if identifier not in [None, ""]:
            profile = self._fetch_profile_from_identifier(
                identifier=identifier,
                original_name=original_name,
                normalized_name=normalized_name,
                match=match,
                diag=diag,
                source_note="LOCAL_INDEX_API",
            )
            if self._profile_has_useful_data(profile):
                profile["diagnostic"] = "local_index_api_profile"
                profile["source"] = "ITALIC 8.0 API + local index"
                return profile

        # Fallback alla taxonpage se l'indice la contiene
        url = self.index_service.taxonpage_url(entry)
        if url:
            return self._fetch_taxonpage_profile(url, match.get("accepted_name") or normalized_name, original_name, normalized_name, match, diag, method="local_index_taxonpage")

        return None

    def _fetch_profile_from_identifier(self, identifier, original_name, normalized_name, match, diag, source_note="API"):
        """Legge API v2 con accepted_name o taxon_id."""
        if identifier in [None, ""]:
            return None

        ident = str(identifier)
        ecology = self._get_api_data(self.ECOLOGY_ENDPOINT, ident, diag=diag, label="ecology-traits")
        description = self._get_api_data(self.DESCRIPTION_ENDPOINT, ident, diag=diag, label="description")
        regions = self._get_api_data(self.REGIONS_ENDPOINT, ident, diag=diag, label="regions-distribution")
        ecoregions = self._get_api_data(self.ECOREGIONS_ENDPOINT, ident, diag=diag, label="ecoregions-distribution")

        if self._api_says_not_present(ecology):
            ecology = None
        if self._api_says_not_present(description):
            description = None
        if self._api_says_not_present(regions):
            regions = None
        if self._api_says_not_present(ecoregions):
            ecoregions = None

        if not any([ecology, description, regions, ecoregions]):
            return None

        accepted = (match or {}).get("accepted_name") or self._extract_api_name(ecology) or ident

        profile = {
            "scientific_name": accepted,
            "source": "ITALIC 8.0 API",
            "taxon_url": "https://italic.units.it/?procedure=qtaxon&taxon=" + urllib.parse.quote(str(accepted)),
            "substrata": [],
            "habitat": [],
            "rock_type": None,
            "tree_type": None,
            "growth_form": self._extract_ecology_value(ecology, "growth_form"),
            "photobiont": self._extract_ecology_value(ecology, "photobiont"),
            "reproductive_strategy": self._extract_ecology_value(ecology, "reproductive_strategy"),
            "ecology_traits": self._format_ecology_traits(ecology),
            "regions_distribution": self._format_distribution(regions),
            "ecoregions_distribution": self._format_distribution(ecoregions),
            "notes": self._description_notes(description),
            "raw_substrata": self._value_to_text(self._extract_ecology_value(ecology, "substrata")),
            "ecology_raw": ecology or {},
            "description_raw": description or {},
            "regions_raw": regions or {},
            "ecoregions_raw": ecoregions or {},
            "diagnostic": "api_v2_parsed",
            "ecology_source_note": source_note,
        }

        useful_text = " ".join([
            profile.get("raw_substrata") or "",
            profile.get("ecology_traits") or "",
            profile.get("notes") or "",
            profile.get("regions_distribution") or "",
            profile.get("ecoregions_distribution") or "",
        ])

        profile["substrata"] = self._normalize_substrata(profile.get("raw_substrata"), useful_text)
        profile["rock_type"] = self._infer_rock_type_from_api(ecology, useful_text)
        profile["tree_type"] = self._infer_tree_type(useful_text)
        profile["habitat"] = self._infer_habitat(useful_text)

        self._attach_api_ecology_classes(profile, ecology)

        profile.update(self._match_fields(match, original_name, normalized_name, accepted, (match or {}).get("taxon_id")))
        return profile

    def _fetch_profile_from_known_taxonpage(self, name, original_name, normalized_name, match, diag):
        key = self._normalize_taxon_name(name).lower()
        url = self.LOCAL_TAXONPAGES.get(key)
        if not url:
            base = self._base_binomial(key)
            url = self.LOCAL_TAXONPAGES.get(base)
        if not url:
            return None
        return self._fetch_taxonpage_profile(url, name, original_name, normalized_name, match, diag, method="local_taxonpage_seed")

    def _fetch_taxonpage_profile(self, url, query_name, original_name, normalized_name, match, diag, method="taxonpage"):
        attempt = {"method": method, "url": url, "ok": False, "error": None}
        try:
            html = self._fetch_text(url)
            profile = self._parse_taxonpage(query_name, url, html)
            profile.update(self._match_fields(match, original_name, normalized_name, query_name, (match or {}).get("taxon_id") if match else None))
            profile["source"] = "ITALIC 8.0 taxonpage"
            profile["diagnostic"] = "taxonpage_parsed_css_scales"
            attempt["ok"] = self._profile_has_useful_data(profile)
            if diag is not None:
                diag["taxonpage_attempts"].append(attempt)
                if attempt["ok"]:
                    diag["final_status"] = "ok"
                    diag["final_reason"] = f"taxonpage letta ({method})"
            return profile
        except Exception as exc:
            attempt["error"] = str(exc)
            if diag is not None:
                diag["taxonpage_attempts"].append(attempt)
            return None

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------
    def match_taxon(self, taxon, diag=None):
        taxon = self._normalize_taxon_name(taxon)
        if not taxon:
            return None

        local = self.LOCAL_SYNONYMS.get(taxon.lower().strip())
        if local:
            result = {
                "input_name": taxon,
                "matched_name": taxon,
                "status": "synonym_local_fallback",
                "accepted_name": local,
                "name_score": 100,
                "auth_score": None,
                "taxon_id": None,
                "other_matches": [],
                "match_url": "local://LOCAL_SYNONYMS",
            }
            if diag is not None:
                diag["match_attempts"].append({"method": "LOCAL", "url": "local://LOCAL_SYNONYMS", "ok": True, "candidate_name": taxon})
            return result

        for candidate in self._taxon_match_candidates(taxon):
            encoded = urllib.parse.quote(candidate, safe="")
            urls = [
                self.MATCH_ENDPOINT + encoded,
                self.MATCH_ENDPOINT + "?name=" + encoded,  # legacy fallback
            ]
            for url in urls:
                attempt = {"method": "GET", "url": url, "ok": False, "error": None, "candidate_name": candidate}
                try:
                    data = self._fetch_json(url)
                    match = self._extract_match_from_response(data)
                    if match:
                        result = self._match_result(data, match, candidate, url)
                        attempt["ok"] = True
                        attempt["matched_name"] = result.get("matched_name")
                        attempt["accepted_name"] = result.get("accepted_name")
                        attempt["taxon_id"] = result.get("taxon_id")
                        if diag is not None:
                            diag["match_attempts"].append(attempt)
                        return result
                    attempt["error"] = "JSON valido ma campo match assente"
                except Exception as exc:
                    attempt["error"] = str(exc)
                if diag is not None:
                    diag["match_attempts"].append(attempt)
        return None

    def _get_api_data(self, endpoint, identifier, diag=None, label="api"):
        if identifier in [None, ""]:
            return None
        encoded = urllib.parse.quote(str(identifier), safe="")
        url = endpoint + encoded
        attempt = {"method": label, "url": url, "ok": False, "error": None}
        try:
            data = self._fetch_json(url)
            self._debug_print_json(label + " RAW " + str(identifier), data)
            parsed = self._extract_data_from_api_response(data)
            self._debug_print_json(label + " PARSED " + str(identifier), parsed)
            attempt["ok"] = parsed is not None
            if parsed is None:
                attempt["error"] = "JSON valido ma dati non trovati"
            if diag is not None:
                diag["api_attempts"].append(attempt)
            return parsed
        except Exception as exc:
            attempt["error"] = str(exc)
            if diag is not None:
                diag["api_attempts"].append(attempt)
            return None

    def _fetch_json(self, url):
        raw = self._fetch_text(url)
        return json.loads(raw)

    def _fetch_text(self, url):
        return fetch_text(
            url, timeout=self.timeout,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json,text/html,*/*",
            },
        )

    def _extract_data_from_api_response(self, data):
        if data is None:
            return None
        if isinstance(data, dict):
            if isinstance(data.get("data"), dict):
                return data.get("data")
            if isinstance(data.get("data"), list):
                return data.get("data")[0] if data.get("data") else None
            useful = {k: v for k, v in data.items() if k not in ["input_name", "input", "message", "messages"]}
            return useful if useful else None
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    if isinstance(item.get("data"), dict):
                        return item.get("data")
                    useful = {k: v for k, v in item.items() if k not in ["input_name", "input", "message", "messages"]}
                    if useful:
                        return useful
        return None

    def _extract_match_from_response(self, data):
        if not isinstance(data, dict):
            return None
        match = data.get("match")
        if isinstance(match, list):
            match = match[0] if match else None
        if isinstance(match, dict):
            return match
        if any(k in data for k in ["accepted_name", "matched_name", "taxon_id"]):
            return data
        return None

    def _match_result(self, data, match, fallback_name, url):
        return {
            "input_name": data.get("input_name", fallback_name) if isinstance(data, dict) else fallback_name,
            "matched_name": match.get("matched_name") or fallback_name,
            "status": match.get("status"),
            "accepted_name": match.get("accepted_name") or match.get("matched_name") or fallback_name,
            "name_score": match.get("name_score"),
            "auth_score": match.get("auth_score"),
            "taxon_id": match.get("taxon_id"),
            "other_matches": data.get("other_matches", []) if isinstance(data, dict) else [],
            "match_url": url,
        }

    def _match_fields(self, match, original_name, normalized_name, query_name, taxon_id):
        fields = {
            "original_name": original_name,
            "normalized_name": normalized_name,
            "queried_name": original_name,
            "searched_name": query_name,
            "taxon_id": taxon_id,
            "nomenclature_match": match,
        }
        if match:
            fields.update({
                "matched_name": match.get("matched_name"),
                "accepted_name": match.get("accepted_name"),
                "nomenclature_status": match.get("status"),
                "name_score": match.get("name_score"),
                "auth_score": match.get("auth_score"),
                "taxon_id": match.get("taxon_id") or taxon_id,
                "match_url": match.get("match_url"),
            })
        return fields

    # ------------------------------------------------------------------
    # Ecology parsing
    # ------------------------------------------------------------------
    def _attach_api_ecology_classes(self, profile, ecology):
        ecology = ecology or {}
        scale_fields = [
            ("ph_of_the_substrata", 5),
            ("solar_irradiation", 5),
            ("aridity", 5),
            ("eutrophication", 5),
            ("poleotolerance", 3),
        ]
        for key, _max_class in scale_fields:
            mn = self._to_int(self._extract_ecology_value(ecology, key + "_min"))
            mx = self._to_int(self._extract_ecology_value(ecology, key + "_max"))
            if mn is not None:
                profile[key + "_min"] = mn
            if mx is not None:
                profile[key + "_max"] = mx

        cmin = self._to_int(self._extract_ecology_value(ecology, "altitudinal_distribution_min"))
        cmax = self._to_int(self._extract_ecology_value(ecology, "altitudinal_distribution_max"))
        if cmin is not None or cmax is not None:
            profile["italic_altitude_class_min"] = cmin
            profile["italic_altitude_class_max"] = cmax
            mmin, mmax = self._italic_altitude_classes_to_meters(cmin, cmax)
            profile["altitudinal_distribution_min"] = mmin
            profile["altitudinal_distribution_max"] = mmax
            profile["altitudinal_distribution_source"] = "ITALIC_API_CLASS_CONVERTED"

    def _parse_taxonpage(self, scientific_name, taxon_url, html):
        clean_text = self._html_to_clean_text(html)
        lower_text = clean_text.lower()
        accepted = self._extract_accepted_name(clean_text) or self._extract_title(html) or scientific_name

        growth_form = self._extract_bold_value_from_html(html, "Growth form")
        substrata_text = self._extract_bold_value_from_html(html, "Substrata")
        photobiont = self._extract_bold_value_from_html(html, "Photobiont")
        reproductive_strategy = self._extract_bold_value_from_html(html, "Reproductive strategy")
        note = self._extract_html_note(html) or self._extract_section(clean_text, ["Note:", "Notes:", "Ecology:", "Ecological notes:"])
        description = self._extract_section(clean_text, ["Description"])

        useful_text = " ".join(x for x in [substrata_text, growth_form, photobiont, reproductive_strategy, note, description] if x)
        if not useful_text:
            useful_text = clean_text[:3500]

        profile = {
            "scientific_name": accepted,
            "source": "ITALIC 8.0 taxonpage",
            "taxon_url": taxon_url,
            "substrata": self._normalize_substrata(substrata_text, useful_text),
            "habitat": self._infer_habitat(useful_text or lower_text),
            "rock_type": self._infer_rock_type(useful_text or lower_text),
            "tree_type": self._infer_tree_type(useful_text or lower_text),
            "growth_form": growth_form,
            "photobiont": photobiont,
            "reproductive_strategy": reproductive_strategy,
            "ecology_traits": self._format_taxonpage_traits(growth_form, substrata_text, photobiont, reproductive_strategy),
            "regions_distribution": "",
            "ecoregions_distribution": self._extract_commonness_rarity(clean_text),
            "notes": note or description or useful_text[:1000],
            "raw_substrata": substrata_text,
            "diagnostic": "taxonpage_parsed_css_scales",
        }
        self._attach_taxonpage_ecology_scales(profile, html, clean_text)
        return profile

    def _extract_bold_value_from_html(self, html, label):
        if not html:
            return ""
        pat = r"<b>\s*" + re.escape(label) + r"\s*:?\s*</b>\s*(?P<val>.*?)(?:</h[1-6]>|<br\s*/?>|</div>|</p>)"
        m = re.search(pat, html, flags=re.I | re.S)
        return self._clean_text(m.group("val")) if m else ""

    def _extract_taxonpage_scale_range(self, html, label, max_class=6):
        html = html or ""
        label_norm = re.sub(r"[^a-z0-9]+", "", (label or "").lower())

        # Cerca blocco intorno alla label.
        low = html.lower()
        pos = low.find((label or "").lower())
        if pos == -1:
            return None, None
        block = html[pos:pos + 2500]

        # Limita al primo eco-grid successivo quando possibile.
        td_matches = re.findall(r"<td\b([^>]*)>\s*([0-9]+)\s*</td>", block, flags=re.I | re.S)
        vals = []
        for attrs, value in td_matches:
            attrs_low = attrs.lower()
            if any(cls in attrs_low for cls in ["only-cell", "only-cell-2", "left-cell", "left-cell-2", "right-cell", "right-cell-2"]):
                try:
                    x = int(value)
                    if 0 <= x <= max_class:
                        vals.append(x)
                except Exception:
                    pass
        if vals:
            vals = sorted(set(vals))
            return vals[0], vals[-1]
        return None, None

    def _attach_taxonpage_ecology_scales(self, profile, html, clean_text):
        specs = [
            ("ph_of_the_substrata", "pH of the substrata", 5),
            ("solar_irradiation", "Solar irradiation", 5),
            ("aridity", "Aridity", 5),
            ("eutrophication", "Eutrophication", 5),
            ("poleotolerance", "Poleotolerance", 3),
            ("altitudinal_distribution", "Altitudinal distribution", 6),
        ]
        extras = []
        for key, label, max_class in specs:
            mn, mx = self._extract_taxonpage_scale_range(html, label, max_class=max_class)
            if key == "altitudinal_distribution" and mn is None and mx is None:
                mn, mx = self._extract_altitude_classes_from_rarity_belts(clean_text)
                source = "ITALIC_TAXONPAGE_RARITY_BELTS"
            else:
                source = "ITALIC_TAXONPAGE_CSS_SCALE"

            if mn is None and mx is None:
                continue

            if key == "altitudinal_distribution":
                profile["italic_altitude_class_min"] = mn
                profile["italic_altitude_class_max"] = mx
                mmin, mmax = self._italic_altitude_classes_to_meters(mn, mx)
                profile["altitudinal_distribution_min"] = mmin
                profile["altitudinal_distribution_max"] = mmax
                profile["altitudinal_distribution_source"] = source
                extras.extend([
                    f"italic_altitude_class_min: {mn}",
                    f"italic_altitude_class_max: {mx}",
                    f"altitudinal_distribution_min: {mmin}",
                    f"altitudinal_distribution_max: {mmax}",
                ])
            else:
                profile[key + "_min"] = mn
                profile[key + "_max"] = mx
                extras.extend([f"{key}_min: {mn}", f"{key}_max: {mx}"])

        if extras:
            profile["ecology_traits"] = ((profile.get("ecology_traits") + "; ") if profile.get("ecology_traits") else "") + "; ".join(extras)

    def _extract_altitude_classes_from_rarity_belts(self, clean_text):
        txt = clean_text or ""
        mapping = [
            ("Padanian area", 1), ("Dry mediterranean belt", 1), ("Humid mediterranean belt", 1),
            ("Submediterranean belt", 2), ("Dry submediterranean belt", 2), ("Humid submediterranean belt", 2),
            ("Montane belt", 3), ("Subalpine belt", 4), ("Oromediterranean belt", 4), ("Alpine belt", 5),
        ]
        vals = []
        for label, cls in mapping:
            m = re.search(re.escape(label) + r"\s*:\s*([^.;\n\r<]+)", txt, flags=re.I)
            if not m:
                continue
            val = m.group(1).strip().lower()
            if val and "absent" not in val and val not in {"null", "none", "-"}:
                vals.append(cls)
        if vals:
            vals = sorted(set(vals))
            return vals[0], vals[-1]
        return None, None

    def _italic_altitude_classes_to_meters(self, cmin, cmax):
        bands = {1: (0, 600), 2: (400, 1000), 3: (800, 1700), 4: (1600, 2400), 5: (2200, 3000), 6: (2800, 4000)}
        lo = self._to_int(cmin)
        hi = self._to_int(cmax)
        if lo is None and hi is None:
            return None, None
        if lo is None:
            lo = hi
        if hi is None:
            hi = lo
        if lo > hi:
            lo, hi = hi, lo
        if lo not in bands or hi not in bands:
            return None, None
        return bands[lo][0], bands[hi][1]

    # ------------------------------------------------------------------
    # Formatting / inference
    # ------------------------------------------------------------------
    def _api_says_not_present(self, data):
        text = self._value_to_text(data).lower()
        return any(x in text for x in ["not present", "not present in the database", "is not present the database", "not found"])

    def _extract_api_name(self, data):
        if isinstance(data, dict):
            return data.get("scientific_name") or data.get("accepted_name")
        return None

    def _format_ecology_traits(self, data):
        if not isinstance(data, dict):
            return self._value_to_text(data)
        parts = []
        for k, v in data.items():
            if v not in [None, "", [], {}]:
                parts.append(f"{k}: {self._value_to_text(v)}")
        return "; ".join(parts)

    def _format_taxonpage_traits(self, growth_form, substrata, photobiont, reproductive):
        parts = []
        if growth_form:
            parts.append("growth_form: " + growth_form)
        if substrata:
            parts.append("substrata: " + substrata)
        if photobiont:
            parts.append("photobiont: " + photobiont)
        if reproductive:
            parts.append("reproductive_strategy: " + reproductive)
        return "; ".join(parts)

    def _format_distribution(self, data):
        if not isinstance(data, dict):
            return self._value_to_text(data)
        parts = []
        for k, v in data.items():
            if k in ["scientific_name", "data_about", "warnings"]:
                continue
            if v in [None, "", [], {}] or str(v).lower() in ["0", "absent", "false"]:
                continue
            parts.append(f"{k}: {self._value_to_text(v)}")
        return "; ".join(parts)

    def _description_notes(self, data):
        if not isinstance(data, dict):
            return self._value_to_text(data)
        return self._value_to_text(data.get("notes") or data.get("description") or "")

    def _extract_ecology_value(self, data, key):
        if not isinstance(data, dict):
            return ""
        if key in data:
            return data.get(key)
        kn = key.lower().replace("_", "").replace("-", "")
        for k, v in data.items():
            if str(k).lower().replace("_", "").replace("-", "") == kn:
                return v
        return ""

    def _normalize_substrata(self, substrata_text, note_text):
        txt = f"{substrata_text or ''} {note_text or ''}".lower()
        values = []
        if any(k in txt for k in ["bark", "epiph", "tronchi", "corteccia", "tree", "trees", "forophy", "phorophy", "basi di tronchi"]):
            values.append("epifita")
        if any(k in txt for k in ["rocks", "rock", "sax", "rocc", "walls", "muri", "stone", "stones", "siliceous", "calcareous"]):
            values.append("saxicolo")
        if any(k in txt for k in ["soil", "terr", "suolo", "ground", "earth"]):
            values.append("terricolo")
        if any(k in txt for k in ["moss", "mosses", "muschi"]):
            values.append("muscicolo")
        if any(k in txt for k in ["lign", "wood", "legno", "dead wood", "lignum", "stumps", "fallen trunks"]):
            values.append("lignicolo")
        return list(dict.fromkeys(values))

    def _infer_rock_type_from_api(self, ecology_data, text):
        ph_min = self._to_int(self._extract_ecology_value(ecology_data, "ph_of_the_substrata_min"))
        ph_max = self._to_int(self._extract_ecology_value(ecology_data, "ph_of_the_substrata_max"))
        if ph_min is not None or ph_max is not None:
            lo = ph_min if ph_min is not None else ph_max
            hi = ph_max if ph_max is not None else ph_min
            if hi <= 2:
                return "siliceo"
            if lo >= 4:
                return "calcareo"
            if lo <= 2 and hi >= 4:
                return "misto"
        return self._infer_rock_type(text)

    def _infer_rock_type(self, text):
        txt = (text or "").lower()
        calc = any(k in txt for k in ["calcicol", "calcareous", "limestone", "dolomit", "carbonat", "basic substrata", "base-rich", "pure limestone"])
        sil = any(k in txt for k in ["silicicol", "siliceous", "acid substrata", "quartzite", "silic", "acid rocks", "very acid substrata"])
        if calc and sil:
            return "misto"
        if calc:
            return "calcareo"
        if sil:
            return "siliceo"
        if any(k in txt for k in ["wide range of substrata", "various substrata", "calcareous or siliceous"]):
            return "misto"
        return None

    def _infer_tree_type(self, text):
        txt = (text or "").lower()
        for tree in ["fagus", "quercus", "sambucus", "juglans", "abies", "picea", "larix", "pinus", "betula", "alnus", "fraxinus", "acer"]:
            if tree in txt:
                return tree
        if any(k in txt for k in ["conifer", "coniferous", "stumps", "fallen trunks"]):
            return "conifere"
        if any(k in txt for k in ["deciduous", "broadleaved"]):
            return "latifoglie"
        return None

    def _infer_habitat(self, text):
        txt = (text or "").lower()
        habitats = []
        if any(k in txt for k in ["alpine", "nival", "subalpine", "treeline", "high mountain", "altitudinal", "boreal-montane"]):
            habitats.append("alpino")
        if any(k in txt for k in ["rock", "rocks", "cliff", "sax", "rupicol", "siliceous", "calcareous"]):
            habitats.append("rupicolo")
        if any(k in txt for k in ["forest", "wood", "bosco", "forests", "woodland", "stumps", "fallen trunks"]):
            habitats.append("bosco")
        if any(k in txt for k in ["open habitats", "open situations", "aperto", "grassland", "prato"]):
            habitats.append("aperto")
        if any(k in txt for k in ["humid", "wet", "umid", "moist"]):
            habitats.append("umido")
        if any(k in txt for k in ["dry", "arid", "secco", "xeric"]):
            habitats.append("secco")
        return list(dict.fromkeys(habitats))

    # ------------------------------------------------------------------
    # HTML helpers
    # ------------------------------------------------------------------
    def _html_to_clean_text(self, html):
        if not html:
            return ""
        html = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.I | re.S)
        html = re.sub(r"<style.*?>.*?</style>", " ", html, flags=re.I | re.S)
        html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", html)
        text = unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    def _clean_text(self, text):
        text = re.sub(r"<[^>]+>", " ", text or "")
        text = unescape(text)
        return re.sub(r"\s+", " ", text).strip(" ;,.")

    def _extract_title(self, html):
        m = re.search(r"<h3>\s*(.*?)\s*</h3>", html or "", flags=re.I | re.S)
        if m:
            return self._clean_text(m.group(1))
        m = re.search(r"<title>\s*(.*?)\s*</title>", html or "", flags=re.I | re.S)
        return self._clean_text(m.group(1)) if m else None

    def _extract_accepted_name(self, text):
        patterns = [
            r"Accepted name\s*:?\s*([^;|]+?)(?:\s{2,}| Taxon | Description | Ecology | Substrata |$)",
            r"Taxon\s*:?\s*([^;|]+?)(?:\s{2,}| Description | Ecology | Substrata |$)",
        ]
        for pat in patterns:
            m = re.search(pat, text or "", flags=re.I)
            if m:
                val = self._clean_text(m.group(1))
                if val and len(val) < 160:
                    return val
        return None

    def _extract_html_note(self, html):
        m = re.search(r"<b>\s*Note\s*:?\s*</b>\s*(.*?)</h6>", html or "", flags=re.I | re.S)
        return self._clean_text(m.group(1)) if m else ""

    def _extract_section(self, text, labels, max_chars=1200):
        if not text:
            return ""
        all_labels = ["Substrata:", "Substrate:", "Ecology and traits", "Ecology:", "Ecological notes:", "Note:", "Notes:", "Regions distribution", "Ecoregions distribution", "Distribution", "Description", "Bibliography"]
        low = text.lower()
        for label in labels:
            start = low.find(label.lower())
            if start == -1:
                continue
            content_start = start + len(label)
            next_pos = []
            for other in all_labels:
                pos = low.find(other.lower(), content_start + 5)
                if pos != -1:
                    next_pos.append(pos)
            end = min(next_pos) if next_pos else min(len(text), content_start + max_chars)
            return self._clean_text(text[content_start:end])[:max_chars]
        return ""

    def _extract_commonness_rarity(self, clean_text):
        labels = ["Alpine belt", "Subalpine belt", "Oromediterranean belt", "Montane belt", "Submediterranean belt", "Padanian area", "Humid submediterranean belt", "Humid mediterranean belt", "Dry mediterranean belt"]
        parts = []
        for label in labels:
            m = re.search(re.escape(label) + r"\s*:\s*([^.;\n\r]+)", clean_text or "", flags=re.I)
            if m:
                parts.append(f"{label}: {m.group(1).strip()}")
        return "; ".join(parts)

    # ------------------------------------------------------------------
    # Name / fallback
    # ------------------------------------------------------------------
    def _normalize_taxon_name(self, taxon):
        taxon = (taxon or "").strip()
        if not taxon:
            return ""
        taxon = re.sub(r"\s+", " ", taxon)
        taxon = re.sub(r"\s*\([^)]*\)", " ", taxon).strip()
        taxon = re.sub(r"\b(et\s+auct\.|auct\.|p\.p\.|s\.l\.|s\.str\.)\b", " ", taxon, flags=re.I)
        taxon = re.sub(r"\s+", " ", taxon).strip(" ,;.")
        tokens = taxon.split()
        if len(tokens) < 2:
            return taxon
        for i, token in enumerate(tokens[2:], start=2):
            marker = token.lower().rstrip(".")
            if marker in {"subsp", "ssp", "var", "f"} and i + 1 < len(tokens):
                return " ".join([tokens[0], tokens[1], marker + ".", tokens[i + 1]]).strip()
        return " ".join(tokens[:2]).strip()

    def _base_binomial(self, taxon):
        tokens = (taxon or "").split()
        return " ".join(tokens[:2]) if len(tokens) >= 2 else (taxon or "")

    def _taxon_match_candidates(self, taxon):
        normalized = self._normalize_taxon_name(taxon)
        candidates = []
        if normalized:
            candidates.append(normalized)
        base = self._base_binomial(normalized)
        if base and base not in candidates:
            candidates.append(base)
        return candidates

    GENUS_ECOLOGY_FALLBACK = {
        "cladonia": {
            "substrata": ["terricolo", "muscicolo"],
            "habitat": ["aperto"],
            "rock_type": None,
            "tree_type": None,
            "growth_form": "fruticose/squamulose",
            "notes": "Ecologia stimata da fallback di genere: Cladonia è spesso terricola o muscicola in ambienti aperti. Confidenza bassa.",
        },
        "rhizocarpon": {"substrata": ["saxicolo"], "habitat": ["alpino", "rupicolo", "aperto", "secco"], "rock_type": "siliceo", "tree_type": None, "growth_form": "crustose", "notes": "Fallback di genere: Rhizocarpon saxicolo siliceo montano/alpino. Confidenza bassa."},
        "sporastatia": {"substrata": ["saxicolo"], "habitat": ["alpino", "rupicolo", "secco"], "rock_type": "siliceo", "tree_type": None, "growth_form": "crustose", "notes": "Fallback di genere: Sporastatia saxicola silicea di ambienti alpini/esposti. Confidenza bassa."},
        "bryoria": {"substrata": ["epifita"], "habitat": ["bosco"], "rock_type": None, "tree_type": "conifere", "growth_form": "fruticose", "notes": "Fallback di genere: Bryoria epifita forestale, spesso su conifere. Confidenza bassa."},
        "usnea": {"substrata": ["epifita"], "habitat": ["bosco"], "rock_type": None, "tree_type": "conifere/latifoglie", "growth_form": "fruticose", "notes": "Fallback di genere: Usnea epifita forestale. Confidenza bassa."},
    }

    def _fallback_ecology_for_name(self, name):
        clean = self._normalize_taxon_name(name or "").lower().strip()
        genus = clean.split()[0] if clean else ""
        data = self.GENUS_ECOLOGY_FALLBACK.get(genus)
        if not data:
            return None
        out = dict(data)
        out["ecology_source"] = "fallback_genus"
        out["ecology_confidence"] = "bassa"
        out["warnings"] = "Ecologia stimata da fallback locale perché ITALIC non espone dati ecologici per questo taxon."
        return out

    def _nomenclature_or_fallback_profile(self, original_name, normalized_name, match, diag, reason):
        accepted = (match or {}).get("accepted_name") or normalized_name or original_name
        fallback = self._fallback_ecology_for_name(accepted) or self._fallback_ecology_for_name(original_name)
        if fallback:
            profile = self._empty_profile(accepted, source="ITALIC 8.0 API + fallback ecologico locale")
            profile.update(self._match_fields(match, original_name, normalized_name, accepted, (match or {}).get("taxon_id") if match else None))
            profile.update({
                "substrata": fallback.get("substrata") or [],
                "habitat": fallback.get("habitat") or [],
                "rock_type": fallback.get("rock_type"),
                "tree_type": fallback.get("tree_type"),
                "growth_form": fallback.get("growth_form"),
                "ecology_source": fallback.get("ecology_source"),
                "ecology_confidence": fallback.get("ecology_confidence"),
                "warnings": fallback.get("warnings"),
                "notes": fallback.get("notes") or fallback.get("warnings"),
                "raw_substrata": ", ".join(fallback.get("substrata") or []),
                "ecology_traits": "fallback ecologico locale; substrata: " + (", ".join(fallback.get("substrata") or []) or "-") + "; habitat: " + (", ".join(fallback.get("habitat") or []) or "-") + "; confidenza: bassa",
                "diagnostic": fallback.get("ecology_source") or "fallback_ecology",
                "diagnostic_info": self._ui_diag(diag),
                "cache_status": "not_cached_fallback_ecology",
                "engine_version": self.ENGINE_VERSION,
            })
            diag["final_status"] = "partial"
            diag["final_reason"] = reason
            return profile

        profile = self._empty_profile(accepted, source="ITALIC 8.0 API (solo nomenclatura)")
        profile.update(self._match_fields(match, original_name, normalized_name, accepted, (match or {}).get("taxon_id") if match else None))
        profile["notes"] = "Match nomenclaturale riuscito, ma ITALIC non espone dati ecologici. Motivo: " + str(reason)
        profile["diagnostic"] = "nomenclature_only_no_ecology"
        profile["diagnostic_info"] = self._ui_diag(diag)
        profile["cache_status"] = "not_cached_partial"
        profile["engine_version"] = self.ENGINE_VERSION
        diag["final_status"] = "partial"
        diag["final_reason"] = reason
        return profile

    # ------------------------------------------------------------------
    # Cache / utility
    # ------------------------------------------------------------------
    def _ensure_cache(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        if not os.path.exists(self.cache_path):
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def _read_cache(self):
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _get_cache(self, scientific_name, allow_expired=False):
        data = self._read_cache()
        entry = data.get(scientific_name)
        if not entry:
            return None
        profile = entry.get("profile") if isinstance(entry, dict) and "profile" in entry else entry
        timestamp = float(entry.get("timestamp", 0)) if isinstance(entry, dict) else 0
        if not isinstance(profile, dict):
            return None
        if profile.get("engine_version") != self.ENGINE_VERSION:
            return None
        age = time.time() - timestamp if timestamp else 0
        if allow_expired or age <= self.CACHE_TTL_SECONDS:
            return profile
        return None

    def _save_cache(self, scientific_name, profile):
        if not scientific_name or self._is_fallback_profile(profile):
            return
        data = self._read_cache()
        profile["engine_version"] = self.ENGINE_VERSION
        data[scientific_name] = {"timestamp": time.time(), "profile": profile}
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _is_fallback_profile(self, profile):
        if not isinstance(profile, dict):
            return False
        return "fallback" in str(profile.get("source", "")).lower() or "fallback" in str(profile.get("diagnostic", "")).lower()

    def _profile_has_useful_data(self, profile):
        if not isinstance(profile, dict):
            return False
        combined = self._value_to_text({
            "ecology_traits": profile.get("ecology_traits"),
            "notes": profile.get("notes"),
            "raw_substrata": profile.get("raw_substrata"),
            "warnings": profile.get("warnings"),
        }).lower()
        warning_only = ("not present" in combined or "not present the database" in combined) and not any([
            profile.get("substrata"), profile.get("rock_type"), profile.get("tree_type"),
            profile.get("regions_distribution"), profile.get("ecoregions_distribution"),
            profile.get("italic_altitude_class_min"), profile.get("altitudinal_distribution_min"),
        ])
        if warning_only:
            return False
        return bool(profile.get("substrata") or profile.get("rock_type") or profile.get("tree_type") or profile.get("ecology_traits") or profile.get("notes") or profile.get("regions_distribution") or profile.get("ecoregions_distribution") or profile.get("italic_altitude_class_min") is not None)

    def _empty_profile(self, scientific_name, source="ITALIC 8.0"):
        return {
            "scientific_name": scientific_name,
            "queried_name": scientific_name,
            "source": source,
            "taxon_url": None,
            "substrata": [],
            "habitat": [],
            "rock_type": None,
            "tree_type": None,
            "ecology_traits": "",
            "regions_distribution": "",
            "ecoregions_distribution": "",
            "notes": "",
            "raw_substrata": "",
            "diagnostic": "",
        }

    def _value_to_text(self, value):
        if value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(self._value_to_text(v) for v in value if v not in [None, ""])
        if isinstance(value, dict):
            return "; ".join(f"{k}: {self._value_to_text(v)}" for k, v in value.items() if v not in [None, "", [], {}])
        return str(value)

    def _to_int(self, value):
        try:
            if value in [None, "", [], {}]:
                return None
            return int(round(float(str(value).replace(",", "."))))
        except Exception:
            return None

    def _debug_print_json(self, label, payload):
        if not getattr(self, "DEBUG_ITALIC_JSON", False):
            return
        try:
            print("\n===== ITALIC JSON DEBUG:", label, "=====")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            print("===== END ITALIC JSON DEBUG =====\n")
        except Exception:
            pass

    def _ui_diag(self, diag):
        diag = diag or {}
        ok_index = [a for a in diag.get("index_attempts", []) if a.get("ok")]
        ok_match = [a for a in diag.get("match_attempts", []) if a.get("ok")]
        ok_api = [a for a in diag.get("api_attempts", []) if a.get("ok")]
        ok_taxonpage = [a for a in diag.get("taxonpage_attempts", []) if a.get("ok")]
        return {
            "original_name": diag.get("original_name"),
            "normalized_name": diag.get("normalized_name"),
            "candidate_names": diag.get("candidate_names", []),
            "selected_name": diag.get("selected_name"),
            "selected_taxon_id": diag.get("selected_taxon_id"),
            "final_status": diag.get("final_status"),
            "final_reason": diag.get("final_reason"),
            "index_ok": bool(ok_index),
            "match_ok": bool(ok_match),
            "api_ok": bool(ok_api),
            "taxonpage_ok": bool(ok_taxonpage),
        }

    def _print_debug_summary(self, original_name, normalized_name, match, diag, profile=None):
        try:
            print("\n===== ITALIC DEBUG =====")
            print("ENGINE_VERSION:", self.ENGINE_VERSION)
            print("INPUT:", original_name)
            print("NORMALIZED:", normalized_name)
            if self.index_service is not None:
                print("INDEX_PATH:", getattr(self.index_service, "index_path", None))
            print("INDEX_ATTEMPTS:", len((diag or {}).get("index_attempts") or []))
            for attempt in ((diag or {}).get("index_attempts") or [])[:5]:
                print(" - INDEX", "OK" if attempt.get("ok") else "NO", attempt.get("method"), attempt.get("accepted_name") or attempt.get("name"), attempt.get("error") or "")
            if match:
                print("MATCHED:", match.get("matched_name"))
                print("ACCEPTED:", match.get("accepted_name"))
                print("STATUS:", match.get("status"))
                print("TAXON_ID:", match.get("taxon_id"))
                print("MATCH_URL:", match.get("match_url"))
            else:
                print("MATCH: NONE")
            if diag:
                print("CANDIDATES:", diag.get("candidate_names"))
                print("SELECTED_NAME:", diag.get("selected_name"))
                print("SELECTED_TAXON_ID:", diag.get("selected_taxon_id"))
                print("FINAL_STATUS:", diag.get("final_status"))
                print("FINAL_REASON:", diag.get("final_reason"))
                print("MATCH_ATTEMPTS:", len(diag.get("match_attempts") or []))
                for attempt in (diag.get("match_attempts") or [])[:6]:
                    print(" - MATCH", "OK" if attempt.get("ok") else "NO", attempt.get("method"), attempt.get("candidate_name"), attempt.get("url"), attempt.get("error") or "")
                print("API_ATTEMPTS:", len(diag.get("api_attempts") or []))
                for attempt in (diag.get("api_attempts") or [])[:8]:
                    print(" - API", "OK" if attempt.get("ok") else "NO", attempt.get("method"), attempt.get("url"), attempt.get("error") or "")
                print("TAXONPAGE_ATTEMPTS:", len(diag.get("taxonpage_attempts") or []))
                for attempt in (diag.get("taxonpage_attempts") or [])[:6]:
                    print(" - TAXONPAGE", "OK" if attempt.get("ok") else "NO", attempt.get("method"), attempt.get("url"), attempt.get("error") or "")
            if profile:
                print("PROFILE_SOURCE:", profile.get("source"))
                print("PROFILE_DIAGNOSTIC:", profile.get("diagnostic"))
                print("PROFILE_TAXON:", profile.get("scientific_name"))
                print("PROFILE_URL:", profile.get("taxon_url"))
                print("SUBSTRATA:", profile.get("substrata"))
                print("ROCK_TYPE:", profile.get("rock_type"))
                print("TREE_TYPE:", profile.get("tree_type"))
                print("HABITAT:", profile.get("habitat"))
                print("ECOLOGY_PRESENT:", bool(profile.get("ecology_traits") or profile.get("notes")))
                print("REGIONS_PRESENT:", bool(profile.get("regions_distribution")))
                print("ECOREGIONS_PRESENT:", bool(profile.get("ecoregions_distribution")))
                print("ITALIC_ALT_CLASSES:", profile.get("italic_altitude_class_min"), profile.get("italic_altitude_class_max"))
                print("ITALIC_ALT_METERS:", profile.get("altitudinal_distribution_min"), profile.get("altitudinal_distribution_max"))
                print("ITALIC_ALT_SOURCE:", profile.get("altitudinal_distribution_source"))
                print("PH_CLASSES:", profile.get("ph_of_the_substrata_min"), profile.get("ph_of_the_substrata_max"))
                print("ARIDITY_CLASSES:", profile.get("aridity_min"), profile.get("aridity_max"))
            print("========================\n")
        except Exception as exc:
            print("ITALIC DEBUG PRINT ERROR:", exc)
