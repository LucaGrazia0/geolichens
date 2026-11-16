import json
import math
from difflib import SequenceMatcher
from pathlib import Path

from .osm_geocoding_service import PhotonGeocoder
from ..core.locality_names import normalize_name, name_variants, locality_kind, plausible_name, search_variants, name_evidence
from .confirmed_localities_service import ConfirmedLocalitiesService


class GeocodingResult:
    def __init__(self, ok=False, query=None, feature=None, error=None, raw=None, matched_source=None, tried_queries=None, candidates=None, warning=None):
        self.ok = ok
        self.query = query
        self.feature = feature
        self.error = error
        self.warning = warning
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

    def __init__(self, bbox=None, timeout=35, endpoint=None, cache_dir=None):
        self.bbox = self.DEFAULT_BBOX if bbox is None else bbox
        self.timeout = timeout
        self.client = PhotonGeocoder(endpoint, timeout, cache_dir)
        self._lookup_error = None
        self.auto_expand = False
        self.archive = ConfirmedLocalitiesService(Path(cache_dir) / 'confirmed_localities.json' if cache_dir else None)
        self.use_archive = True
        self.municipality_boundary = None
        self.last_warning = ''

    def set_endpoint(self, endpoint):
        self.client.endpoint = PhotonGeocoder.validate_endpoint(endpoint)

    def set_bbox(self, bbox):
        if bbox is None:
            self.bbox = None
        elif len(bbox) == 4:
            values = tuple(float(v) for v in bbox)
            if not (-180 <= values[0] < values[2] <= 180
                    and -90 <= values[1] < values[3] <= 90):
                raise ValueError('Area di ricerca non valida.')
            self.bbox = values

    def _normalize(self, text):
        return normalize_name(text)

    def _boundary_match(self, feature):
        """Use a loaded administrative polygon, never its bounding rectangle."""
        feature.pop('_geolichen_municipality_match', None)
        feature.pop('_geolichen_distance_to_boundary_m', None)
        if self.municipality_boundary is None or self.municipality_boundary.isEmpty():
            return
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsPointXY, QgsProject
        from ._shared_geo_utils import local_metric_crs
        try:
            point = QgsGeometry.fromPointXY(QgsPointXY(*map(float, feature['center'])))
            inside = self.municipality_boundary.intersects(point)
            distance = 0.0
            if not inside:
                polygon = QgsGeometry(self.municipality_boundary)
                transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'),
                                                     local_metric_crs(point.asPoint()), QgsProject.instance())
                polygon.transform(transform); point.transform(transform)
                distance = polygon.distance(point)
            feature['_geolichen_distance_to_boundary_m'] = distance
            feature['_geolichen_municipality_match'] = 'inside' if inside else ('near' if distance <= 2000 else 'outside')
        except (ValueError, TypeError, KeyError):
            pass

    @staticmethod
    def _tag_match(feature, ref_type):
        props = feature.get('properties') or {}
        key, value = props.get('osm_key'), props.get('osm_value')
        compatible = {
            'summit': {('natural', 'peak')}, 'summit_peak': {('natural', 'peak')},
            'mountain_area': {('natural', 'peak'), ('natural', 'ridge'), ('place', 'mountain')},
            'pass': {('mountain_pass', 'yes'), ('natural', 'saddle')},
            'valley': {('natural', 'valley')},
            'hydro': {('natural', 'water'), ('water', 'lake'), ('landuse', 'reservoir'),
                      ('waterway', 'river'), ('waterway', 'stream')},
            'forest_area': {('natural', 'wood'), ('landuse', 'forest')},
            'refuge_malga': {('tourism', 'alpine_hut'), ('tourism', 'wilderness_hut'), ('amenity', 'shelter')},
            'trail': {('highway', 'path'), ('highway', 'track'), ('highway', 'footway'), ('highway', 'bridleway')},
        }
        return bool((key, value) in compatible.get(ref_type, set()))

    def _types_param(self, ref_type):
        # Keep conservative so we don't exclude legitimate mountain toponyms.
        if ref_type == "municipality":
            return "municipality,county,locality,place"
        if ref_type in ("summit", "summit_peak", "mountain_area", "mountain_group", "pass", "valley", "meadow", "refuge_malga", "forest_area", "hydro", "trail", "generic_toponym"):
            return "poi,place,locality"
        return "poi,place,locality,municipality,county"

    def _call(self, query_text, limit=10, types_param=None, proximity=None):
        if self._lookup_error:
            # A failed town request must not suppress valid cached localities.
            # Try the same context, then a previously un-biased request. Both
            # keep endpoint, current bbox and TTL isolation; no network retry.
            for focus in ([proximity, None] if proximity else [None]):
                try:
                    data = self.client.search(query_text, self.bbox, focus, limit, cache_only=True)
                    for feature in data.get('features', []):
                        feature['_geolichen_cached_response'] = True
                    return data
                except OSError:
                    pass
            raise OSError(self._lookup_error)
        try:
            data = self.client.search(query_text, self.bbox, proximity, limit)
            if self.client.last_from_cache:
                for feature in data.get('features', []):
                    feature['_geolichen_cached_response'] = True
            if not data.get('features') and self.bbox and self.auto_expand:
                data = self.client.search(query_text, None, proximity, limit)
                for feature in data.get('features', []):
                    feature['_geolichen_area_expanded'] = True
            return data
        except (OSError, TimeoutError) as exc:
            self._lookup_error = 'Ricerca online Photon non disponibile: ' + str(exc)
            raise

    def _haversine_m(self, lon1, lat1, lon2, lat2):
        r = 6371000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _feature_score(self, feature, original_query, ref_type=None, municipality_hint=None, municipality_center=None):
        score = 0.0
        self._boundary_match(feature)
        variants = name_variants(original_query)
        oq = self._normalize(variants[1] if len(variants) > 1 else original_query)
        place_name = self._normalize(feature.get("place_name") or "")
        text = self._normalize(feature.get("text") or feature.get("place_name") or "")
        tier, coverage = name_evidence(original_query, feature.get('text'), municipality_hint)
        feature['_geolichen_name_tier'] = tier
        score += 80 * coverage
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

        # Prefer Italian results within the configured search area.
        if "italia" in place_name:
            score += 6

        # Municipality hint matters a lot.
        town_match, _ = self._town_evidence(feature, municipality_hint)
        if town_match == 'same':
            score += 110
        elif town_match == 'different':
            score -= 25

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
        boundary_match = feature.get('_geolichen_municipality_match')
        if boundary_match:
            score += {'inside': 120, 'near': 60, 'outside': -40}[boundary_match]
        elif municipality_center and center and len(center) == 2:
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

        if self._tag_match(feature, ref_type):
            score += 60
        similarity = SequenceMatcher(None, oq, text).ratio()
        if similarity >= .65:
            score += 30 * similarity
        return score

    def _distance_to_municipality(self, feature, municipality_center=None):
        center = feature.get("center") if isinstance(feature, dict) else None
        if municipality_center and center and len(center) == 2:
            try:
                return float(self._haversine_m(center[0], center[1], municipality_center[0], municipality_center[1]))
            except Exception:
                return None
        return None

    def _town_evidence(self, feature, municipality):
        def clean(value):
            value = self._normalize(value)
            return value.removeprefix('comune di ').strip()
        props = feature.get('properties') or {}
        reported = props.get('city') or props.get('municipality')
        if not municipality or not reported:
            return 'unknown', reported
        return ('same' if clean(reported) == clean(municipality) else 'different'), reported

    def _score_reason(self, feature, original_query, ref_type=None, municipality_hint=None, municipality_center=None):
        """Motivazione sintetica e leggibile del ranking del geocoder."""
        reasons = []
        variants = name_variants(original_query)
        oq = self._normalize(variants[1] if len(variants) > 1 else original_query)
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
        tier, coverage = name_evidence(original_query, feature.get('text'), municipality_hint)
        if tier == 2:
            reasons.append('parole distintive del nome presenti')
        elif tier == 1:
            reasons.append('nome simile con possibile variante ortografica')
        elif coverage > 0:
            reasons.append('solo alcune parole distintive del nome presenti')

        town_match, reported = self._town_evidence(feature, municipality_hint)
        if town_match == 'same':
            reasons.append('comune indicato dalla fonte coerente')
        elif town_match == 'different':
            reasons.append(f'comune indicato dalla fonte: {reported}; diverso da quello del record, da verificare')

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

        if feature.get('_geolichen_area_expanded'):
            reasons.append("ricerca estesa oltre l’area selezionata")
        if feature.get("bbox"):
            reasons.append("bbox disponibile")
        else:
            reasons.append("solo punto")

        if not reasons:
            reasons.append("ranking automatico")
        if self._tag_match(feature, ref_type):
            reasons.append('tipo OSM coerente')
        match = feature.get('_geolichen_municipality_match')
        if match:
            reasons.append({'inside': 'dentro il confine comunale',
                            'near': 'vicino al confine comunale',
                            'outside': 'fuori dal confine comunale'}[match])
        elif municipality_center:
            reasons.append('vicinanza al centro del comune; confine non verificato')
        if feature.get('_geolichen_confirmed_locality'):
            reasons.append('località già confermata nell’archivio locale')
        if feature.get('_geolichen_cached_response'):
            reasons.append('risposta Photon dalla cache locale')
        return "; ".join(reasons)

    def geocode_ranked(self, query_text, original_query=None, ref_type=None, municipality_hint=None, municipality_center=None):
        if not query_text:
            return GeocodingResult(ok=False, query=query_text, error="Query vuota", matched_source=ref_type)
        try:
            if ref_type in (None, 'locality', 'generic_toponym'):
                ref_type = locality_kind(original_query or query_text)
            data = self._call(
                query_text,
                limit=10,
                types_param=self._types_param(ref_type),
                proximity=municipality_center,
            )
            features = data.get("features", [])
            # A road named after a pass or peak is not that natural feature.
            natural_intent = ref_type in ('pass', 'summit', 'summit_peak', 'mountain_area', 'mountain_group', 'valley')
            natural_intent = natural_intent or (ref_type != 'trail' and locality_kind(original_query or query_text) in (
                'pass', 'summit_peak', 'mountain_area', 'valley', 'hydro', 'forest_area')
            )
            if natural_intent:
                features = [f for f in features if (f.get('properties') or {}).get('osm_key')
                            not in ('highway', 'railway')]
            if ref_type != 'municipality':
                features = [f for f in features if plausible_name(
                    original_query or query_text, f.get('text'), municipality_hint)]
            # Failed results must not expose rejected provider hits via raw.
            data['features'] = features
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
                    f['_geolichen_original_query'] = original_query or query_text
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
                key=self._ranking_key,
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
                warning=self._name_warning(original_query or query_text, ranked) if ref_type != 'municipality' else None,
            )
        except Exception as e:
            return GeocodingResult(ok=False, query=query_text, error=str(e), matched_source=ref_type)

    def _build_queries_for_reference(self, ref, municipality_value=None):
        name = ref.normalized_name
        muni = str(municipality_value).strip() if municipality_value else None
        # Photon uses the bbox and municipality location bias; start with the
        # actual toponym instead of turning its name into a long address string.
        return search_variants(name, muni)

    @staticmethod
    def _ranking_key(feature):
        return feature.get('_geolichen_name_tier', 0), float(feature.get('_geolichen_score', 0.0))

    def _name_warning(self, query, candidates):
        """A partial name match is a suggestion, never a verified alias."""
        variants = name_variants(query)
        expected = self._normalize(variants[-1]) if variants else ''
        if not candidates or not expected:
            return None
        has_exact_or_confirmed = False
        for feature in candidates:
            exact = self._normalize(feature.get('text')) == expected
            feature['_geolichen_partial_name'] = not exact and not feature.get('_geolichen_confirmed_locality')
            has_exact_or_confirmed |= not feature['_geolichen_partial_name']
        if has_exact_or_confirmed:
            return None
        return ('Nessuna corrispondenza esatta con il nome richiesto. '
                'Le località proposte hanno nomi parzialmente simili: verifica la posizione '
                'in mappa oppure modifica il nome; non sono equivalenze accertate.')

    def _geocode_municipality(self, municipality_value):
        if not municipality_value:
            return None
        for q in [str(municipality_value), f"{municipality_value}, Italia"]:
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
        seen = {}
        for f in features or []:
            center = f.get("center") if isinstance(f, dict) else None
            try:
                center_key = tuple(round(float(x), 5) for x in center) if center and len(center) == 2 else None
            except Exception:
                center_key = None
            identity = f.get('id')
            key = ('id', identity) if identity and identity != 'osm::' else (self._normalize(f.get("place_name") or f.get("text") or ""), center_key)
            if key in seen:
                old = out[seen[key]]
                old_center = tuple(round(float(x), 5) for x in old.get('center', []))
                if (old.get('_geolichen_confirmed_locality') or f.get('_geolichen_confirmed_locality')) and old_center != center_key:
                    # A source may have moved its representative point since
                    # the user's confirmation. Show both positions for review.
                    key = (key, center_key)
            queries = [f.get('_geolichen_query')] if f.get('_geolichen_query') else []
            if key in seen:
                index = seen[key]
                old = out[index]
                queries += old.get('_geolichen_queries', [])
                better = f if float(f.get('_geolichen_score', 0)) > float(old.get('_geolichen_score', 0)) else old
                if old.get('_geolichen_confirmed_locality') or f.get('_geolichen_confirmed_locality'):
                    better['_geolichen_confirmed_locality'] = True
                    better['_geolichen_confirmed_at'] = old.get('_geolichen_confirmed_at') or f.get('_geolichen_confirmed_at', '')
                better['_geolichen_queries'] = list(dict.fromkeys(queries))
                out[index] = better
            else:
                seen[key] = len(out)
                f['_geolichen_queries'] = queries
                out.append(f)
        return out

    def _choose_best_from_candidates(self, candidates, municipality_center=None):
        candidates = self._dedupe_features(candidates)
        for f in candidates:
            self._annotate_candidate_scope(f, municipality_center)
        # Keep alternatives visible: distance to the town center is not proof
        # of administrative membership, especially in mountain municipalities.
        pool = candidates
        pool = sorted(pool, key=self._ranking_key, reverse=True)
        return pool[0] if pool else None, pool

    def _search_reference(self, name, kind, municipality, center, tried, attempted):
        """A partial hit must not stop the quick search; avoid duplicate work."""
        found = []
        effective_kind = locality_kind(name) if kind in (None, 'locality', 'generic_toponym') else kind
        for query in search_variants(name, municipality)[:3]:
            key = (self._normalize(query), self._normalize(name), effective_kind)
            if key not in attempted:
                tried.append((effective_kind, query))
                attempted[key] = self.geocode_ranked(
                    query, original_query=name, ref_type=effective_kind,
                    municipality_hint=municipality, municipality_center=center)
            result = attempted[key]
            if result.ok:
                found.extend(result.candidates)
                if not result.warning:
                    break
        return found


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

        self.client.begin_search()
        self._lookup_error = None
        self.last_warning = ''
        tried = []
        all_candidates = []
        attempted = {}

        local = self.archive.lookup(locality_text, municipality_value, self.bbox) if self.use_archive else []
        if local:
            for f in local:
                f['_geolichen_query'] = locality_text
                f['_geolichen_ref_type'] = locality_kind(locality_text)
                f['_geolichen_score_reason'] = 'località confermata nell’archivio locale; verifica prima di creare il buffer'
                self._boundary_match(f)
            return GeocodingResult(ok=True, feature=local[0], candidates=local,
                                   query=locality_text, matched_source=locality_kind(locality_text))

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
                all_candidates.extend(self._search_reference(
                    ref.normalized_name, ref.ref_type, municipality_hint,
                    municipality_center, tried, attempted))

        if locality_text:
            all_candidates.extend(self._search_reference(
                str(locality_text), 'locality', municipality_hint,
                municipality_center, tried, attempted))

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
                    warning=self._name_warning(locality_text, ranked),
                    error=self._lookup_error,
                )

        if municipality_result and municipality_result.ok:
            if locality_text and self._normalize(locality_text) != self._normalize(municipality_value):
                return GeocodingResult(
                    ok=False, query=locality_text, tried_queries=tried,
                    error=self._lookup_error or (
                        'Comune trovato, ma nessuna località corrispondente al nome richiesto. '
                        'Modifica il nome e usa «Cerca altre località», oppure indica il punto manualmente.'))
            municipality_result.tried_queries = tried or [("municipality", municipality_result.query)]
            return municipality_result

        return GeocodingResult(
            ok=False,
            query=municipality_value or locality_text,
            error=self._lookup_error or "Né comune né località hanno prodotto un risultato; prova una ricerca manuale.",
            tried_queries=tried,
        )

    def search_more(self, query, municipality=None, previous_candidates=(), lookup_municipality=True):
        """Explore bounded variants even after a success; preserve old results on failure."""
        self.client.begin_search()
        self._lookup_error = None
        self.last_warning = ''
        tried = []
        candidates = list(previous_candidates)
        if self.use_archive:
            candidates.extend(self.archive.lookup(query, municipality, self.bbox))
        town = self._geocode_municipality(municipality) if lookup_municipality else None
        center = town.center if town and town.ok else None
        queries = search_variants(query, municipality)
        seen = set()
        for text in queries:
            key = self._normalize(text)
            if key in seen:
                continue
            seen.add(key)
            if self._lookup_error or self.client.network_requests >= self.client.max_requests:
                self.last_warning = self._lookup_error or 'Raggiunto il limite di richieste; risultati raccolti conservati.'
                self._lookup_error = self._lookup_error or self.last_warning
            tried.append((locality_kind(query), text))
            result = self.geocode_ranked(text, original_query=query, ref_type=locality_kind(query),
                                         municipality_hint=municipality, municipality_center=center)
            if result.ok:
                candidates.extend(result.candidates)
        # Re-evaluate all merged alternatives against the current edited name,
        # rather than comparing scores calculated for different old queries.
        for f in candidates:
            kind = locality_kind(query)
            f['_geolichen_score'] = self._feature_score(f, query, kind, municipality, center)
            f['_geolichen_distance_to_municipality_m'] = self._distance_to_municipality(f, center)
            f['_geolichen_score_reason'] = self._score_reason(f, query, kind, municipality, center)
        best, ranked = self._choose_best_from_candidates(candidates, center)
        self.last_warning = self._lookup_error or self.last_warning
        return GeocodingResult(ok=bool(best), feature=best, candidates=ranked, query=query,
                               matched_source=locality_kind(query), tried_queries=tried,
                               warning=self._name_warning(query, ranked),
                               error=self.last_warning or (None if best else 'Nessuna località trovata.'))

    def search_in_area(self, query, municipality, bbox):
        """A user-chosen map extent restricts this action, not project settings."""
        if not bbox or len(bbox) != 4 or not all(math.isfinite(float(v)) for v in bbox):
            raise ValueError('Area visibile non valida.')
        west, south, east, north = map(float, bbox)
        if self.bbox:
            west, south = max(west, self.bbox[0]), max(south, self.bbox[1])
            east, north = min(east, self.bbox[2]), min(north, self.bbox[3])
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError('L’area visibile non interseca l’area di ricerca configurata.')
        worker = GeocodingService((west, south, east, north), self.timeout,
                                  self.client.endpoint, self.client.cache_dir)
        worker.use_archive, worker.archive = self.use_archive, self.archive
        worker.municipality_boundary = self.municipality_boundary
        worker.client.max_requests = self.client.max_requests
        result = worker.search_more(query, municipality, lookup_municipality=False)
        if not result.candidates:
            result.error = result.error or 'Nessuna corrispondenza nell’area visibile.'
        return result

