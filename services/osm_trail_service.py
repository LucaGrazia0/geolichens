"""Lightweight OpenStreetMap trail retrieval for GeoLichen.

The implementation follows the same high-level workflow used by QuickOSM:
construct an Overpass query, download OSM data, parse ways, and expose them as
QGIS vector features.  It intentionally does not depend on QuickOSM.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Optional

from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (
    QgsApplication,
    QgsBlockingNetworkRequest,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from ._shared_geo_utils import local_metric_crs


@dataclass
class OsmTrailResult:
    success: bool
    layer: Optional[QgsVectorLayer] = None
    feature_count: int = 0
    source: str = "OpenStreetMap / Overpass API"
    endpoint: str = ""
    query_bbox: Optional[tuple] = None
    elapsed_ms: int = 0
    from_cache: bool = False
    warning: Optional[str] = None
    error: Optional[str] = None


class OsmTrailService:
    """Download and parse OSM trail ways inside an existing SearchGeometry."""

    DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
    HIGHWAY_VALUES = (
        "path",
        "track",
        "footway",
        "bridleway",
        "steps",
        "pedestrian",
        "service",
        "living_street",
    )
    CACHE_VERSION = "osm_trails_v2_robust"
    FALLBACK_ENDPOINTS = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.nchc.org.tw/api/interpreter",
    )

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_s: int = 25,
        query_margin_m: float = 50.0,
        max_area_km2: float = 150.0,
        cache_ttl_hours: float = 24.0,
    ):
        self.endpoint = str(endpoint or self.DEFAULT_ENDPOINT)
        self.endpoints = tuple(dict.fromkeys((self.endpoint,) + self.FALLBACK_ENDPOINTS))
        self.timeout_s = max(5, int(timeout_s or 25))
        self.query_margin_m = max(0.0, float(query_margin_m or 0.0))
        self.max_area_km2 = max(0.1, float(max_area_km2 or 150.0))
        self.cache_ttl_hours = max(0.0, float(cache_ttl_hours or 24.0))

    def fetch(self, search_geometry, source_crs=None) -> OsmTrailResult:
        started = time.monotonic()
        try:
            if search_geometry is None or search_geometry.isEmpty():
                return self._failure("SearchGeometry assente o vuota", started)

            src = source_crs or QgsCoordinateReferenceSystem("EPSG:4326")
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

            geom = QgsGeometry(search_geometry)
            if not geom.isGeosValid():
                try:
                    geom = geom.makeValid()
                except Exception:
                    pass
            if geom is None or geom.isEmpty():
                return self._failure("SearchGeometry non valida", started)

            geom_wgs = self._transform(geom, src, wgs84)
            if geom_wgs is None or geom_wgs.isEmpty():
                return self._failure("Impossibile trasformare la SearchGeometry", started)
            metric = local_metric_crs(geom_wgs.centroid().asPoint())
            geom_m = self._transform(geom_wgs, wgs84, metric)
            if geom_wgs is None or geom_wgs.isEmpty() or geom_m is None or geom_m.isEmpty():
                return self._failure("Impossibile trasformare la SearchGeometry", started)

            if self.query_margin_m > 0:
                geom_m = geom_m.buffer(self.query_margin_m, 8)
                geom_wgs = self._transform(geom_m, metric, wgs84)

            rect_wgs = geom_wgs.boundingBox()
            rect_m = geom_m.boundingBox()
            area_km2 = max(0.0, rect_m.width() * rect_m.height() / 1_000_000.0)
            bbox = (rect_wgs.yMinimum(), rect_wgs.xMinimum(), rect_wgs.yMaximum(), rect_wgs.xMaximum())

            if not self._bbox_plausible(bbox):
                return self._failure("Bounding box OSM non plausibile", started, bbox=bbox)
            if area_km2 > self.max_area_km2:
                return self._failure(
                    f"Area Overpass troppo estesa ({area_km2:.1f} km²; limite {self.max_area_km2:.1f} km²)",
                    started,
                    bbox=bbox,
                )

            query = self.build_query(bbox)
            cache_path = self._cache_path(bbox, query)
            payload = self._read_cache(cache_path)
            from_cache = payload is not None
            if payload is None:
                payload, error, endpoint_used = self._download(query)
                if error:
                    return self._failure(error, started, bbox=bbox)
                self.endpoint = endpoint_used or self.endpoint
                self._write_cache(cache_path, payload)

            layer, count, warning = self._parse_to_layer(payload)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if layer is None:
                return OsmTrailResult(
                    success=False,
                    layer=None,
                    feature_count=0,
                    endpoint=self.endpoint,
                    query_bbox=bbox,
                    elapsed_ms=elapsed_ms,
                    from_cache=from_cache,
                    warning=warning,
                    error=warning or "Nessuna geometria sentieristica valida",
                )
            return OsmTrailResult(
                success=True,
                layer=layer,
                feature_count=count,
                endpoint=self.endpoint,
                query_bbox=bbox,
                elapsed_ms=elapsed_ms,
                from_cache=from_cache,
                warning=warning,
            )
        except Exception as exc:
            return self._failure(str(exc), started)

    def build_query(self, bbox: tuple) -> str:
        south, west, north, east = bbox
        bbox_text = f"{south:.7f},{west:.7f},{north:.7f},{east:.7f}"
        clauses = "\n".join(
            f'  way["highway"="{value}"]({bbox_text});' for value in self.HIGHWAY_VALUES
        )
        return (
            f"[out:json][timeout:{self.timeout_s}];\n"
            "(\n"
            f"{clauses}\n"
            ");\n"
            "out tags geom;"
        )

    def _download(self, query: str):
        errors = []
        endpoint_used = ""
        body = QByteArray(("data=" + self._urlencode(query)).encode("utf-8"))
        for endpoint in self.endpoints[:2]:
            endpoint_used = endpoint
            try:
                request = QNetworkRequest(QUrl(endpoint))
                try:
                    request.setTransferTimeout((self.timeout_s + 2) * 1000)
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

    @staticmethod
    def _urlencode(text: str) -> str:
        from urllib.parse import quote_plus
        return quote_plus(text)

    def _parse_to_layer(self, payload):
        if not isinstance(payload, dict):
            return None, 0, "Risposta OSM non riconosciuta"
        elements = payload.get("elements") or []
        layer = QgsVectorLayer("LineString?crs=EPSG:4326", "GeoLichen – OSM Trails", "memory")
        if not layer.isValid():
            return None, 0, "Impossibile creare il layer temporaneo OSM"

        fields = [
            QgsField("osm_id", QVariant.LongLong),
            QgsField("highway", QVariant.String),
            QgsField("trail_class", QVariant.String),
            QgsField("name", QVariant.String),
            QgsField("ref", QVariant.String),
            QgsField("surface", QVariant.String),
            QgsField("tracktype", QVariant.String),
            QgsField("sac_scale", QVariant.String),
            QgsField("trail_visibility", QVariant.String),
            QgsField("access", QVariant.String),
            QgsField("foot", QVariant.String),
            QgsField("bicycle", QVariant.String),
            QgsField("horse", QVariant.String),
            QgsField("incline", QVariant.String),
            QgsField("bridge", QVariant.String),
            QgsField("tunnel", QVariant.String),
            QgsField("source", QVariant.String),
        ]
        provider = layer.dataProvider()
        provider.addAttributes(fields)
        layer.updateFields()

        features = []
        invalid = 0
        for element in elements:
            if not isinstance(element, dict) or element.get("type") != "way":
                continue
            tags = element.get("tags") or {}
            highway = str(tags.get("highway") or "")
            if highway not in self.HIGHWAY_VALUES:
                continue
            coords = element.get("geometry") or []
            points = []
            for item in coords:
                try:
                    points.append(QgsPointXY(float(item["lon"]), float(item["lat"])))
                except Exception:
                    continue
            if len(points) < 2:
                invalid += 1
                continue
            geom = QgsGeometry.fromPolylineXY(points)
            if geom is None or geom.isEmpty():
                invalid += 1
                continue
            feat = QgsFeature(layer.fields())
            feat.setGeometry(geom)
            feat.setAttributes([
                int(element.get("id") or 0),
                highway,
                self.classify_osm_trail(tags),
                str(tags.get("name") or ""),
                str(tags.get("ref") or ""),
                str(tags.get("surface") or ""),
                str(tags.get("tracktype") or ""),
                str(tags.get("sac_scale") or ""),
                str(tags.get("trail_visibility") or ""),
                str(tags.get("access") or ""),
                str(tags.get("foot") or ""),
                str(tags.get("bicycle") or ""),
                str(tags.get("horse") or ""),
                str(tags.get("incline") or ""),
                str(tags.get("bridge") or ""),
                str(tags.get("tunnel") or ""),
                "© OpenStreetMap contributors",
            ])
            features.append(feat)

        if features:
            provider.addFeatures(features)
            layer.updateExtents()
        warning = None
        if invalid:
            warning = f"{invalid} way OSM prive di geometria valida sono state ignorate"
        return layer, len(features), warning

    @staticmethod
    def classify_osm_trail(tags: dict) -> str:
        highway = str((tags or {}).get("highway") or "").lower()
        if highway in {"path", "track", "footway", "bridleway", "steps", "pedestrian", "service"}:
            return highway
        if highway == "living_street":
            return "other_access"
        return "other_access"

    @staticmethod
    def _transform(geometry, source_crs, target_crs):
        if geometry is None:
            return None
        clone = QgsGeometry(geometry)
        if source_crs == target_crs:
            return clone
        transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
        clone.transform(transform)
        return clone

    @staticmethod
    def _bbox_plausible(bbox):
        try:
            south, west, north, east = [float(v) for v in bbox]
            return -90 <= south < north <= 90 and -180 <= west < east <= 180
        except Exception:
            return False

    def _cache_path(self, bbox, query):
        base = os.path.join(QgsApplication.qgisSettingsDirPath(), "geolichen_cache", "osm_trails")
        os.makedirs(base, exist_ok=True)
        rounded = tuple(round(float(v), 5) for v in bbox)
        key = hashlib.sha256((self.CACHE_VERSION + repr(rounded) + query).encode("utf-8")).hexdigest()
        return os.path.join(base, key + ".json")

    def _read_cache(self, path):
        if self.cache_ttl_hours <= 0 or not os.path.exists(path):
            return None
        try:
            age_h = (time.time() - os.path.getmtime(path)) / 3600.0
            if age_h > self.cache_ttl_hours:
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

    def _failure(self, message, started, bbox=None):
        return OsmTrailResult(
            success=False,
            endpoint=self.endpoint,
            query_bbox=bbox,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error=str(message),
        )
