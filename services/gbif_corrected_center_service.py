import math
import random

from ._shared_geo_utils import coerce_geometry as _shared_coerce_geometry
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry,
    QgsPointXY, QgsProject,
)


class GbifCorrectedCenterService:
    """Calcola il corrected center documentale richiesto dal metodo point-radius.

    Il risultato non sostituisce mai il punto ecologico selezionato dal GSS.
    Le geometrie sono attese in WGS84, coerentemente con il resto della pipeline.
    """

    def calculate(self, locality_context, original_locality_extent, selected_point=None):
        locality_type = str(getattr(locality_context, "locality_type", "unknown") or "unknown")
        geometry_type = str(getattr(locality_context, "geometry_type", "unknown") or "unknown")
        geocoded_center = self._point(getattr(locality_context, "geocoded_center", None))
        selected = self._point(selected_point)

        # Punto + buffer manuale: il punto cliccato è il centro tecnico della
        # geometria operativa, non una coordinata dichiarata del reperto.
        # Deve restare separato dal punto ecologico Rank 1.
        manual_mode_name = str(getattr(locality_context, "search_geometry_mode", "") or "").casefold()
        manual_mode = manual_mode_name.startswith("manual")
        manual_center = self._point(getattr(locality_context, "manual_search_center_wgs84", None))
        if manual_mode and manual_center is not None:
            return self._result(
                manual_center,
                ("manual_line_midpoint" if manual_mode_name == "manual_line" else "manual_buffer_center"),
                "manual_search_center",
                ("Punto a metà della linea manuale usato come centro tecnico del corridoio; "
                 if manual_mode_name == "manual_line" else
                 "Centro tecnico scelto dall’operatore per il buffer manuale; ")
                + "non coincide necessariamente con il punto ecologico selezionato.",
                locality_type, geometry_type,
            )

        # Coordinate esplicite del record: il punto dichiarato è il centro corretto.
        if locality_type == "coordinates" and (geocoded_center or selected):
            point = geocoded_center or selected
            return self._result(
                point, "declared_coordinate", "record_coordinate",
                "La località è espressa come coordinate; il punto dichiarato è il corrected center.",
                locality_type, geometry_type,
            )

        geom = self._geometry(original_locality_extent)

        # A semantic POINT may carry a documentary bbox. In that case the bbox
        # is the feature representation and must determine the corrected center.
        extent_is_point = False
        if geom is not None:
            try:
                extent_is_point = int(geom.type()) == 0
            except Exception:
                extent_is_point = False
        if geometry_type == "point" and extent_is_point and geocoded_center is not None:
            return self._result(
                geocoded_center, "geocoder_feature_center", "geocoder",
                "Il riferimento è un punto privo di estensione; viene usato il centro della fonte.",
                locality_type, geometry_type,
            )

        if geom is not None:
            minimum_center = self._minimum_enclosing_center_wgs84(geom, geocoded_center or selected)
            if minimum_center is not None:
                return self._result(
                    minimum_center, "minimum_enclosing_circle_center", "original_locality_extent",
                    "Centro del più piccolo cerchio calcolato per contenere l'intera geometria documentale.",
                    locality_type, geometry_type,
                )

            # Conservative fallback if the minimum enclosing circle cannot be
            # computed with the available geometry.
            try:
                centroid_geom = geom.centroid()
                if centroid_geom and not centroid_geom.isEmpty():
                    centroid = QgsPointXY(centroid_geom.asPoint())
                    return self._result(
                        centroid, "centroid_fallback", "original_locality_extent",
                        "Cerchio minimo non calcolabile; usato il centroide come fallback dichiarato.",
                        locality_type, geometry_type,
                    )
            except Exception:
                pass

        # Fallback documentato: geocoder, poi punto ecologico, senza alterarli.
        if geocoded_center is not None:
            return self._result(
                geocoded_center, "geocoder_center_fallback", "geocoder",
                "Estensione originale non utilizzabile; usato il centro del geocoder.",
                locality_type, geometry_type,
            )
        if selected is not None:
            return self._result(
                selected, "selected_point_fallback", "ecological_point",
                "Centro documentale non calcolabile; fallback esplicito al punto ecologico.",
                locality_type, geometry_type,
            )
        return {
            "corrected_center": None,
            "corrected_center_lon": None,
            "corrected_center_lat": None,
            "corrected_center_method": "not_calculable",
            "corrected_center_source": "none",
            "corrected_center_reason": "Nessuna geometria o coordinata disponibile.",
            "locality_type": locality_type,
            "geometry_type": geometry_type,
            "corrected_center_calculable": False,
        }


    def _minimum_enclosing_center_wgs84(self, geometry, hint_point=None):
        """Return the centre of a deterministic minimum enclosing circle.

        Vertices are transformed to a local metric CRS. The randomized
        incremental algorithm is deterministic through a fixed seed and works
        on the convex hull to keep complex polygons responsive.
        """
        try:
            anchor = hint_point
            if anchor is None:
                anchor = QgsPointXY(geometry.boundingBox().center())
            lon, lat = float(anchor.x()), float(anchor.y())
            zone = max(1, min(60, int((lon + 180.0) / 6.0) + 1))
            epsg = (32600 if lat >= 0 else 32700) + zone
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            metric = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
            forward = QgsCoordinateTransform(wgs84, metric, QgsProject.instance())
            reverse = QgsCoordinateTransform(metric, wgs84, QgsProject.instance())
            work = QgsGeometry(geometry)
            try:
                work = work.convexHull()
            except Exception:
                pass
            work.transform(forward)
            points = [(float(v.x()), float(v.y())) for v in work.vertices()]
            if not points:
                return None
            circle = self._minimum_enclosing_circle(points)
            if circle is None:
                return None
            center_metric = QgsPointXY(circle[0], circle[1])
            return QgsPointXY(reverse.transform(center_metric))
        except Exception:
            return None

    @classmethod
    def _minimum_enclosing_circle(cls, points):
        pts = list(dict.fromkeys(points))
        random.Random(0).shuffle(pts)
        circle = None
        for i, p in enumerate(pts):
            if circle is None or not cls._inside_circle(p, circle):
                circle = (p[0], p[1], 0.0)
                for j, q in enumerate(pts[:i]):
                    if not cls._inside_circle(q, circle):
                        circle = cls._circle_two_points(p, q)
                        for r in pts[:j]:
                            if not cls._inside_circle(r, circle):
                                candidate = cls._circle_three_points(p, q, r)
                                if candidate is not None:
                                    circle = candidate
        return circle

    @staticmethod
    def _inside_circle(point, circle):
        if circle is None:
            return False
        return math.hypot(point[0] - circle[0], point[1] - circle[1]) <= circle[2] + 1e-7

    @staticmethod
    def _circle_two_points(a, b):
        cx, cy = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        return cx, cy, math.hypot(a[0] - b[0], a[1] - b[1]) / 2.0

    @staticmethod
    def _circle_three_points(a, b, c):
        d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        if abs(d) < 1e-12:
            return None
        ux = ((a[0] ** 2 + a[1] ** 2) * (b[1] - c[1]) + (b[0] ** 2 + b[1] ** 2) * (c[1] - a[1]) + (c[0] ** 2 + c[1] ** 2) * (a[1] - b[1])) / d
        uy = ((a[0] ** 2 + a[1] ** 2) * (c[0] - b[0]) + (b[0] ** 2 + b[1] ** 2) * (a[0] - c[0]) + (c[0] ** 2 + c[1] ** 2) * (b[0] - a[0])) / d
        return ux, uy, math.hypot(ux - a[0], uy - a[1])

    @staticmethod
    def _geometry(value):
        return _shared_coerce_geometry(value)

    @staticmethod
    def _point(value):
        if value is None:
            return None
        try:
            if isinstance(value, QgsPointXY):
                return QgsPointXY(value)
            if hasattr(value, "x") and hasattr(value, "y"):
                return QgsPointXY(float(value.x()), float(value.y()))
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                return QgsPointXY(float(value[0]), float(value[1]))
        except Exception:
            return None
        return None

    @staticmethod
    def _result(point, method, source, reason, locality_type, geometry_type):
        return {
            "corrected_center": point,
            "corrected_center_lon": float(point.x()),
            "corrected_center_lat": float(point.y()),
            "corrected_center_method": method,
            "corrected_center_source": source,
            "corrected_center_reason": reason,
            "locality_type": locality_type,
            "geometry_type": geometry_type,
            "corrected_center_calculable": True,
        }
