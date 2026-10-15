"""Phase 13C — terrain-derived mountain polygon reconstruction.

The engine consumes ``TerrainContext`` and ``SummitDetectionResult`` and
reconstructs the morphologic domain draining by steepest ascent toward the
selected summit. A prominence-informed elevation floor, maximum distance and
connected-component checks prevent the result from expanding across deep
saddles or into neighbouring mountains.

Phase 13C remains non-invasive: it returns a candidate terrain polygon but does
not replace ``DocumentedGeometry`` or alter GBIF uncertainty. Integration is
reserved for Phase 13D.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .summit_context import SummitDetectionResult
from .terrain_context import TerrainContext
from .terrain_polygon_context import TerrainPolygonResult

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:  # QGIS is optional in external tests.
    from qgis.core import QgsGeometry, QgsPointXY, QgsRectangle
except Exception:  # pragma: no cover
    QgsGeometry = None
    QgsPointXY = None
    QgsRectangle = None


class TerrainPolygonReconstructionEngine:
    """Reconstruct a mountain domain around the selected summit."""

    VERSION = "13.C.1"

    def __init__(
        self,
        *,
        minimum_relief_m: float = 80.0,
        maximum_relief_m: float = 450.0,
        prominence_fraction: float = 0.85,
        minimum_radius_m: float = 180.0,
        maximum_radius_m: float = 1800.0,
        minimum_area_m2: float = 30_000.0,
        maximum_area_m2: float = 12_000_000.0,
        simplify_tolerance_cells: float = 0.75,
    ) -> None:
        self.minimum_relief_m = max(10.0, float(minimum_relief_m))
        self.maximum_relief_m = max(self.minimum_relief_m, float(maximum_relief_m))
        self.prominence_fraction = max(0.2, min(1.5, float(prominence_fraction)))
        self.minimum_radius_m = max(50.0, float(minimum_radius_m))
        self.maximum_radius_m = max(self.minimum_radius_m, float(maximum_radius_m))
        self.minimum_area_m2 = max(0.0, float(minimum_area_m2))
        self.maximum_area_m2 = max(self.minimum_area_m2, float(maximum_area_m2))
        self.simplify_tolerance_cells = max(0.0, float(simplify_tolerance_cells))

    @staticmethod
    def _neighbours8(row: int, col: int, height: int, width: int):
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                rr, cc = row + dr, col + dc
                if 0 <= rr < height and 0 <= cc < width:
                    yield rr, cc

    @staticmethod
    def _distance_grid(row: int, col: int, summit_row: int, summit_col: int, px: float, py: float) -> float:
        return math.hypot((col - summit_col) * px, (row - summit_row) * py)

    def _elevation_floor(self, summit_elevation: float, prominence: float) -> Tuple[float, float]:
        relief = prominence * self.prominence_fraction
        relief = max(self.minimum_relief_m, min(self.maximum_relief_m, relief))
        return summit_elevation - relief, relief

    def _adaptive_radius(self, prominence: float, terrain_radius: float) -> float:
        # Larger/prominent mountains receive a larger reconstruction window,
        # but never exceed the prepared DEM radius.
        radius = self.minimum_radius_m + max(0.0, prominence) * 3.0
        radius = max(self.minimum_radius_m, min(self.maximum_radius_m, radius))
        if terrain_radius > 0:
            radius = min(radius, terrain_radius * 0.92)
        return radius

    def _steepest_ascent_labels(self, elevation: Any, eligible: Any) -> Tuple[Any, Dict[int, Tuple[int, int]]]:
        """Label every eligible cell by the local maximum reached uphill.

        The implementation uses path compression and deterministic tie
        breaking. Plateaus are resolved by moving to the lexicographically
        first equal-height neighbour only when that neighbour has a smaller
        flat index, preventing cycles.
        """
        height, width = elevation.shape
        parent = np.full((height, width), -1, dtype=np.int64)
        for row in range(height):
            for col in range(width):
                if not eligible[row, col]:
                    continue
                current_index = row * width + col
                best_index = current_index
                best_z = float(elevation[row, col])
                for rr, cc in self._neighbours8(row, col, height, width):
                    if not eligible[rr, cc]:
                        continue
                    z = float(elevation[rr, cc])
                    idx = rr * width + cc
                    if z > best_z + 1e-9 or (abs(z - best_z) <= 1e-9 and idx < best_index):
                        best_z = z
                        best_index = idx
                parent[row, col] = best_index

        labels = np.full((height, width), -1, dtype=np.int64)
        roots: Dict[int, Tuple[int, int]] = {}
        for row in range(height):
            for col in range(width):
                if parent[row, col] < 0:
                    continue
                path: List[int] = []
                index = row * width + col
                seen = set()
                while True:
                    rr, cc = divmod(index, width)
                    if labels[rr, cc] >= 0:
                        root = int(labels[rr, cc])
                        break
                    if index in seen:
                        root = min(seen)
                        break
                    seen.add(index)
                    path.append(index)
                    next_index = int(parent[rr, cc])
                    if next_index == index:
                        root = index
                        break
                    index = next_index
                roots[root] = divmod(root, width)
                for path_index in path:
                    pr, pc = divmod(path_index, width)
                    labels[pr, pc] = root
        return labels, roots

    @staticmethod
    def _connected_component(mask: Any, seed_row: int, seed_col: int) -> Any:
        height, width = mask.shape
        result = np.zeros_like(mask, dtype=bool)
        if not (0 <= seed_row < height and 0 <= seed_col < width and mask[seed_row, seed_col]):
            return result
        queue = deque([(seed_row, seed_col)])
        result[seed_row, seed_col] = True
        while queue:
            row, col = queue.popleft()
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
                rr, cc = row + dr, col + dc
                if 0 <= rr < height and 0 <= cc < width and mask[rr, cc] and not result[rr, cc]:
                    result[rr, cc] = True
                    queue.append((rr, cc))
        return result

    @staticmethod
    def _binary_cleanup(mask: Any, passes: int = 1) -> Any:
        cleaned = mask.copy()
        height, width = cleaned.shape
        for _ in range(max(0, int(passes))):
            neighbour_count = np.zeros_like(cleaned, dtype=np.uint8)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    shifted = np.roll(np.roll(cleaned, dr, axis=0), dc, axis=1)
                    if dr < 0:
                        shifted[dr:, :] = False
                    elif dr > 0:
                        shifted[:dr, :] = False
                    if dc < 0:
                        shifted[:, dc:] = False
                    elif dc > 0:
                        shifted[:, :dc] = False
                    neighbour_count += shifted
            cleaned = (cleaned & (neighbour_count >= 2)) | (~cleaned & (neighbour_count >= 6))
        return cleaned

    @staticmethod
    def _perimeter_m(mask: Any, px: float, py: float) -> float:
        perimeter = 0.0
        height, width = mask.shape
        for row, col in zip(*np.where(mask)):
            if row == 0 or not mask[row - 1, col]:
                perimeter += px
            if row == height - 1 or not mask[row + 1, col]:
                perimeter += px
            if col == 0 or not mask[row, col - 1]:
                perimeter += py
            if col == width - 1 or not mask[row, col + 1]:
                perimeter += py
        return perimeter

    def _mask_to_geometry(self, terrain: TerrainContext, mask: Any) -> Any:
        """Polygonise the mask by merging contiguous row runs.

        Row runs dramatically reduce the number of geometries compared with
        one rectangle per raster cell. Outside QGIS, ``None`` is returned while
        the numerical mask remains fully testable.
        """
        if QgsGeometry is None or QgsRectangle is None or terrain.extent is None:
            return None
        px = abs(float(terrain.grid.pixel_size_x))
        py = abs(float(terrain.grid.pixel_size_y))
        x_min = float(terrain.extent.xMinimum())
        y_max = float(terrain.extent.yMaximum())
        rectangles = []
        height, width = mask.shape
        for row in range(height):
            cols = np.where(mask[row])[0]
            if cols.size == 0:
                continue
            start = previous = int(cols[0])
            runs = []
            for value in cols[1:]:
                value = int(value)
                if value == previous + 1:
                    previous = value
                    continue
                runs.append((start, previous))
                start = previous = value
            runs.append((start, previous))
            top = y_max - row * py
            bottom = top - py
            for first, last in runs:
                left = x_min + first * px
                right = x_min + (last + 1) * px
                rectangles.append(QgsGeometry.fromRect(QgsRectangle(left, bottom, right, top)))
        if not rectangles:
            return None
        try:
            geometry = QgsGeometry.unaryUnion(rectangles)
            if geometry is None or geometry.isEmpty():
                return None
            try:
                geometry = geometry.makeValid()
            except Exception:
                pass
            tolerance = self.simplify_tolerance_cells * max(px, py)
            if tolerance > 0:
                try:
                    simplified = geometry.simplify(tolerance)
                    if simplified is not None and not simplified.isEmpty():
                        geometry = simplified
                except Exception:
                    pass
            return geometry
        except Exception:
            return None

    def reconstruct(
        self,
        terrain: TerrainContext,
        summit_result: SummitDetectionResult,
    ) -> TerrainPolygonResult:
        provenance = {
            "engine": "Terrain Polygon Reconstruction Engine",
            "version": self.VERSION,
            "input": ["TerrainContext", "SummitDetectionResult"],
            "method": "steepest_ascent_domain_with_prominence_floor",
            "geometry_mutation": False,
        }
        if np is None:
            return TerrainPolygonResult.unavailable("NumPy non disponibile", provenance=provenance)
        if terrain is None or not terrain.available or terrain.grid is None:
            return TerrainPolygonResult.unavailable("TerrainContext non disponibile", provenance=provenance)
        if summit_result is None or not summit_result.available or summit_result.selected is None:
            return TerrainPolygonResult.unavailable("Cima selezionata non disponibile", provenance=provenance)
        if summit_result.fallback_required:
            return TerrainPolygonResult.unavailable(
                "La rilevazione della cima richiede fallback; poligono non ricostruito",
                provenance=provenance,
            )

        grid = terrain.grid
        elevation = np.asarray(grid.elevation, dtype=float)
        valid = np.asarray(grid.valid_mask, dtype=bool) & np.isfinite(elevation)
        selected = summit_result.selected
        summit_row, summit_col = int(selected.row), int(selected.col)
        if not (0 <= summit_row < elevation.shape[0] and 0 <= summit_col < elevation.shape[1] and valid[summit_row, summit_col]):
            return TerrainPolygonResult.unavailable("La cima non ricade nella griglia DEM valida", provenance=provenance)

        px = abs(float(grid.pixel_size_x))
        py = abs(float(grid.pixel_size_y))
        cell_area = px * py
        summit_z = float(elevation[summit_row, summit_col])
        floor_z, relief = self._elevation_floor(summit_z, float(selected.prominence_m))
        radius_m = self._adaptive_radius(float(selected.prominence_m), float(terrain.radius_m))

        rows, cols = np.indices(elevation.shape)
        distance = np.hypot((cols - summit_col) * px, (rows - summit_row) * py)
        eligible = valid & (elevation >= floor_z) & (distance <= radius_m)
        if int(eligible.sum()) < 9:
            return TerrainPolygonResult.unavailable("Dominio topografico troppo piccolo", provenance=provenance)

        labels, _ = self._steepest_ascent_labels(elevation, eligible)
        summit_root = int(labels[summit_row, summit_col])
        if summit_root < 0:
            return TerrainPolygonResult.unavailable("Impossibile etichettare il dominio della cima", provenance=provenance)
        mask = labels == summit_root
        mask = self._connected_component(mask, summit_row, summit_col)
        mask = self._binary_cleanup(mask, passes=1)
        mask = self._connected_component(mask, summit_row, summit_col)

        cell_count = int(mask.sum())
        area_m2 = cell_count * cell_area
        if cell_count < 4:
            return TerrainPolygonResult.unavailable("Poligono morfologico insufficiente", provenance=provenance)

        perimeter = self._perimeter_m(mask, px, py)
        compactness = 0.0 if perimeter <= 0 else min(1.0, 4.0 * math.pi * area_m2 / (perimeter * perimeter))
        max_distance = float(distance[mask].max()) if cell_count else 0.0
        touches_edge = bool(
            mask[0, :].any() or mask[-1, :].any() or mask[:, 0].any() or mask[:, -1].any()
        )
        quality_flags: List[str] = []
        warnings: List[str] = []

        area_ok = self.minimum_area_m2 <= area_m2 <= self.maximum_area_m2
        if area_m2 < self.minimum_area_m2:
            quality_flags.append("area_too_small")
            warnings.append(f"Area ricostruita ridotta ({area_m2 / 1_000_000.0:.3f} km²)")
        if area_m2 > self.maximum_area_m2:
            quality_flags.append("area_too_large")
            warnings.append(f"Area ricostruita eccessiva ({area_m2 / 1_000_000.0:.2f} km²)")
        if touches_edge:
            quality_flags.append("touches_dem_edge")
            warnings.append("Il dominio raggiunge il bordo della finestra DEM")
        if compactness < 0.08:
            quality_flags.append("low_compactness")
            warnings.append("Poligono molto frastagliato o allungato")
        if terrain.coverage_ratio < 0.8:
            quality_flags.append("partial_dem_coverage")

        geometry = self._mask_to_geometry(terrain, mask)
        geometry_available = geometry is not None
        if QgsGeometry is not None and not geometry_available:
            quality_flags.append("polygonisation_failed")
            warnings.append("Maschera ricostruita ma conversione in poligono fallita")

        confidence = float(summit_result.confidence)
        confidence *= min(1.0, max(0.55, terrain.coverage_ratio))
        confidence *= 0.85 + 0.15 * compactness
        if not area_ok:
            confidence *= 0.65
        if touches_edge:
            confidence *= 0.72
        if compactness < 0.08:
            confidence *= 0.80
        if QgsGeometry is not None and not geometry_available:
            confidence *= 0.65
        confidence = max(0.0, min(1.0, confidence))
        fallback_required = confidence < 0.58 or not area_ok or touches_edge or (QgsGeometry is not None and not geometry_available)

        provenance.update(
            {
                "summit_row": summit_row,
                "summit_col": summit_col,
                "summit_elevation_m": summit_z,
                "summit_confidence": summit_result.confidence,
                "prominence_m": selected.prominence_m,
                "elevation_floor_m": floor_z,
                "relief_m": relief,
                "maximum_radius_m": radius_m,
                "cell_area_m2": cell_area,
                "cell_count": cell_count,
                "area_m2": area_m2,
                "perimeter_m": perimeter,
                "compactness": compactness,
                "touches_dem_edge": touches_edge,
                "polygonised": geometry_available,
                "fallback_threshold": 0.58,
            }
        )
        return TerrainPolygonResult(
            available=True,
            geometry=geometry,
            mask=mask,
            area_m2=area_m2,
            cell_count=cell_count,
            summit_elevation_m=summit_z,
            elevation_floor_m=floor_z,
            relief_m=relief,
            maximum_distance_m=max_distance,
            compactness=compactness,
            confidence=confidence,
            fallback_required=fallback_required,
            quality_flags=tuple(quality_flags),
            warnings=tuple(warnings),
            provenance=provenance,
        )
