"""Read optional local municipal polygons once per lookup, without network IO."""
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsFeatureRequest, QgsGeometry, QgsProject)
from ..core.locality_names import normalize_name
from ..core.qgis_compat import GeometryType


class MunicipalityBoundaryService:
    @staticmethod
    def resolve(layer, name_field, municipality):
        if layer is None or not layer.isValid() or name_field not in layer.fields().names():
            return None
        wanted = normalize_name(municipality)
        if not wanted:
            return None
        ids = []
        request = QgsFeatureRequest().setSubsetOfAttributes([name_field], layer.fields())
        request.setFlags(getattr(Qgis, 'FeatureRequestFlag', QgsFeatureRequest).NoGeometry)
        for feature in layer.getFeatures(request):
            name = normalize_name(feature[name_field])
            name = name[len('comune di '):] if name.startswith('comune di ') else name
            target = wanted[len('comune di '):] if wanted.startswith('comune di ') else wanted
            if name != target:
                continue
            ids.append(feature.id())
        matches = []
        # Read geometry only for the named municipality, not every polygon in
        # a regional or national boundary layer. No stale cross-run cache.
        request = QgsFeatureRequest().setFilterFids(ids).setNoAttributes()
        for feature in layer.getFeatures(request) if ids else ():
            geometry = QgsGeometry(feature.geometry())
            if geometry.isEmpty() or geometry.type() != GeometryType.Polygon:
                continue
            if not geometry.isGeosValid():
                geometry = geometry.makeValid()
            geometry.transform(QgsCoordinateTransform(layer.crs(), QgsCoordinateReferenceSystem('EPSG:4326'),
                                                       QgsProject.instance()))
            matches.append(geometry)
        return QgsGeometry.unaryUnion(matches) if matches else None
