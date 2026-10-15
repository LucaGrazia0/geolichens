import json
import math
import urllib.parse

from .network_service import fetch_text


class GeocodingResult:
    def __init__(self, ok=False, query=None, feature=None, error=None, raw=None, matched_source=None, tried_queries=None, candidates=None):
        self.ok = ok
        self.query = query
        self.feature = feature
        self.error = error
        self.raw = raw
        self.matched_source = matched_source
        self.tried_queries = tried_queries or []
        self.candidates = candidates or ((raw or {}).get("features", []) if isinstance(raw, dict) else [])

    @property
    def place_name(self):
        return self.feature.get("place_name") if self.feature else None

    @property
    def center(self):
        return self.feature.get("center") if self.feature else None

    @property
    def bbox(self):
        return self.feature.get("bbox") if self.feature else None


class GeocodingService:
    BASE = "https://api.maptiler.com/geocoding"
    DEFAULT_BBOX = (8.45, 44.7, 11.45, 46.7)  # Lombardia approx

    REF_TYPE_WEIGHTS = {
        "municipality": 2.4,
        "summit": 2.2,
        "summit_peak": 2.2,
        "mountain_area": 2.1,
        "mountain_group": 1.9,
        "pass": 2.0,
        "valley": 1.9,
        "refuge_malga": 1.8,
        "forest_area": 1.8,
        "meadow": 1.5,
        "hydro": 1.5,
        "nearby_place": 1.2,
        "trail": 1.0,
        "generic_toponym": 0.8,
        "locality": 0.6,
    }

    def __init__(self, api_key=None, bbox=None, timeout=20):
        self.api_key = api_key or ""
        self.bbox = bbox or self.DEFAULT_BBOX
        self.timeout = timeout

    def set_api_key(self, api_key):
        self.api_key = api_key or ""

    def set_bbox(self, bbox):
        if bbox and len(bbox) == 4:
            self.bbox = tuple(bbox)

    def _normalize(self, text):
        return " ".join(str(text or "").lower().replace(",", " ").split())

    def _types_param(self, ref_type):
        # Keep conservative so we don't exclude legitimate mountain toponyms.
        if ref_type == "municipality":
            return "municipality,county,locality,place"
        if ref_type in ("summit", "summit_peak", "mountain_area", "mountain_group", "pass", "valley", "meadow", "refuge_malga", "forest_area", "hydro", "trail", "generic_toponym"):
            return "poi,place,locality"
        return "poi,place,locality,municipality,county"

    def _call(self, query_text, limit=10, types_param=None, proximity=None):
        encoded_query = urllib.parse.quote(str(query_text).strip())
        bbox_str = ",".join(str(v) for v in self.bbox)
        params = [
            f"key={urllib.parse.quote(self.api_key)}",
            f"bbox={bbox_str}",
            "language=it",
            f"limit={limit}",
            "autocomplete=true",
        ]
        if types_param:
            params.append(f"types={urllib.parse.quote(types_param)}")
        if proximity and len(proximity) == 2:
            params.append(f"proximity={proximity[0]},{proximity[1]}")
        url = f"{self.BASE}/{encoded_query}.json?{'&'.join(params)}"
        return json.loads(fetch_text(
            url, timeout=self.timeout,
            headers={"User-Agent": "GeoLichen/15.5.18", "Accept": "application/json"},
        ))

    def _haversine_m(self, lon1, lat1, lon2, lat2):
        r = 6371000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _feature_score(self, feature, original_query, ref_type=None, municipality_hint=None, municipality_center=None):
        score = 0.0
        oq = self._normalize(original_query)
        place_name = self._normalize(feature.get("place_name") or "")
        text = self._normalize(feature.get("text") or feature.get("place_name") or "")
        place_type = feature.get("place_type")
        if isinstance(place_type, list):
            feature_type = ",".join(place_type).lower()
        else:
            feature_type = str(place_type or feature.get("type") or "").lower()

        # Exact / prefix matching gets a lot of weight.
        if oq == text:
            score += 140
        if oq == place_name:
            score += 130
        if text.startswith(oq) and oq:
            score += 80
        if place_name.startswith(oq) and oq:
            score += 70
        if oq and f" {oq} " in f" {place_name} ":
            score += 45
        if oq and f" {oq} " in f" {text} ":
            score += 45

        # Prefer Lombardia / Italy.
        if "lombardia" in place_name:
            score += 20
        if "italia" in place_name:
            score += 6

        # Municipality hint matters a lot.
        muni = self._normalize(municipality_hint)
        if muni:
            if muni in place_name:
                score += 110
            elif muni in text:
                score += 80

        # Type-aware scoring.
        if ref_type:
            score += 10 * self.REF_TYPE_WEIGHTS.get(ref_type, 0.5)
            summit_kw = ["cima", "vetta", "pizzo", "punta", "corno"]
            mountain_kw = ["monte", "montagna", "massiccio", "gruppo", "dorsale", "catena", "colle", "dosso", "poggio"]
            pass_kw = ["passo", "forcella", "sella", "bocchetta"]
            valley_kw = ["valle", "val "]
            hydro_kw = ["lago", "rio", "torrente", "fiume"]
            refuge_kw = ["rifugio", "malga", "bivacco"]
            meadow_kw = ["prato", "piana", "pian", "alpe", "alpeggio"]
            if ref_type == "summit":
                if any(k in place_name for k in summit_kw + mountain_kw):
                    score += 45
                if any(t in feature_type for t in ["poi", "place", "locality"]):
                    score += 8
            elif ref_type == "summit_peak":
                if any(k in place_name for k in summit_kw):
                    score += 50
                if any(t in feature_type for t in ["poi", "place", "locality"]):
                    score += 8
            elif ref_type == "mountain_area":
                if any(k in place_name for k in mountain_kw):
                    score += 55
                # Se il geocoder fornisce una bbox, è molto utile per costruire
                # un'area di rilievo invece di un buffer puntuale.
                if feature.get("bbox"):
                    score += 25
            elif ref_type == "mountain_group":
                if any(k in place_name for k in ["gruppo", "massiccio", "catena", "dorsale", "monte"]):
                    score += 50
                if feature.get("bbox"):
                    score += 30
            elif ref_type == "pass":
                if any(k in place_name for k in pass_kw):
                    score += 45
            elif ref_type == "valley":
                if any(k in place_name for k in valley_kw):
                    score += 40
            elif ref_type == "hydro":
                if any(k in place_name for k in hydro_kw):
                    score += 35
            elif ref_type == "refuge_malga":
                if any(k in place_name for k in refuge_kw):
                    score += 35
            elif ref_type == "forest_area":
                if any(k in place_name for k in ["foresta", "bosco", "selva", "ersaf", "demaniale"]):
                    score += 45
            elif ref_type == "meadow":
                if any(k in place_name for k in meadow_kw):
                    score += 30
            elif ref_type == "municipality":
                if any(t in feature_type for t in ["municipality", "county", "place", "locality", "region"]):
                    score += 30

        # Read provider relevance when available.
        rel = feature.get("relevance")
        try:
            if rel is not None:
                score += float(rel) * 20
        except Exception:
            pass

        # GeoLichen 2.1: il Comune è un vincolo spaziale forte.
        center = feature.get("center")
        if municipality_center and center and len(center) == 2:
            try:
                dist = self._haversine_m(center[0], center[1], municipality_center[0], municipality_center[1])
                if dist <= 3000:
                    score += 120
                elif dist <= 8000:
                    score += 95
                elif dist <= 15000:
                    score += 70
                elif dist <= 25000:
                    score += 35
                elif dist <= 40000:
                    score += 5
                elif dist <= 60000:
                    score -= 40
                else:
                    score -= 120
            except Exception:
                pass

        return score

    def _distance_to_municipality(self, feature, municipality_center=None):
        center = feature.get("center") if isinstance(feature, dict) else None
        if municipality_center and center and len(center) == 2:
            try:
                return float(self._haversine_m(center[0], center[1], municipality_center[0], municipality_center[1]))
            except Exception:
                return None
        return None

    def _score_reason(self, feature, original_query, ref_type=None, municipality_hint=None, municipality_center=None):
        """Motivazione sintetica e leggibile del ranking del geocoder."""
        reasons = []
        oq = self._normalize(original_query)
        place_name = self._normalize(feature.get("place_name") or "")
        text = self._normalize(feature.get("text") or feature.get("place_name") or "")
        place_type = feature.get("place_type")
        if isinstance(place_type, list):
            feature_type = ",".join(place_type).lower()
        else:
            feature_type = str(place_type or feature.get("type") or "").lower()

        if oq and (oq == text or oq == place_name):
            reasons.append("nome esatto")
        elif oq and (text.startswith(oq) or place_name.startswith(oq)):
            reasons.append("inizio nome coerente")
        elif oq and (f" {oq} " in f" {place_name} " or f" {oq} " in f" {text} "):
            reasons.append("nome contenuto")

        muni = self._normalize(municipality_hint)
        if muni:
            if muni in place_name or muni in text:
                reasons.append("comune coerente")
            else:
                dist = self._distance_to_municipality(feature, municipality_center)
                if dist is not None:
                    if dist < 5000:
                        reasons.append("vicino al comune")
                    elif dist > 30000:
                        reasons.append("lontano dal comune")

        if ref_type:
            if ref_type == "pass" and any(k in place_name for k in ["passo", "forcella", "sella", "bocchetta"]):
                reasons.append("tipo passo")
            elif ref_type == "summit" and any(k in place_name for k in ["monte", "cima", "vetta", "pizzo", "punta", "corno"]):
                reasons.append("tipo cima/monte")
            elif ref_type == "summit_peak" and any(k in place_name for k in ["cima", "vetta", "pizzo", "punta", "corno"]):
                reasons.append("tipo cima/vetta")
            elif ref_type == "mountain_area" and any(k in place_name for k in ["monte", "montagna", "colle", "dosso", "poggio"]):
                reasons.append("tipo monte/area del rilievo")
            elif ref_type == "mountain_group" and any(k in place_name for k in ["gruppo", "massiccio", "catena", "dorsale"]):
                reasons.append("tipo gruppo montuoso")
            elif ref_type == "valley" and any(k in place_name for k in ["valle", "val "]):
                reasons.append("tipo valle")
            elif ref_type == "refuge_malga" and any(k in place_name for k in ["rifugio", "malga", "bivacco"]):
                reasons.append("tipo rifugio/malga")
            elif ref_type == "forest_area" and any(k in place_name for k in ["foresta", "bosco", "selva", "ersaf", "demaniale"]):
                reasons.append("tipo area forestale")

        if feature.get("bbox"):
            reasons.append("bbox disponibile")
        else:
            reasons.append("solo punto")

        if not reasons:
            reasons.append("ranking automatico")
        return "; ".join(reasons)

    def geocode_ranked(self, query_text, original_query=None, ref_type=None, municipality_hint=None, municipality_center=None):
        if not self.api_key:
            return GeocodingResult(ok=False, query=query_text, error="API key mancante", matched_source=ref_type)
        if not query_text:
            return GeocodingResult(ok=False, query=query_text, error="Query vuota", matched_source=ref_type)
        try:
            data = self._call(
                query_text,
                limit=10,
                types_param=self._types_param(ref_type),
                proximity=municipality_center,
            )
            features = data.get("features", [])
            if not features:
                return GeocodingResult(ok=False, query=query_text, error="Nessun risultato trovato", raw=data, matched_source=ref_type)
            scored = []
            for f in features:
                try:
                    score = self._feature_score(
                        f,
                        original_query or query_text,
                        ref_type=ref_type,
                        municipality_hint=municipality_hint,
                        municipality_center=municipality_center,
                    )
                except Exception:
                    score = 0.0
                try:
                    f["_geolichen_score"] = float(score)
                    f["_geolichen_query"] = query_text
                    f["_geolichen_ref_type"] = ref_type
                    f["_geolichen_distance_to_municipality_m"] = self._distance_to_municipality(f, municipality_center)
                    f["_geolichen_score_reason"] = self._score_reason(
                        f,
                        original_query or query_text,
                        ref_type=ref_type,
                        municipality_hint=municipality_hint,
                        municipality_center=municipality_center,
                    )
                except Exception:
                    pass
                scored.append(f)

            ranked = sorted(
                scored,
                key=lambda f: float(f.get("_geolichen_score", 0.0)),
                reverse=True,
            )
            data["features"] = ranked
            return GeocodingResult(
                ok=True,
                query=query_text,
                feature=ranked[0],
                raw=data,
                matched_source=ref_type,
                candidates=ranked,
            )
        except Exception as e:
            return GeocodingResult(ok=False, query=query_text, error=str(e), matched_source=ref_type)

    def _build_queries_for_reference(self, ref, municipality_value=None):
        name = ref.normalized_name
        muni = str(municipality_value).strip() if municipality_value else None
        queries = []
        if muni:
            queries.append(f"{name}, {muni}, Lombardia, Italia")
            queries.append(f"{name}, {muni}, Italia")
        queries.append(f"{name}, Lombardia, Italia")
        queries.append(f"{name}, Italia")
        queries.append(name)
        out = []
        seen = set()
        for item in queries:
            key = self._normalize(item)
            if key and key not in seen:
                seen.add(key)
                out.append(item)
        return out

    def _geocode_municipality(self, municipality_value):
        if not municipality_value:
            return None
        for q in [f"{municipality_value}, Lombardia, Italia", f"{municipality_value}, Italia", str(municipality_value)]:
            res = self.geocode_ranked(q, original_query=str(municipality_value), ref_type="municipality", municipality_hint=str(municipality_value))
            if res.ok:
                return res
        return None


    def _candidate_scope(self, feature, municipality_center=None):
        dist = self._distance_to_municipality(feature, municipality_center)
        if dist is None:
            return "unknown"
        try:
            d = float(dist)
            if d <= 15000:
                return "municipality_core"
            if d <= 30000:
                return "municipality_extended"
            if d <= 45000:
                return "wide_search"
            return "outside_municipality_context"
        except Exception:
            return "unknown"

    def _annotate_candidate_scope(self, feature, municipality_center=None):
        try:
            feature["_geolichen_municipality_scope"] = self._candidate_scope(feature, municipality_center)
        except Exception:
            pass
        return feature

    def _dedupe_features(self, features):
        out = []
        seen = set()
        for f in features or []:
            center = f.get("center") if isinstance(f, dict) else None
            try:
                center_key = tuple(round(float(x), 5) for x in center) if center and len(center) == 2 else None
            except Exception:
                center_key = None
            key = (self._normalize(f.get("place_name") or f.get("text") or ""), center_key)
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
        return out

    def _choose_best_from_candidates(self, candidates, municipality_center=None):
        candidates = self._dedupe_features(candidates)
        for f in candidates:
            self._annotate_candidate_scope(f, municipality_center)
        core = [
            f for f in candidates
            if f.get("_geolichen_municipality_scope") in ["municipality_core", "municipality_extended"]
        ]
        pool = core if core else candidates
        pool = sorted(pool, key=lambda f: float(f.get("_geolichen_score", 0.0)), reverse=True)
        return pool[0] if pool else None, pool


    def geocode_prefer_municipality(
        self,
        municipality_value=None,
        locality_text=None,
        locality_parse_result=None,
        locality_context=None,
    ):
        """Geocoding Comune-guided e semantico.

        Fase 5.5c: accetta ``LocalityContext`` come sorgente unica dei valori,
        mantenendo piena compatibilità con i tre argomenti storici. Gli
        argomenti espliciti hanno sempre priorità.

        1. Geocodifica il Comune per centro/proximity.
        2. Geocodifica i riferimenti della località.
        3. Preferisce candidati nel contesto comunale.
        4. Mantiene ricerca ampia solo come fallback.
        """
        if locality_context is not None:
            if municipality_value is None:
                municipality_value = getattr(locality_context, "municipality", None)
            if locality_text is None:
                locality_text = (
                    getattr(locality_context, "locality", None)
                    or getattr(locality_context, "search_name", None)
                )

        tried = []
        all_candidates = []

        municipality_result = self._geocode_municipality(municipality_value)
        municipality_center = municipality_result.center if municipality_result and municipality_result.ok else None
        municipality_hint = str(municipality_value) if municipality_value else None

        if municipality_result and municipality_result.ok:
            tried.append(("municipality", municipality_result.query))

        if locality_parse_result is not None:
            refs = locality_parse_result.best_references()
            for ref in refs:
                if ref.ref_type == "municipality" and municipality_value:
                    continue
                for q in self._build_queries_for_reference(ref, municipality_value=municipality_value):
                    tried.append((ref.ref_type, q))
                    res = self.geocode_ranked(
                        q,
                        original_query=ref.normalized_name,
                        ref_type=ref.ref_type,
                        municipality_hint=municipality_hint,
                        municipality_center=municipality_center,
                    )
                    if res.ok:
                        for f in res.candidates or []:
                            f["_geolichen_query"] = q
                            f["_geolichen_ref_type"] = ref.ref_type
                            all_candidates.append(f)

        if locality_text:
            queries = []
            if municipality_value:
                queries.append(f"{locality_text}, {municipality_value}, Lombardia, Italia")
                queries.append(f"{locality_text}, {municipality_value}, Italia")
            queries.extend([
                f"{locality_text}, Lombardia, Italia",
                f"{locality_text}, Italia",
                locality_text,
            ])
            seen = set()
            for q in queries:
                norm = self._normalize(q)
                if norm in seen:
                    continue
                seen.add(norm)
                tried.append(("locality", q))
                res = self.geocode_ranked(
                    q,
                    original_query=str(locality_text),
                    ref_type="locality",
                    municipality_hint=municipality_hint,
                    municipality_center=municipality_center,
                )
                if res.ok:
                    for f in res.candidates or []:
                        f["_geolichen_query"] = q
                        f["_geolichen_ref_type"] = "locality"
                        all_candidates.append(f)

        if all_candidates:
            best, ranked = self._choose_best_from_candidates(all_candidates, municipality_center)
            if best:
                raw = {"features": ranked}
                return GeocodingResult(
                    ok=True,
                    query=best.get("_geolichen_query") or locality_text,
                    feature=best,
                    raw=raw,
                    matched_source=best.get("_geolichen_ref_type") or "locality",
                    tried_queries=tried,
                    candidates=ranked,
                )

        if municipality_result and municipality_result.ok:
            municipality_result.tried_queries = tried or [("municipality", municipality_result.query)]
            return municipality_result

        return GeocodingResult(
            ok=False,
            query=municipality_value or locality_text,
            error="Né comune né località hanno prodotto un risultato",
            tried_queries=tried,
        )

