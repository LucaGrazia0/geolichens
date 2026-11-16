"""Lightweight OpenStreetMap trail retrieval for GeoLichen.

The implementation follows the same high-level workflow used by QuickOSM:
construct an Overpass query, download OSM data, parse ways, and expose them as
QGIS vector features.  It intentionally does not depend on QuickOSM.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Optional

from ..core.qgis_compat import FieldType, GeometryType
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsLineSymbol,
)

from ._shared_geo_utils import local_metric_crs
from .overpass_transport import download_overpass


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
    CACHE_VERSION = "osm_trails_v3_buffer_clip"
    ARCHIVE_MAX_AGE_HOURS = 30 * 24
    FAILURE_RETRY_SECONDS = 60
    _recent_failures = {}
    FALLBACK_ENDPOINTS = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    )

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_s: int = 25,
        query_margin_m: float = 50.0,
        max_area_km2: float = 150.0,
        cache_ttl_hours: float = 24.0,
        wait_timeout_s: float = 60.0,
    ):
        self.endpoint = str(endpoint or self.DEFAULT_ENDPOINT)
        self.endpoints = tuple(dict.fromkeys((self.endpoint,) + self.FALLBACK_ENDPOINTS))
        self.timeout_s = max(5, int(timeout_s or 25))
        # Queue time and transfer are separate from the declared query runtime.
        self.wait_timeout_s = max(self.timeout_s + 2.0, float(wait_timeout_s))
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
            clip_geometry = QgsGeometry(geom_wgs)
            if clip_geometry.type() != GeometryType.Polygon:
                return self._failure("I sentieri richiedono un’area buffer poligonale", started)
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
            archive_notice = None
            if payload is None:
                failure = self._recent_failures.get(cache_path)
                if failure and time.monotonic() < failure[0]:
                    payload, error, endpoint_used = None, failure[1], self.endpoint
                    remaining = max(1, math.ceil(failure[0] - time.monotonic()))
                    error += f" Nuovo tentativo per quest'area tra {remaining} s."
                else:
                    payload, error, endpoint_used = self._download(query)
                if error:
                    # Only the identical query may recover an older complete
                    # response. Never reset its age or cache a failed request.
                    if not failure or time.monotonic() >= failure[0]:
                        self._recent_failures[cache_path] = (time.monotonic() + self.FAILURE_RETRY_SECONDS, error)
                        if len(self._recent_failures) > 128:
                            oldest = min(self._recent_failures, key=lambda key: self._recent_failures[key][0])
                            self._recent_failures.pop(oldest, None)
                    payload = self._read_cache(cache_path, allow_expired=True)
                    if payload is None:
                        return self._failure(error, started, bbox=bbox)
                    from_cache = True
                    age_hours = max(0.0, (time.time() - os.path.getmtime(cache_path)) / 3600.0)
                    archive_notice = (f"Overpass non disponibile: usato archivio locale di {age_hours / 24:.1f} giorni "
                                      f"per la stessa area, non aggiornato. {error}")
                else:
                    self._recent_failures.pop(cache_path, None)
                    self.endpoint = endpoint_used or self.endpoint
                    self._write_cache(cache_path, payload)

            # Every response, including an archived one, is clipped again.
            layer, count, warning = self._parse_to_layer(payload, clip_geometry)
            if archive_notice:
                warning = " ".join(text for text in (archive_notice, warning) if text)
                if layer is not None:
                    layer.setCustomProperty('geolichen/osm_archive_fallback', True)
                    layer.setCustomProperty('geolichen/osm_archive_age_hours', age_hours)
                    layer.setCustomProperty('geolichen/osm_archive_warning', archive_notice)

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

    def _download(self, query):
        return download_overpass(query, self.endpoints, self.timeout_s,
                                 wait_timeout_s=self.wait_timeout_s)

    def _parse_to_layer(self, payload, clip_geometry=None):
        if not isinstance(payload, dict):
            return None, 0, "Risposta OSM non riconosciuta"
        elements = payload.get("elements") or []
        layer = QgsVectorLayer("LineString?crs=EPSG:4326", "GeoLichen – Sentieri OSM nel buffer", "memory")
        layer.setCustomProperty('geolichen/temporary_osm_trails', True)
        if not layer.isValid():
            return None, 0, "Impossibile creare il layer temporaneo OSM"

        fields = [
            QgsField("osm_id", FieldType.LongLong),
            QgsField("highway", FieldType.String),
            QgsField("trail_class", FieldType.String),
            QgsField("name", FieldType.String),
            QgsField("ref", FieldType.String),
            QgsField("surface", FieldType.String),
            QgsField("tracktype", FieldType.String),
            QgsField("sac_scale", FieldType.String),
            QgsField("trail_visibility", FieldType.String),
            QgsField("access", FieldType.String),
            QgsField("foot", FieldType.String),
            QgsField("bicycle", FieldType.String),
            QgsField("horse", FieldType.String),
            QgsField("incline", FieldType.String),
            QgsField("bridge", FieldType.String),
            QgsField("tunnel", FieldType.String),
            QgsField("source", FieldType.String),
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
                    lon, lat = float(item['lon']), float(item['lat'])
                    if not (math.isfinite(lon) and math.isfinite(lat)
                            and -180 <= lon <= 180 and -90 <= lat <= 90):
                        raise ValueError('Invalid OSM coordinates')
                    points.append(QgsPointXY(lon, lat))
                except Exception:
                    # Do not connect points across a corrupt/missing segment.
                    points = []
                    break
            if len(points) < 2:
                invalid += 1
                continue
            geom = QgsGeometry.fromPolylineXY(points)
            if geom is None or geom.isEmpty():
                invalid += 1
                continue
            if clip_geometry is not None:
                geom = geom.intersection(clip_geometry)
            parts = self._line_parts(geom)
            attributes = [
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
            ]
            for part in parts:
                feat = QgsFeature(layer.fields())
                feat.setGeometry(part)
                feat.setAttributes(attributes)
                features.append(feat)

        if features:
            provider.addFeatures(features)
            layer.updateExtents()
        warning = None
        if invalid:
            warning = f"{invalid} way OSM prive di geometria valida sono state ignorate"
        self.style_trail_layer(layer)
        return layer, len(features), warning

    @staticmethod
    def style_trail_layer(layer):
        """Distinguish mapped walking paths, tracks and access roads visually.

        OSM tags and analytical distances are preserved. A track is not relabelled
        as a footpath, and an access road is not presented as a hiking trail.
        """
        categories = []
        present = {str(feature['highway']) for feature in layer.getFeatures()}
        styles = (
            ("path", "Sentiero (path)", "#8e24aa", "0.8", "dash"),
            ("footway", "Percorso pedonale (footway)", "#8e24aa", "0.8", "dash"),
            ("bridleway", "Percorso equestre (bridleway)", "#8e24aa", "0.8", "dash"),
            ("steps", "Scalinata (steps)", "#8e24aa", "0.8", "dot"),
            ("pedestrian", "Area/strada pedonale (pedestrian)", "#8e24aa", "0.8", "solid"),
            ("track", "Pista agricola/forestale (track)", "#a66b28", "0.65", "dash"),
            ("service", "Strada di servizio (service)", "#526474", "0.4", "solid"),
            ("living_street", "Strada residenziale (living_street)", "#526474", "0.4", "solid"),
        )
        for value, label, color, width, style in styles:
            if value not in present:
                continue
            symbol = QgsLineSymbol.createSimple({
                "line_color": color, "line_width": width, "line_style": style,
            })
            categories.append(QgsRendererCategory(value, symbol, label))
        layer.setRenderer(QgsCategorizedSymbolRenderer("highway", categories))
        layer.triggerRepaint()

    @staticmethod
    def layer_summary(layer):
        """Count clipped segments, not distinct OSM ways or verified routes."""
        counts = {"walking": 0, "track": 0, "road": 0}
        if layer is None or "highway" not in layer.fields().names():
            return "OSM: classificazione dei percorsi non disponibile."
        for feature in layer.getFeatures():
            value = str(feature["highway"])
            if value in ("path", "footway", "bridleway", "steps", "pedestrian"):
                counts["walking"] += 1
            elif value == "track":
                counts["track"] += 1
            elif value in ("service", "living_street"):
                counts["road"] += 1
        summary = (f"OSM nel buffer — percorsi pedonali/equestri: {counts['walking']}; "
                   f"piste: {counts['track']}; strade di accesso: {counts['road']} (segmenti).")
        if not counts["walking"]:
            summary += " Nessun sentiero pedonale restituito da OSM nell’area."
        return summary

    @staticmethod
    def _line_parts(geometry):
        """Keep line segments; ignore point-only boundary contacts and empty clips."""
        if geometry is None or geometry.isEmpty():
            return []
        if geometry.isMultipart():
            return [part for child in geometry.asGeometryCollection()
                    for part in OsmTrailService._line_parts(child)]
        if geometry.type() == GeometryType.Line and geometry.length() > 0:
            return [geometry]
        return []

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

    def _read_cache(self, path, allow_expired=False):
        if self.cache_ttl_hours <= 0 or not os.path.exists(path):
            return None
        try:
            age_h = (time.time() - os.path.getmtime(path)) / 3600.0
            max_age = self.ARCHIVE_MAX_AGE_HOURS if allow_expired else self.cache_ttl_hours
            if age_h < 0 or age_h > max_age:
                return None
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list) or payload.get("remark"):
                return None
            return payload
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
