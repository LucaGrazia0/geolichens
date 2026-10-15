"""Phase 13A — Terrain Preparation Engine.

The engine selects the DEM that spatially covers a locality, extracts a local
raster window and computes slope, aspect and two simple curvature derivatives.
It is intentionally non-invasive: it does not update SLGE geometries, GBIF
uncertainty, GSS, heatmaps or ranking.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from .terrain_context import TerrainContext, TerrainRasterGrid
from ..services._shared_geo_utils import local_metric_crs

try:  # QGIS is available only inside the plugin runtime.
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsRectangle,
    )
except Exception:  # pragma: no cover - enables external unit tests/imports.
    QgsCoordinateReferenceSystem = None
    QgsCoordinateTransform = None
    QgsGeometry = None
    QgsPointXY = None
    QgsProject = None
    QgsRasterLayer = None
    QgsRectangle = None

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


class TerrainPreparationEngine:
    """Prepare a local topographic context from one or more DEM layers."""

    VERSION = "13.A.1"

    def __init__(self, default_radius_m: float = 2500.0, max_cells: int = 1_500_000) -> None:
        self.default_radius_m = max(100.0, float(default_radius_m))
        self.max_cells = max(10_000, int(max_cells))

    @staticmethod
    def _is_raster(layer: Any) -> bool:
        if layer is None:
            return False
        try:
            return bool(layer.isValid()) and layer.dataProvider() is not None and layer.bandCount() >= 1
        except Exception:
            return False

    @staticmethod
    def _layer_source(layer: Any) -> str:
        try:
            return str(layer.source() or "")
        except Exception:
            return ""

    @staticmethod
    def _clone_point(point: Any) -> Any:
        if point is None:
            return None
        try:
            if hasattr(point, "asPoint"):
                return point.asPoint()
            return QgsPointXY(point)
        except Exception:
            return point

    def _transform_point(self, point: Any, source_crs: Any, target_crs: Any) -> Any:
        if point is None or source_crs is None or target_crs is None:
            return point
        try:
            if source_crs == target_crs:
                return QgsPointXY(point)
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            return transform.transform(QgsPointXY(point))
        except Exception:
            return None

    def _metric_radius_extent(self, center: Any, source_crs: Any, target_crs: Any, radius_m: float) -> Any:
        """Create a radius extent in target CRS without assuming it is metric."""
        if center is None or QgsCoordinateReferenceSystem is None:
            return None
        center_wgs84 = self._transform_point(
            center, source_crs, QgsCoordinateReferenceSystem("EPSG:4326")
        )
        if center_wgs84 is None:
            return None
        metric = local_metric_crs(center_wgs84)
        center_metric = self._transform_point(center, source_crs, metric)
        if center_metric is None:
            return None
        rect_metric = QgsRectangle(
            center_metric.x() - radius_m,
            center_metric.y() - radius_m,
            center_metric.x() + radius_m,
            center_metric.y() + radius_m,
        )
        try:
            if metric == target_crs:
                return rect_metric
            transform = QgsCoordinateTransform(metric, target_crs, QgsProject.instance())
            return transform.transformBoundingBox(rect_metric)
        except Exception:
            return None

    def _select_dem(self, dem_layers: Sequence[Any], center: Any, center_crs: Any, band: int) -> Tuple[Any, Any, Optional[float], List[str]]:
        warnings: List[str] = []
        covering = []
        for index, layer in enumerate(dem_layers or []):
            if not self._is_raster(layer):
                continue
            try:
                point_layer = self._transform_point(center, center_crs, layer.crs())
                if point_layer is None or not layer.extent().contains(point_layer):
                    continue
                result = layer.dataProvider().identify(point_layer, 1)
                value = result.results().get(int(band)) if result and result.isValid() else None
                value = float(value) if value is not None else None
                if value is not None and math.isfinite(value):
                    px = abs(float(layer.rasterUnitsPerPixelX()))
                    py = abs(float(layer.rasterUnitsPerPixelY()))
                    resolution = max(px, py)
                    covering.append((resolution, index, layer, point_layer, value))
            except Exception as exc:
                warnings.append(f"DEM non interrogabile: {getattr(layer, 'name', lambda: '?')()} ({exc})")
        if not covering:
            return None, None, None, warnings
        # Finest covering DEM first; original order breaks ties.
        covering.sort(key=lambda item: (item[0], item[1]))
        _, _, layer, point_layer, value = covering[0]
        return layer, point_layer, value, warnings

    @staticmethod
    def _block_to_array(block: Any, width: int, height: int, nodata: Optional[float]) -> Any:
        if np is None:
            raise RuntimeError("NumPy non disponibile nel runtime QGIS")
        values = np.empty((height, width), dtype=float)
        valid = np.ones((height, width), dtype=bool)
        for row in range(height):
            for col in range(width):
                try:
                    if block.isNoData(row, col):
                        values[row, col] = np.nan
                        valid[row, col] = False
                    else:
                        value = float(block.value(row, col))
                        if not math.isfinite(value) or (nodata is not None and value == nodata):
                            values[row, col] = np.nan
                            valid[row, col] = False
                        else:
                            values[row, col] = value
                except Exception:
                    values[row, col] = np.nan
                    valid[row, col] = False
        return values, valid

    @staticmethod
    def _fill_for_derivatives(elevation: Any, valid: Any) -> Any:
        """Fill isolated NoData cells conservatively for numerical gradients."""
        filled = elevation.copy()
        if valid.all():
            return filled
        finite = filled[np.isfinite(filled)]
        fallback = float(np.median(finite)) if finite.size else 0.0
        filled[~np.isfinite(filled)] = fallback
        # A few neighbour-mean iterations avoid sharp artificial NoData edges.
        for _ in range(3):
            missing = ~valid
            if not missing.any():
                break
            neighbour_sum = np.zeros_like(filled)
            neighbour_count = np.zeros_like(filled)
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                shifted = np.roll(np.roll(filled, dy, axis=0), dx, axis=1)
                shifted_valid = np.roll(np.roll(valid, dy, axis=0), dx, axis=1)
                neighbour_sum += np.where(shifted_valid, shifted, 0.0)
                neighbour_count += shifted_valid
            replaceable = missing & (neighbour_count > 0)
            filled[replaceable] = neighbour_sum[replaceable] / neighbour_count[replaceable]
            valid = valid | replaceable
        return filled

    def _derive(self, elevation: Any, valid: Any, pixel_x: float, pixel_y: float) -> Tuple[Any, Any, Any, Any]:
        filled = self._fill_for_derivatives(elevation, valid.copy())
        dz_dy, dz_dx = np.gradient(filled, abs(pixel_y), abs(pixel_x))
        slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
        aspect = (np.degrees(np.arctan2(dz_dx, -dz_dy)) + 360.0) % 360.0

        d2z_dx2 = np.gradient(dz_dx, abs(pixel_x), axis=1)
        d2z_dy2 = np.gradient(dz_dy, abs(pixel_y), axis=0)
        d2z_dxdy = np.gradient(dz_dx, abs(pixel_y), axis=0)
        grad2 = dz_dx * dz_dx + dz_dy * dz_dy
        eps = 1e-12
        profile = -(
            d2z_dx2 * dz_dx * dz_dx
            + 2.0 * d2z_dxdy * dz_dx * dz_dy
            + d2z_dy2 * dz_dy * dz_dy
        ) / np.power(grad2 + eps, 1.5)
        plan = (
            d2z_dx2 * dz_dy * dz_dy
            - 2.0 * d2z_dxdy * dz_dx * dz_dy
            + d2z_dy2 * dz_dx * dz_dx
        ) / np.power(grad2 + eps, 1.5)

        for array in (slope, aspect, profile, plan):
            array[~valid] = np.nan
        return slope, aspect, profile, plan

    def prepare(
        self,
        dem_layers: Sequence[Any],
        center: Any,
        center_crs: Any,
        *,
        radius_m: Optional[float] = None,
        band: int = 1,
    ) -> TerrainContext:
        """Prepare the local DEM and derivatives around ``center``.

        The returned context is diagnostic infrastructure only. Calling this
        method never mutates a layer or an SLGE geometry.
        """
        radius = max(100.0, float(radius_m or self.default_radius_m))
        provenance = {"engine": "Terrain Preparation Engine", "version": self.VERSION}
        if np is None:
            return TerrainContext.unavailable("NumPy non disponibile", provenance=provenance)
        if center is None or center_crs is None:
            return TerrainContext.unavailable("Centro o CRS della località assente", provenance=provenance)

        layer, center_layer, center_value, warnings = self._select_dem(dem_layers, center, center_crs, int(band))
        if layer is None:
            return TerrainContext.unavailable(*(warnings + ["Nessun DEM selezionato copre la località"]), provenance=provenance)

        extent = self._metric_radius_extent(center, center_crs, layer.crs(), radius)
        if extent is None:
            return TerrainContext.unavailable("Impossibile costruire l'estensione DEM locale", provenance=provenance)
        try:
            extent = extent.intersect(layer.extent())
        except Exception:
            pass
        if extent is None or extent.isEmpty():
            return TerrainContext.unavailable("Estensione DEM locale vuota", provenance=provenance)

        pixel_x = abs(float(layer.rasterUnitsPerPixelX()))
        pixel_y = abs(float(layer.rasterUnitsPerPixelY()))
        width = max(3, int(math.ceil(extent.width() / pixel_x)))
        height = max(3, int(math.ceil(extent.height() / pixel_y)))
        total = width * height
        quality_flags: List[str] = []
        if total > self.max_cells:
            scale = math.sqrt(total / float(self.max_cells))
            width = max(3, int(width / scale))
            height = max(3, int(height / scale))
            quality_flags.append("resampled_for_memory_limit")

        try:
            provider = layer.dataProvider()
            block = provider.block(int(band), extent, width, height)
            nodata = provider.sourceNoDataValue(int(band)) if provider.sourceHasNoDataValue(int(band)) else None
            elevation, valid = self._block_to_array(block, width, height, nodata)
            actual_px = extent.width() / float(width)
            actual_py = extent.height() / float(height)
            slope, aspect, profile, plan = self._derive(elevation, valid, actual_px, actual_py)
        except Exception as exc:
            return TerrainContext.unavailable(f"Preparazione DEM fallita: {exc}", provenance=provenance)

        valid_count = int(valid.sum())
        total_count = int(valid.size)
        coverage = valid_count / float(total_count) if total_count else 0.0
        if coverage < 0.80:
            quality_flags.append("partial_dem_coverage")
        if coverage < 0.50:
            warnings.append("Copertura DEM locale inferiore al 50%")
        if min(width, height) < 10:
            quality_flags.append("small_raster_window")

        grid = TerrainRasterGrid(
            elevation=elevation,
            slope_degrees=slope,
            aspect_degrees=aspect,
            profile_curvature=profile,
            plan_curvature=plan,
            valid_mask=valid,
            width=width,
            height=height,
            pixel_size_x=actual_px,
            pixel_size_y=actual_py,
            nodata_value=nodata,
        )
        provenance.update(
            {
                "selection_rule": "finest_spatially_covering_dem",
                "center_elevation_m": center_value,
                "derivatives": ["slope", "aspect", "profile_curvature", "plan_curvature"],
                "geometry_mutation": False,
            }
        )
        return TerrainContext(
            available=True,
            dem_layer=layer,
            dem_layer_name=str(layer.name() or ""),
            dem_source=self._layer_source(layer),
            band=int(band),
            extent=extent,
            crs=layer.crs(),
            center=center_layer,
            radius_m=radius,
            resolution_m=max(abs(actual_px), abs(actual_py)),
            grid=grid,
            coverage_ratio=coverage,
            valid_cell_count=valid_count,
            total_cell_count=total_count,
            quality_flags=tuple(quality_flags),
            warnings=tuple(warnings),
            provenance=provenance,
        )
