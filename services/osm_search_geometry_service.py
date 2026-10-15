"""OpenStreetMap geometry resolver for the initial GeoLichen SearchGeometry.

This is a deliberately small extraction of the workflow used by QuickOSM:
Overpass query -> OSM elements -> QGIS geometries.  It does not depend on
QuickOSM and is used only before the semantic-buffer fallback is applied.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (
    QgsApplication,
    QgsBlockingNetworkRequest,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
)

from ._shared_geo_utils import local_metric_crs


@dataclass
class OsmSearchGeometryResult:
    success: bool
    geometry: Optional[QgsGeometry] = None
    geometry_type: str = ""
    osm_type: str = ""
    osm_id: int = 0
    name: str = ""
    tags: Optional[dict] = None
    strategy: str = ""
    from_cache: bool = False
    endpoint: str = ""
    match_score: float = 0.0
    anchor_distance_m: Optional[float] = None
    error: Optional[str] = None


class OsmSearchGeometryService:
    """Resolve a named locality to an OSM geometry near a geocoder anchor."""

    DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
    CACHE_VERSION = "osm_search_geometry_v3_robust"
    FALLBACK_ENDPOINTS = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.nchc.org.tw/api/interpreter",
    )

    TAG_FILTERS = {
        "municipality": (
            '["boundary"="administrative"]',
        ),
        "forest": (
            '["natural"="wood"]', '["landuse"="forest"]',
        ),
        "lake": (
            '["natural"="water"]', '["water"="lake"]', '["landuse"="reservoir"]',
        ),
        "meadow": (
            '["landuse"="meadow"]', '["natural"="grassland"]',
        ),
        "glacier": ('["natural"="glacier"]',),
        "river": (
            '["waterway"="river"]', '["waterway"="stream"]',
        ),
        "trail": (
            '["highway"="path"]', '["highway"="track"]',
            '["highway"="footway"]', '["highway"="bridleway"]',
        ),
        "road": (
            '["highway"="unclassified"]', '["highway"="service"]',
            '["highway"="residential"]', '["highway"="tertiary"]',
        ),
        "ridge": ('["natural"="ridge"]',),
        "peak": ('["natural"="peak"]',),
        "hill": ('["natural"="peak"]', '["natural"="hill"]'),
        "pass": ('["mountain_pass"="yes"]', '["natural"="saddle"]'),
        "refuge": (
            '["tourism"="alpine_hut"]', '["tourism"="wilderness_hut"]',
            '["amenity"="shelter"]',
        ),
        "church": ('["amenity"="place_of_worship"]', '["building"="church"]'),
        "mountain": (
            '["natural"="peak"]', '["natural"="ridge"]', '["place"="mountain"]',
        ),
        "mountain_group": (
            '["place"="mountain_range"]', '["natural"="ridge"]',
        ),
        "valley": ('["natural"="valley"]',),
        "generic_locality": (
            '["place"]', '["natural"]', '["tourism"]',
        ),
    }

    POLYGON_TYPES = {"municipality", "forest", "lake", "meadow", "glacier", "mountain", "mountain_group"}
    LINE_TYPES = {"river", "trail", "road", "ridge", "valley"}

    # Query only OSM primitive types that can realistically provide the
    # expected geometry. This substantially reduces Overpass work compared
    # with asking node/way/relation for every tag.
    OBJECT_TYPES = {
        "municipality": ("relation", "way"),
        "forest": ("way", "relation"),
        "lake": ("way", "relation"),
        "meadow": ("way", "relation"),
        "glacier": ("way", "relation"),
        "river": ("way", "relation"),
        "trail": ("way",),
        "road": ("way",),
        "ridge": ("way", "relation"),
        "valley": ("way", "relation", "node"),
        "peak": ("node",),
        "hill": ("node", "way"),
        "pass": ("node",),
        "refuge": ("node", "way"),
        "church": ("node", "way", "relation"),
        "mountain": ("node", "way", "relation"),
        "mountain_group": ("relation", "way", "node"),
        "generic_locality": ("node", "way", "relation"),
    }

    def __init__(self, endpoint=DEFAULT_ENDPOINT, timeout_s=5, cache_ttl_hours=24.0):
        self.endpoint = str(endpoint or self.DEFAULT_ENDPOINT)
        self.endpoints = tuple(dict.fromkeys((self.endpoint,) + self.FALLBACK_ENDPOINTS))
        # Keep the lookup responsive, while allowing one short fallback request.
        self.timeout_s = max(3, min(8, int(timeout_s or 5)))
        self.cache_ttl_hours = max(0.0, float(cache_ttl_hours or 24.0))

    def resolve(self, name, canonical_type, anchor_geometry, source_crs=None, search_radius_m=3000.0):
        started = time.monotonic()
        try:
            if anchor_geometry is None or anchor_geometry.isEmpty():
                return OsmSearchGeometryResult(False, error="Anchor geocodificato assente")
            canonical_type = str(canonical_type or "generic_locality")
            filters = self.TAG_FILTERS.get(canonical_type, self.TAG_FILTERS["generic_locality"])
            clean_name = str(name or "").strip()
            if not clean_name:
                return OsmSearchGeometryResult(False, error="Nome località assente")

            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            source_crs = source_crs or wgs84
            anchor_wgs = self._transform(anchor_geometry, source_crs, wgs84)
            center = anchor_wgs.centroid().asPoint()
            metric = local_metric_crs(center)
            anchor_m = self._transform(anchor_wgs, wgs84, metric)
            radius = max(250.0, min(float(search_radius_m or 3000.0), 12000.0))
            name_variants = self._name_variants(clean_name, canonical_type)
            query = self.build_query(name_variants, filters, center.y(), center.x(), radius, canonical_type)
            cache_path = self._cache_path(clean_name, canonical_type, center.x(), center.y(), radius, query)
            payload = self._read_cache(cache_path)
            from_cache = payload is not None
            endpoint_used = "cache" if from_cache else ""
            if payload is None:
                payload, error, endpoint_used = self._download(query)
                if error:
                    return OsmSearchGeometryResult(False, from_cache=False, endpoint=endpoint_used, error=error)
                self._write_cache(cache_path, payload)

            candidates = self._parse_candidates(payload, canonical_type)
            if not candidates:
                return OsmSearchGeometryResult(False, from_cache=from_cache, endpoint=endpoint_used, error="Nessuna geometria OSM compatibile")

            target_names = [self._normalise_name(v) for v in name_variants if v]
            best = None
            best_score = -1e9
            best_distance = None
            for candidate in candidates:
                geom = candidate["geometry"]
                geom_m = self._transform(geom, wgs84, metric)
                if geom_m is None or geom_m.isEmpty():
                    continue
                distance = anchor_m.distance(geom_m)
                candidate_names = candidate.get("names") or [candidate.get("name") or ""]
                name_score = 0.0
                for target in target_names:
                    for candidate_name in candidate_names:
                        name_score = max(name_score, self._name_similarity(target, self._normalise_name(candidate_name)))
                geom_bonus = self._geometry_bonus(canonical_type, geom)
                tag_bonus = self._tag_compatibility(canonical_type, candidate.get("tags") or {})
                distance_score = max(0.0, 1.0 - distance / max(radius, 1.0))
                score = name_score * 0.62 + distance_score * 0.23 + geom_bonus * 0.08 + tag_bonus * 0.07
                # A nearby strongly compatible OSM object may have only an alt/local name.
                if name_score < 0.28 and distance > min(180.0, radius * 0.08):
                    continue
                if score > best_score:
                    best_score = score
                    best_distance = float(distance)
                    best = candidate

            if best is None:
                return OsmSearchGeometryResult(False, from_cache=from_cache, endpoint=endpoint_used, error="Nessuna corrispondenza OSM affidabile")

            geom = QgsGeometry(best["geometry"])
            return OsmSearchGeometryResult(
                True,
                geometry=geom,
                geometry_type=self._geometry_type(geom),
                osm_type=str(best.get("type") or ""),
                osm_id=int(best.get("id") or 0),
                name=str(best.get("name") or clean_name),
                tags=dict(best.get("tags") or {}),
                strategy=f"osm_{canonical_type}_{self._geometry_type(geom).lower()}",
                from_cache=from_cache,
                endpoint=endpoint_used,
                match_score=float(best_score),
                anchor_distance_m=best_distance,
            )
        except Exception as exc:
            return OsmSearchGeometryResult(False, error=str(exc))

    def build_query(self, names, filters, lat, lon, radius_m, canonical_type="generic_locality"):
        names = names if isinstance(names, (list, tuple)) else [names]
        name_keys = ("name", "name:it", "official_name", "short_name", "alt_name", "loc_name", "old_name")
        clauses = []
        object_types = self.OBJECT_TYPES.get(canonical_type, self.OBJECT_TYPES["generic_locality"])
        seen = set()
        for raw_name in names[:4]:
            escaped = re.escape(str(raw_name).strip())
            if not escaped:
                continue
            for name_key in name_keys:
                name_clause = f'["{name_key}"~"^{escaped}$",i]'
                for filt in filters:
                    for osm_obj in object_types:
                        clause = f"  {osm_obj}{filt}{name_clause}(around:{radius_m:.0f},{lat:.7f},{lon:.7f});"
                        if clause not in seen:
                            seen.add(clause)
                            clauses.append(clause)
        return (
            f"[out:json][timeout:{self.timeout_s}][maxsize:12582912];\n(\n"
            + "\n".join(clauses)
            + "\n);\nout body center geom;"
        )

    def _parse_candidates(self, payload, canonical_type):
        if not isinstance(payload, dict):
            return []
        output = []
        for element in payload.get("elements") or []:
            if not isinstance(element, dict):
                continue
            geom = self._geometry_from_element(element, canonical_type)
            if geom is None or geom.isEmpty():
                continue
            tags = element.get("tags") or {}
            names = []
            for key in ("name", "name:it", "official_name", "short_name", "alt_name", "loc_name", "old_name"):
                value = tags.get(key)
                if value:
                    names.extend(str(value).split(";"))
            names = [value.strip() for value in names if value and value.strip()]
            output.append({
                "geometry": geom,
                "type": element.get("type"),
                "id": element.get("id"),
                "name": names[0] if names else "",
                "names": names,
                "tags": tags,
            })
        return output

    def _geometry_from_element(self, element, canonical_type):
        osm_type = element.get("type")
        if osm_type == "node":
            try:
                return QgsGeometry.fromPointXY(QgsPointXY(float(element["lon"]), float(element["lat"])))
            except Exception:
                center = element.get("center") or {}
                try:
                    return QgsGeometry.fromPointXY(QgsPointXY(float(center["lon"]), float(center["lat"])))
                except Exception:
                    return None

        if osm_type == "way":
            points = self._points(element.get("geometry") or [])
            if len(points) < 2:
                return self._center_geometry(element)
            if canonical_type in self.POLYGON_TYPES and self._closed(points):
                return QgsGeometry.fromPolygonXY([points])
            return QgsGeometry.fromPolylineXY(points)

        if osm_type == "relation":
            member_lines = []
            member_polygons = []
            for member in element.get("members") or []:
                if member.get("role") not in {"", "outer"}:
                    continue
                points = self._points(member.get("geometry") or [])
                if len(points) < 2:
                    continue
                if self._closed(points):
                    member_polygons.append(QgsGeometry.fromPolygonXY([points]))
                else:
                    member_lines.append(QgsGeometry.fromPolylineXY(points))
            if canonical_type in self.POLYGON_TYPES:
                if member_polygons:
                    return QgsGeometry.unaryUnion(member_polygons)
                if member_lines:
                    try:
                        polygons = QgsGeometry.polygonize(member_lines)
                        if polygons is not None and not polygons.isEmpty():
                            return polygons
                    except Exception:
                        pass
            if member_lines:
                return QgsGeometry.unaryUnion(member_lines)
            return self._center_geometry(element)
        return None

    @staticmethod
    def _points(items):
        points = []
        for item in items:
            try:
                points.append(QgsPointXY(float(item["lon"]), float(item["lat"])))
            except Exception:
                continue
        return points

    @staticmethod
    def _closed(points):
        if len(points) < 4:
            return False
        return abs(points[0].x() - points[-1].x()) < 1e-9 and abs(points[0].y() - points[-1].y()) < 1e-9

    @staticmethod
    def _center_geometry(element):
        center = element.get("center") or {}
        try:
            return QgsGeometry.fromPointXY(QgsPointXY(float(center["lon"]), float(center["lat"])))
        except Exception:
            return None

    @staticmethod
    def _geometry_type(geometry):
        try:
            return {0: "POINT", 1: "LINE", 2: "POLYGON"}.get(int(geometry.type()), "UNKNOWN")
        except Exception:
            return "UNKNOWN"

    def _geometry_bonus(self, canonical_type, geometry):
        geom_type = self._geometry_type(geometry)
        if canonical_type in self.POLYGON_TYPES:
            return 1.0 if geom_type == "POLYGON" else 0.25
        if canonical_type in self.LINE_TYPES:
            return 1.0 if geom_type == "LINE" else 0.25
        return 1.0 if geom_type == "POINT" else 0.65

    @classmethod
    def _name_variants(cls, value, canonical_type):
        raw = str(value or "").strip()
        variants = [raw]
        # Geocoder labels can contain administrative suffixes; OSM usually stores only the toponym.
        if "," in raw:
            variants.append(raw.split(",", 1)[0].strip())
        prefixes = {
            "mountain": ("monte ", "montagna ", "mt. "),
            "peak": ("cima ", "vetta ", "pizzo ", "punta ", "corno "),
            "pass": ("passo ", "forcella ", "sella ", "colle "),
            "lake": ("lago ",),
            "forest": ("bosco ", "foresta ", "selva "),
            "valley": ("valle ", "val di ", "val "),
        }.get(canonical_type, ())
        low = raw.lower()
        for prefix in prefixes:
            if low.startswith(prefix):
                variants.append(raw[len(prefix):].strip())
        result = []
        seen = set()
        for item in variants:
            key = cls._normalise_name(item)
            if key and key not in seen:
                seen.add(key)
                result.append(item)
        return result or [raw]

    def _tag_compatibility(self, canonical_type, tags):
        checks = {
            "municipality": lambda t: t.get("boundary") == "administrative",
            "peak": lambda t: t.get("natural") == "peak",
            "mountain": lambda t: t.get("natural") in {"peak", "ridge"} or t.get("place") == "mountain",
            "mountain_group": lambda t: t.get("place") == "mountain_range" or t.get("natural") == "ridge",
            "pass": lambda t: t.get("mountain_pass") == "yes" or t.get("natural") == "saddle",
            "forest": lambda t: t.get("natural") == "wood" or t.get("landuse") == "forest",
            "lake": lambda t: t.get("natural") == "water" or t.get("water") == "lake" or t.get("landuse") == "reservoir",
            "river": lambda t: t.get("waterway") in {"river", "stream"},
            "trail": lambda t: t.get("highway") in {"path", "track", "footway", "bridleway"},
            "refuge": lambda t: t.get("tourism") in {"alpine_hut", "wilderness_hut"} or t.get("amenity") == "shelter",
        }
        checker = checks.get(canonical_type)
        return 1.0 if checker is None or checker(tags) else 0.0

    @staticmethod
    def _normalise_name(value):
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        return text

    @staticmethod
    def _name_similarity(target, candidate):
        if not target or not candidate:
            return 0.0
        if target == candidate:
            return 1.0
        if target in candidate or candidate in target:
            return 0.90
        return SequenceMatcher(None, target, candidate).ratio()

    @staticmethod
    def _transform(geometry, source_crs, target_crs):
        clone = QgsGeometry(geometry)
        if source_crs == target_crs:
            return clone
        clone.transform(QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance()))
        return clone

    def _download(self, query):
        errors = []
        endpoint_used = ""
        from urllib.parse import quote_plus
        body = QByteArray(("data=" + quote_plus(query)).encode("utf-8"))
        for index, endpoint in enumerate(self.endpoints[:2]):
            endpoint_used = endpoint
            try:
                request = QNetworkRequest(QUrl(endpoint))
                try:
                    request.setTransferTimeout((self.timeout_s + 1) * 1000)
                except Exception:
                    pass
                request.setHeader(QNetworkRequest.ContentTypeHeader, "application/x-www-form-urlencoded; charset=UTF-8")
                blocking = QgsBlockingNetworkRequest()
                result = blocking.post(request, body, forceRefresh=True)
                if result != QgsBlockingNetworkRequest.NoError:
                    errors.append(blocking.errorMessage() or f"Errore richiesta {endpoint}")
                    continue
                reply = blocking.reply()
                if reply is None:
                    errors.append(f"Risposta assente da {endpoint}")
                    continue
                status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                try:
                    status = int(status)
                except Exception:
                    status = 200
                if status >= 400:
                    errors.append(f"HTTP {status} da {endpoint}")
                    continue
                raw = bytes(reply.content())
                if not raw:
                    errors.append(f"Risposta vuota da {endpoint}")
                    continue
                try:
                    return json.loads(raw.decode("utf-8")), None, endpoint
                except Exception as exc:
                    errors.append(f"JSON non valido da {endpoint}: {exc}")
            except Exception as exc:
                errors.append(f"{endpoint}: {exc}")
        return None, "Download Overpass fallito: " + " | ".join(errors[-2:]), endpoint_used

    def _cache_path(self, name, canonical_type, lon, lat, radius, query):
        base = os.path.join(QgsApplication.qgisSettingsDirPath(), "geolichen_cache", "osm_search_geometry")
        os.makedirs(base, exist_ok=True)
        signature = f"{self.CACHE_VERSION}|{canonical_type}|{self._normalise_name(name)}|{lon:.4f}|{lat:.4f}|{radius:.0f}|{query}"
        key = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        return os.path.join(base, key + ".json")

    def _read_cache(self, path):
        if self.cache_ttl_hours <= 0 or not os.path.exists(path):
            return None
        try:
            if (time.time() - os.path.getmtime(path)) / 3600.0 > self.cache_ttl_hours:
                return None
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return None

    @staticmethod
    def _write_cache(path, payload):
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass
