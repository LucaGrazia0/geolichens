import math

from ._shared_geo_utils import local_metric_crs as _shared_local_metric_crs
from ._shared_geo_utils import to_float as _shared_to_float
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
)


class GbifGeoreferencingService:
    """Calcola la componente geografica point-radius separata dal GSS.

    L'area usata deve essere ``original_locality_extent``: i filtri ecologici
    inferiti possono ordinare i candidati, ma non riducono questa geometria.
    """

    def estimate(
        self,
        corrected_center,
        original_locality_extent,
        grid_step_m=100,
        source_error_m=0,
        coordinate_error_m=0,
        measurement_error_m=0,
        datum_error_m=0,
    ):
        if corrected_center is None:
            return self._not_calculable("corrected_center_missing")
        if original_locality_extent is None or original_locality_extent.isEmpty():
            return self._not_calculable("original_locality_extent_missing")

        # Sprint 2: la discretizzazione della griglia descrive esclusivamente
        # la risoluzione numerica del candidato. Non rappresenta l'incertezza
        # geografica della località e non entra in coordinateUncertaintyInMeters.
        grid_step_diagnostic = self._nonnegative_float(grid_step_m, 100.0)
        candidate_resolution = grid_step_diagnostic / math.sqrt(2.0)
        geographic_radial = self.max_distance_to_geometry_m(
            corrected_center, original_locality_extent
        )
        if geographic_radial is None:
            return self._not_calculable("geographic_radial_failed")

        source_error = self._nonnegative_float(source_error_m, 0.0)
        coordinate_error = self._nonnegative_float(coordinate_error_m, 0.0)
        measurement_error = self._nonnegative_float(measurement_error_m, 0.0)
        datum_error = self._nonnegative_float(datum_error_m, 0.0)

        # Le componenti di errore indipendenti vengono combinate in quadratura
        # (root-sum-of-squares), mantenendo il raggio geografico come limite
        # minimo dell'incertezza complessiva.
        total = math.sqrt(
            geographic_radial ** 2
            + source_error ** 2
            + coordinate_error ** 2
            + measurement_error ** 2
            + datum_error ** 2
        )
        total = max(geographic_radial, total)
        # Il Point-Radius descrive l'estensione geografica e gli errori della
        # fonte. La risoluzione del candidato resta una diagnostica separata.
        total = max(1.0, total)
        return {
            "coordinate_uncertainty_m": round(total, 1),
            "gbif_uncertainty_m": round(total, 1),
            "geographic_radial_m": round(geographic_radial, 1),
            # Alias legacy mantenuto per compatibilità: è una diagnostica,
            # non una componente di coordinateUncertaintyInMeters.
            "grid_error_m": round(candidate_resolution, 1),
            "candidate_resolution_m": round(candidate_resolution, 1),
            "grid_step_diagnostic_m": round(grid_step_diagnostic, 1),
            "source_error_m": round(source_error, 1),
            "coordinate_error_m": round(coordinate_error, 1),
            "measurement_error_m": round(measurement_error, 1),
            "datum_error_m": round(datum_error, 1),
            "gbif_calculable": True,
            "gbif_method": (
                "point-radius from GBIF corrected center to the selected locality "
                "extent; independent source/coordinate/measurement/datum errors are "
                "combined in quadrature; candidate resolution reported separately"
            ),
            "uncertainty_method": "gbif_point_radius",
            "candidate_resolution_method": "grid_step_div_sqrt_2",
            "gbif_extent_source": "original_or_operational_locality_extent",
        }

    def max_distance_to_geometry_m(self, point_wgs84, geom_wgs84):
        """Distanza massima dal punto a tutto il bordo della geometria."""
        try:
            metric = self._local_metric_crs(point_wgs84)
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            transform = QgsCoordinateTransform(wgs84, metric, QgsProject.instance())

            center_geom = QgsGeometry.fromPointXY(QgsPointXY(point_wgs84))
            center_geom.transform(transform)
            center = center_geom.asPoint()

            geom = QgsGeometry(geom_wgs84)
            geom.transform(transform)
            try:
                geom = geom.densifyByDistance(25.0)
            except Exception:
                pass

            maximum = None
            for vertex in geom.vertices():
                distance = math.hypot(
                    float(vertex.x()) - float(center.x()),
                    float(vertex.y()) - float(center.y()),
                )
                if maximum is None or distance > maximum:
                    maximum = distance
            return maximum
        except Exception:
            return None

    def _local_metric_crs(self, point_wgs84):
        return _shared_local_metric_crs(point_wgs84)

    @staticmethod
    def _to_float(value):
        return _shared_to_float(value)

    @classmethod
    def _nonnegative_float(cls, value, default):
        parsed = cls._to_float(value)
        return parsed if parsed is not None and parsed >= 0 else float(default)

    @staticmethod
    def _not_calculable(reason):
        return {
            "coordinate_uncertainty_m": None,
            "gbif_uncertainty_m": None,
            "geographic_radial_m": None,
            "grid_error_m": None,
            "candidate_resolution_m": None,
            "grid_step_diagnostic_m": None,
            "source_error_m": None,
            "coordinate_error_m": None,
            "measurement_error_m": None,
            "datum_error_m": None,
            "gbif_calculable": False,
            "gbif_failure_reason": reason,
            "gbif_method": "point-radius_not_calculable",
            "uncertainty_method": "gbif_point_radius_not_calculable",
            "candidate_resolution_method": "grid_step_div_sqrt_2",
            "gbif_extent_source": "original_or_operational_locality_extent",
        }
