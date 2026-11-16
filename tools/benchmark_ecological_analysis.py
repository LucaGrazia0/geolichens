"""Local synthetic benchmark; run with QGIS Python (-B).

Compares the corrected model with and without repeated sampling/full SSI work.
No network, specimen datasets or user project. Prints JSON for Windows/macOS
comparison. Runtime depends on hardware; no timing threshold is asserted.
"""

import json
from pathlib import Path
import platform
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from regression_analysis import (
    FullStability, SpatialAnalysis, UnoptimizedHabitat,
    EcologyEngine, HabitatSuitabilityService, ModelUncertaintyService,
    QgsApplication, QgsCoordinateReferenceSystem, QgsDistanceArea,
    QgsPointXY, QgsProject, SolutionStabilityService,
)


def fresh_distance(a, b):
    if a is None or b is None:
        return None
    measure = QgsDistanceArea()
    measure.setSourceCrs(QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance().transformContext())
    measure.setEllipsoid("WGS84")
    return float(measure.measureLine(QgsPointXY(a), QgsPointXY(b)))


class RepeatedDistanceModel(ModelUncertaintyService):
    def make_distance_func(self):
        return fresh_distance


def timed(operation):
    start = time.perf_counter()
    result = operation()
    return result, round(time.perf_counter() - start, 6)


def benchmark():
    fixture = SpatialAnalysis()
    fixture.setUp()
    try:
        report = {"platform": platform.platform(), "python": platform.python_version()}
        from qgis.core import Qgis
        report["qgis"] = Qgis.QGIS_VERSION
        reuse = ModelUncertaintyService().make_distance_func()
        for name, scale in (("compact", 1), ("dispersed", 20)):
            rows = [{"point": fixture.xy((i % 40) * scale, (i // 40) * scale), "score": 80}
                    for i in range(800)]
            full, before = timed(lambda: FullStability().evaluate(80, rows, fixture.point, fresh_distance, 100, 10))
            fast, after = timed(lambda: SolutionStabilityService().evaluate(80, rows, fixture.point, reuse, 100, 10))
            assert full == fast, "SSI output changed"
            report["ssi_800_" + name] = {"full_seconds": before, "optimized_seconds": after,
                                         "identical_output": True}

        dem = fixture.dem()
        soil = fixture.polygon("Synthetic soil", "&field=PH_H2O:double", [5.2])
        forest = fixture.polygon("Synthetic forest", "&field=tree:string", ["abete"])
        points = [fixture.xy(x, y) for x in range(-100, 101, 10) for y in range(-100, 101, 10)][:300]
        reference = UnoptimizedHabitat(EcologyEngine())
        reference.uncertainty_service.model_service = RepeatedDistanceModel()
        reference.uncertainty_service.stability_service = FullStability()
        optimized = HabitatSuitabilityService(EcologyEngine())

        def analyze(service):
            return fixture.run_analysis(service=service, dem_layer=dem, soil_layer=soil, soil_field="PH_H2O",
                                        trees_layer=forest, trees_field="tree", _candidate_points=points,
                                        create_layer=True, visualization_mode="both", grid_step_m=10)

        full, before = timed(lambda: analyze(reference))
        fast, after = timed(lambda: analyze(optimized))
        assert full["features"] == fast["features"], "Scores/ranks/evidence changed"
        assert fixture.comparable(full["uncertainty"]) == fixture.comparable(fast["uncertainty"]), "Uncertainty changed"
        report["analysis_300_with_points_and_surface"] = {
            "full_seconds": before, "optimized_seconds": after,
            "identical_scores_ranks_evidence_uncertainty": True,
            "network_included": False, "canvas_rendering_included": False,
            "adaptive_refinement_included": False,
        }
        QgsProject.instance().removeAllMapLayers()
        return report
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="geolichen_benchmark_profile_") as profile:
        app = QgsApplication([], False, profile)
        app.initQgis()
        print(json.dumps(benchmark(), indent=2))
