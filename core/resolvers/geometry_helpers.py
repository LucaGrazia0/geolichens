"""Shared helpers for operational Geometry Resolution Engine resolvers.

Kept deliberately small: resolvers consume geometries already supplied by the
boundary pipeline and only decode provider GeoJSON when necessary.
"""
import json

try:
    from qgis.core import QgsGeometry, QgsPointXY, QgsRectangle
except Exception:  # Allows documentation/static tooling outside QGIS.
    QgsGeometry = None
    QgsPointXY = None
    QgsRectangle = None


def geometry_type_name(geometry):
    if geometry is None:
        return "NONE"
    try:
        if geometry.isEmpty():
            return "EMPTY"
        return {0: "POINT", 1: "LINE", 2: "POLYGON"}.get(int(geometry.type()), "UNKNOWN")
    except Exception:
        return "UNKNOWN"


def clone_geometry(geometry):
    if geometry is None:
        return None
    try:
        return QgsGeometry(geometry)
    except Exception:
        return geometry


def geometry_from_feature(feature):
    """Decode the best explicit geometry available in a geocoder feature."""
    if QgsGeometry is None or not isinstance(feature, dict):
        return None, ""

    geojson = feature.get("geometry")
    if isinstance(geojson, dict):
        try:
            geometry = QgsGeometry.fromJson(json.dumps(geojson).encode("utf-8"))
            if geometry is not None and not geometry.isEmpty():
                return geometry, "provider_geojson"
        except Exception:
            pass

    bbox = feature.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            geometry = QgsGeometry.fromRect(QgsRectangle(*map(float, bbox)))
            if geometry is not None and not geometry.isEmpty():
                return geometry, "provider_bbox"
        except Exception:
            pass

    center = feature.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        try:
            return QgsGeometry.fromPointXY(QgsPointXY(float(center[0]), float(center[1]))), "provider_center"
        except Exception:
            pass

    lon = feature.get("lon", feature.get("longitude", feature.get("x")))
    lat = feature.get("lat", feature.get("latitude", feature.get("y")))
    if lon is not None and lat is not None:
        try:
            return QgsGeometry.fromPointXY(QgsPointXY(float(lon), float(lat))), "provider_coordinates"
        except Exception:
            pass
    return None, ""


def point_geometry_from_feature(feature):
    """Decode a representative provider point without promoting its bbox.

    Point-like documentary features (summits, passes, refuges) may carry a
    small provider bbox as positional evidence. The bbox is not their primary
    documentary geometry and is therefore deliberately ignored here.
    """
    if QgsGeometry is None or not isinstance(feature, dict):
        return None, ""

    geojson = feature.get("geometry")
    if isinstance(geojson, dict) and str(geojson.get("type") or "").lower() == "point":
        try:
            geometry = QgsGeometry.fromJson(json.dumps(geojson).encode("utf-8"))
            if geometry is not None and not geometry.isEmpty():
                return geometry, "provider_geojson_point"
        except Exception:
            pass

    center = feature.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        try:
            return QgsGeometry.fromPointXY(QgsPointXY(float(center[0]), float(center[1]))), "provider_center"
        except Exception:
            pass

    lon = feature.get("lon", feature.get("longitude", feature.get("x")))
    lat = feature.get("lat", feature.get("latitude", feature.get("y")))
    if lon is not None and lat is not None:
        try:
            return QgsGeometry.fromPointXY(QgsPointXY(float(lon), float(lat))), "provider_coordinates"
        except Exception:
            pass
    return None, ""
