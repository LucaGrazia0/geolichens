"""Advanced GBIF locality geometry engine (Phase 10).

The service converts parsed locality-offset information into a geographic
geometry that can be used by the corrected-center and point-radius pipeline.
It is deliberately conservative: when the source geometry or the relation is
ambiguous, it returns the original extent and records that manual verification
is required rather than inventing a smaller uncertainty.
"""

import math

from ._shared_geo_utils import coerce_geometry as _shared_coerce_geometry
from ._shared_geo_utils import local_metric_crs_epsg_string as _shared_local_metric_crs_str
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
)


class GbifLocalityGeometryService:
    """Build the final locality geometry described by a textual offset."""

    def build(self, locality_context, source_extent):
        geom = self._geometry(source_extent)
        spec = getattr(locality_context, "offset_spec", None) or {}
        kind = str(spec.get("kind") or "").strip()

        if geom is None or not kind:
            return self._result(
                geom, "original_extent", False, False,
                "Nessuna trasformazione geometrica da applicare.", spec,
            )

        center = self._representative_point(geom)
        if center is None:
            return self._result(
                geom, "original_extent_fallback", False, True,
                "Geometria sorgente non utilizzabile; mantenuta l'estensione originale.", spec,
            )

        metric_crs = self._local_metric_crs(center)
        if metric_crs is None:
            return self._result(
                geom, "original_extent_fallback", False, True,
                "Impossibile determinare un CRS metrico locale.", spec,
            )

        metric_geom = self._transform(geom, "EPSG:4326", metric_crs)
        if metric_geom is None:
            return self._result(
                geom, "original_extent_fallback", False, True,
                "Trasformazione metrica non riuscita.", spec,
            )

        precision = max(0.0, self._float(spec.get("distance_precision_m"), 0.0))
        method = ""
        final_metric = None

        if kind == "distance_at_heading":
            distance = max(0.0, self._float(spec.get("distance_m"), 0.0))
            heading = self._float(spec.get("heading_deg"), None)
            if heading is None:
                return self._result(
                    geom, "offset_heading_unresolved", False, True,
                    "Direzione non interpretabile; mantenuta l'estensione originale.", spec,
                )
            dx, dy = self._offset_xy(distance, heading)
            final_metric = QgsGeometry(metric_geom)
            final_metric.translate(dx, dy)
            if precision > 0:
                final_metric = final_metric.buffer(precision, 24)
            method = "gbif_distance_at_heading"

        elif kind == "orthogonal_offsets":
            north = self._float(spec.get("north_m"), 0.0)
            east = self._float(spec.get("east_m"), 0.0)
            final_metric = QgsGeometry(metric_geom)
            final_metric.translate(east, north)
            if precision > 0:
                final_metric = final_metric.buffer(precision, 24)
            method = "gbif_orthogonal_offsets"

        elif kind == "distance_only":
            distance = max(0.0, self._float(spec.get("distance_m"), 0.0))
            # With no heading, every position at the stated distance is
            # possible. The enclosing geometry is therefore the source extent
            # buffered by offset distance plus its stated precision.
            final_metric = metric_geom.buffer(distance + precision, 32)
            method = "gbif_distance_only_conservative_envelope"

        elif kind == "along_path":
            distance = max(0.0, self._float(spec.get("distance_m"), 0.0))
            if metric_geom.type() != 1:  # QgsWkbTypes.LineGeometry
                return self._result(
                    geom, "along_path_requires_line", False, True,
                    "L'offset lungo percorso richiede la geometria lineare del percorso.", spec,
                )
            length = metric_geom.length()
            if length <= 0:
                return self._result(
                    geom, "along_path_invalid_line", False, True,
                    "Il percorso non ha una lunghezza utilizzabile.", spec,
                )
            # Direction along a path is often ambiguous. If a start endpoint is
            # supplied, use it; otherwise include both possible endpoints.
            start_hint = str(spec.get("path_start") or "both").lower()
            positions = []
            if start_hint in {"start", "both"}:
                positions.append(min(distance, length))
            if start_hint in {"end", "both"}:
                positions.append(max(0.0, length - distance))
            points = []
            for pos in positions:
                p = metric_geom.interpolate(pos)
                if p and not p.isEmpty():
                    points.append(p)
            if not points:
                return self._result(
                    geom, "along_path_not_calculable", False, True,
                    "Impossibile interpolare la distanza lungo il percorso.", spec,
                )
            final_metric = points[0]
            for point in points[1:]:
                final_metric = final_metric.combine(point)
            final_metric = final_metric.buffer(max(precision, 1.0), 24)
            method = "gbif_distance_along_path"

        elif kind == "two_distinct_paths":
            path_a = self._geometry(getattr(locality_context, "offset_path_a", None))
            path_b = self._geometry(getattr(locality_context, "offset_path_b", None))
            if path_a is None or path_b is None:
                return self._result(
                    geom, "two_paths_require_geometries", False, True,
                    "Servono le geometrie separate dei due percorsi per calcolare la loro intersezione traslata.", spec,
                )
            result = self._two_path_intersection(path_a, path_b, spec, metric_crs)
            if result is None:
                return self._result(
                    geom, "two_paths_no_intersection", False, True,
                    "Le bande ottenute dai due percorsi non producono un'intersezione valida.", spec,
                )
            final_metric = result
            method = "gbif_distances_from_two_distinct_paths"

        else:
            return self._result(
                geom, "unsupported_offset", False, True,
                f"Tipo di offset non supportato automaticamente: {kind}.", spec,
            )

        final_wgs84 = self._transform(final_metric, metric_crs, "EPSG:4326")
        if final_wgs84 is None or final_wgs84.isEmpty():
            return self._result(
                geom, "offset_geometry_failed", False, True,
                "La geometria finale non è valida; mantenuta l'estensione originale.", spec,
            )
        return self._result(
            final_wgs84, method, True, False,
            "Geometria della località costruita dall'offset testuale secondo un metodo GBIF conservativo.", spec,
        )

    def _two_path_intersection(self, path_a, path_b, spec, metric_crs):
        a = self._transform(path_a, "EPSG:4326", metric_crs)
        b = self._transform(path_b, "EPSG:4326", metric_crs)
        if a is None or b is None:
            return None
        da = max(0.0, self._float(spec.get("distance_a_m"), 0.0))
        db = max(0.0, self._float(spec.get("distance_b_m"), 0.0))
        pa = max(1.0, self._float(spec.get("precision_a_m"), 1.0))
        pb = max(1.0, self._float(spec.get("precision_b_m"), 1.0))
        # A distance from a path defines a band around that path. Without a
        # stated side, both sides remain possible; buffer-minus-inner-buffer
        # represents the conservative distance band.
        band_a = self._distance_band(a, da, pa)
        band_b = self._distance_band(b, db, pb)
        if band_a is None or band_b is None:
            return None
        inter = band_a.intersection(band_b)
        return inter if inter and not inter.isEmpty() else None

    @staticmethod
    def _distance_band(line, distance, precision):
        outer = line.buffer(distance + precision, 24)
        inner_distance = max(0.0, distance - precision)
        if inner_distance <= 0:
            return outer
        inner = line.buffer(inner_distance, 24)
        return outer.difference(inner)

    @staticmethod
    def _offset_xy(distance, heading_deg):
        radians = math.radians(float(heading_deg) % 360.0)
        return distance * math.sin(radians), distance * math.cos(radians)

    @staticmethod
    def _geometry(value):
        return _shared_coerce_geometry(value)

    @staticmethod
    def _representative_point(geom):
        try:
            p = geom.centroid()
            if p and not p.isEmpty():
                return QgsPointXY(p.asPoint())
            p = geom.pointOnSurface()
            if p and not p.isEmpty():
                return QgsPointXY(p.asPoint())
        except Exception:
            return None
        return None

    @staticmethod
    def _local_metric_crs(point):
        return _shared_local_metric_crs_str(point)

    @staticmethod
    def _transform(geom, source, target):
        try:
            source_crs = QgsCoordinateReferenceSystem(source) if isinstance(source, str) else QgsCoordinateReferenceSystem(source)
            target_crs = QgsCoordinateReferenceSystem(target) if isinstance(target, str) else QgsCoordinateReferenceSystem(target)
            transformed = QgsGeometry(geom)
            transformed.transform(QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance()))
            return transformed
        except Exception:
            return None

    @staticmethod
    def _float(value, default=None):
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _result(geometry, method, applied, requires_verification, reason, spec):
        return {
            "final_locality_extent": geometry,
            "locality_geometry_method": method,
            "locality_geometry_applied": bool(applied),
            "locality_geometry_requires_verification": bool(requires_verification),
            "locality_geometry_reason": reason,
            "offset_spec": dict(spec or {}),
        }
