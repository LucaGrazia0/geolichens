"""Darwin Core metadata for GeoLichen georeferences (Phase 9).

This service documents the geographic georeference independently from the
GeoLichen ecological point. It does not alter GSS, ranking, candidate
selection, DEM values, buffers, or heatmaps.
"""

from datetime import date
import math

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
)


class GbifMetadataService:
    """Build a Darwin Core compatible georeferencing metadata package."""

    PROTOCOL = "GeoLichen assisted point-radius and locality-geometry georeferencing protocol v10.0, derived from the GBIF Georeferencing Quick Reference Guide"
    DATUM = "EPSG:4326"
    FOOTPRINT_SRS = "EPSG:4326"

    def build(
        self,
        corrected_center,
        original_locality_extent,
        gbif_result,
        corrected_center_result=None,
        locality_context=None,
        constraint_metadata=None,
        coordinate_precision=0.000001,
        georeferenced_by="",
        verification_status="unverified",
    ):
        gbif_result = gbif_result or {}
        corrected_center_result = corrected_center_result or {}
        metadata = list(constraint_metadata or [])

        lon = lat = None
        if corrected_center is not None:
            try:
                lon = float(corrected_center.x())
                lat = float(corrected_center.y())
            except Exception:
                lon = lat = None

        uncertainty = self._positive_float(
            gbif_result.get("coordinate_uncertainty_m")
        )
        precision = self._positive_float(coordinate_precision) or 0.000001

        footprint_wkt = ""
        if original_locality_extent is not None:
            try:
                if not original_locality_extent.isEmpty():
                    footprint_wkt = original_locality_extent.asWkt()
            except Exception:
                footprint_wkt = ""

        spatial_fit = self._point_radius_spatial_fit(
            corrected_center=corrected_center,
            original_extent=original_locality_extent,
            radius_m=uncertainty,
        )

        sources = self._sources(
            metadata=metadata,
            locality_context=locality_context,
            corrected_center_result=corrected_center_result,
        )
        remarks = self._remarks(
            gbif_result=gbif_result,
            corrected_center_result=corrected_center_result,
            locality_context=locality_context,
            georeferenced_by=georeferenced_by,
        )

        return {
            "decimalLatitude": lat,
            "decimalLongitude": lon,
            "geodeticDatum": self.DATUM,
            "coordinateUncertaintyInMeters": uncertainty,
            # GeoLichen diagnostic fields: intentionally outside Darwin Core.
            "candidateResolutionInMeters": self._positive_float(
                gbif_result.get("candidate_resolution_m")
            ),
            "uncertaintyGeometrySource": str(
                gbif_result.get("uncertainty_geometry_source")
                or gbif_result.get("gbif_extent_source")
                or ""
            ),
            "uncertaintyMethod": str(
                gbif_result.get("uncertainty_method")
                or gbif_result.get("gbif_method")
                or ""
            ),
            "effectiveBufferRadiusInMeters": self._positive_float(
                gbif_result.get("effective_buffer_radius_m")
            ),
            "effectiveSearchGeometrySource": str(
                gbif_result.get("effective_search_geometry_source") or ""
            ),
            "effectiveSearchGeometryType": str(
                gbif_result.get("effective_search_geometry_type") or ""
            ),
            "effectiveSearchGeometryAreaHectares": self._positive_float(
                gbif_result.get("effective_search_geometry_area_ha")
            ),
            "effectiveSearchGeometryVertexCount": gbif_result.get(
                "effective_search_geometry_vertex_count"
            ),
            "effectiveSearchGeometryClipped": bool(
                gbif_result.get("effective_search_geometry_clipped")
            ),
            "effectiveSearchGeometryExpanded": bool(
                gbif_result.get("effective_search_geometry_expanded")
            ),
            "coordinatePrecision": precision,
            "pointRadiusSpatialFit": spatial_fit,
            "footprintWKT": footprint_wkt,
            "footprintSRS": self.FOOTPRINT_SRS if footprint_wkt else "",
            "georeferencedBy": str(georeferenced_by or ""),
            "georeferencedDate": date.today().isoformat(),
            "georeferenceProtocol": self.PROTOCOL,
            "georeferenceSources": sources,
            "georeferenceVerificationStatus": str(
                verification_status or "unverified"
            ),
            "georeferenceRemarks": remarks,
            "gbif_dwc_complete": bool(
                lon is not None
                and lat is not None
                and uncertainty is not None
                and self.DATUM
                and self.PROTOCOL
            ),
        }

    def _point_radius_spatial_fit(self, corrected_center, original_extent, radius_m):
        """Area(point-radius) / area(original representation).

        Darwin Core allows 0, values >= 1, or undefined. The value is left
        undefined for zero-area geometries unless the representation is the
        same point. A value of 0 is used only when the circle cannot contain the
        original geometry.
        """
        if corrected_center is None or original_extent is None or radius_m is None:
            return None
        try:
            if original_extent.isEmpty():
                return None
            area = self._metric_area(original_extent, corrected_center)
            if area is None or area <= 0:
                try:
                    if original_extent.type() == 0 and original_extent.distance(
                        QgsGeometry.fromPointXY(corrected_center)
                    ) == 0:
                        return 1.0
                except Exception:
                    pass
                return None
            circle_area = math.pi * float(radius_m) ** 2
            if circle_area + 1e-9 < area:
                return 0.0
            return round(max(1.0, circle_area / area), 6)
        except Exception:
            return None

    def _metric_area(self, geometry, point_wgs84):
        try:
            lon = float(point_wgs84.x())
            lat = float(point_wgs84.y())
            zone = max(1, min(60, int((lon + 180.0) / 6.0) + 1))
            epsg = (32600 if lat >= 0 else 32700) + zone
            metric = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            transform = QgsCoordinateTransform(wgs84, metric, QgsProject.instance())
            geom = QgsGeometry(geometry)
            geom.transform(transform)
            return float(geom.area())
        except Exception:
            return None

    @staticmethod
    def _sources(metadata, locality_context, corrected_center_result):
        values = []
        for item in metadata:
            source = str(item.get("source") or "").strip()
            if source and source not in values:
                values.append(source)
        if locality_context is not None:
            for value in (
                getattr(locality_context, "gbif_corrected_center_source", ""),
                getattr(locality_context, "search_strategy", ""),
            ):
                value = str(value or "").strip()
                if value and value not in values:
                    values.append(value)
        source = str(corrected_center_result.get("corrected_center_source") or "").strip()
        if source and source not in values:
            values.append(source)
        if "GeoLichen" not in values:
            values.append("GeoLichen")
        return " | ".join(values)

    @staticmethod
    def _remarks(gbif_result, corrected_center_result, locality_context, georeferenced_by):
        parts = [
            "Georeference calculated with the point-radius method from the GBIF corrected center and the selected documentary/operational locality extent.",
            "Ecological constraints, model radius and candidate-grid resolution were not used to reduce coordinateUncertaintyInMeters.",
        ]
        method = corrected_center_result.get("corrected_center_method")
        if method:
            parts.append(f"Corrected-center method: {method}.")
        source = corrected_center_result.get("corrected_center_source")
        if source:
            parts.append(f"Corrected-center source: {source}.")
        if locality_context is not None:
            geometry_method = getattr(locality_context, "locality_geometry_method", "")
            geometry_reason = getattr(locality_context, "locality_geometry_reason", "")
            if geometry_method:
                parts.append(f"Final locality geometry method: {geometry_method}.")
            if geometry_reason:
                parts.append(f"Locality geometry note: {geometry_reason}")
            if getattr(locality_context, "locality_geometry_requires_verification", False):
                parts.append("The offset geometry requires manual verification before publication.")
            locality_type = getattr(locality_context, "locality_type", "")
            geometry_type = getattr(locality_context, "geometry_type", "")
            if locality_type or geometry_type:
                parts.append(
                    f"Locality classification: {locality_type or 'unknown'} ({geometry_type or 'unknown'})."
                )
            documented_source = getattr(locality_context, "documented_extent_source", "")
            search_strategy = getattr(locality_context, "search_extent_strategy", "")
            if documented_source:
                parts.append(f"Documented locality extent source: {documented_source}.")
            if search_strategy:
                parts.append(f"Operational search extent strategy: {search_strategy}.")
        effective_type = gbif_result.get("effective_search_geometry_type")
        effective_radius = gbif_result.get("effective_buffer_radius_m")
        effective_area = gbif_result.get("effective_search_geometry_area_ha")
        effective_vertices = gbif_result.get("effective_search_geometry_vertex_count")
        effective_clipped = bool(gbif_result.get("effective_search_geometry_clipped"))
        effective_expanded = bool(gbif_result.get("effective_search_geometry_expanded"))
        if effective_type:
            parts.append(f"Effective operational geometry type: {effective_type}.")
        if effective_radius is not None:
            parts.append(f"Effective operational radius: {effective_radius} m.")
        if effective_area is not None:
            parts.append(f"Effective operational area: {effective_area} ha.")
        if effective_vertices is not None:
            parts.append(f"Effective operational geometry vertices: {effective_vertices}.")
        parts.append(
            "Effective operational geometry transformations: "
            f"clipped={effective_clipped}; expanded={effective_expanded}."
        )
        if locality_context is not None and getattr(
            locality_context, "documented_extent_requires_verification", False
        ):
            parts.append("The documentary locality extent requires manual verification before publication.")
        components = []
        for key, label in (
            ("geographic_radial_m", "geographic radial"),
            ("source_error_m", "source error"),
            ("coordinate_error_m", "coordinate error"),
            ("measurement_error_m", "measurement error"),
            ("datum_error_m", "datum error"),
        ):
            value = gbif_result.get(key)
            if value is not None:
                components.append(f"{label}={value} m")
        if components:
            parts.append("Uncertainty components: " + ", ".join(components) + ".")
        candidate_resolution = gbif_result.get("candidate_resolution_m")
        if candidate_resolution is not None:
            parts.append(
                f"Candidate resolution={candidate_resolution} m; this is a numerical grid diagnostic and is not included in coordinateUncertaintyInMeters."
            )
        geometry_source = gbif_result.get("uncertainty_geometry_source") or gbif_result.get("gbif_extent_source")
        if geometry_source:
            parts.append(f"Geometry used for uncertainty: {geometry_source}.")
        if not georeferenced_by:
            parts.append("georeferencedBy was not supplied and must be completed by the operator before publication.")
        return " ".join(parts)

    @staticmethod
    def _positive_float(value):
        try:
            value = float(value)
            return value if value > 0 else None
        except Exception:
            return None
