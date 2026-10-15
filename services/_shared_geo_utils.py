"""Helper numerici e geometrici condivisi tra i servizi GeoLichen.

Questo modulo centralizza piccole funzioni di utilita che, fino alla 14.2.0,
erano copiate e incollate indipendentemente in piu file di ``services/``:

- ``to_float``: conversione sicura a float (10 copie indipendenti trovate:
  benchmark_service, ecological_layer_decision_service, ecology_engine,
  gbif_georeferencing_service, habitat_suitability_service,
  model_uncertainty_service, scoring_model, soil_service, uncertainty_service,
  validation_service). Le copie non erano tutte equivalenti: solo
  benchmark_service e validation_service gestivano la virgola decimale
  (es. "450,5") e scartavano NaN/Inf; le altre 8 copie fallivano silenziosamente
  su quei valori restituendo None. Questo modulo adotta la versione piu
  robusta come unica implementazione, cosi nessun punto del codice perde piu
  silenziosamente un valore numerico valido scritto con la virgola.

- ``local_metric_crs`` / ``local_metric_crs_epsg_string``: calcolo della zona
  UTM locale per un punto WGS84, prima duplicato con la stessa identica
  formula in gbif_georeferencing_service.py e gbif_locality_geometry_service.py.

- ``coerce_geometry``: conversione sicura a QgsGeometry, prima duplicata in
  gbif_corrected_center_service.py e gbif_locality_geometry_service.py.

Nessuna di queste funzioni tocca GSS, ranking, MCI, SSI o filtri altitudinali:
sono utility numeriche/geometriche di basso livello, usate a valle.
"""
from __future__ import annotations

import math

from qgis.core import QgsCoordinateReferenceSystem, QgsGeometry


def to_float(value, default=None):
    """Converte ``value`` in float in modo sicuro, gestendo la virgola decimale.

    Restituisce ``default`` (di norma ``None``) se il valore e vuoto, non
    numerico, oppure NaN/Inf. Accetta numeri gia float/int, stringhe con
    punto o virgola come separatore decimale (es. "12.5" o "12,5"), e i
    valori vuoti tipici del progetto (``None``, ``""``, ``[]``, ``{}``).
    """
    if value is None:
        return default
    try:
        if value in [None, "", [], {}]:
            return default
    except Exception:
        pass
    text = str(value).strip().replace(" ", "")
    if not text:
        return default
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        result = float(text)
    except Exception:
        return default
    return result if math.isfinite(result) else default


def utm_epsg_code(lon, lat):
    """Restituisce il codice EPSG della zona UTM che contiene (lon, lat)."""
    zone = max(1, min(60, int((float(lon) + 180.0) / 6.0) + 1))
    return (32600 if float(lat) >= 0 else 32700) + zone


def local_metric_crs(point_wgs84):
    """Restituisce il QgsCoordinateReferenceSystem UTM locale per un punto WGS84.

    In caso di errore ripiega su EPSG:32632 (UTM 32N), coerentemente con il
    comportamento storico di gbif_georeferencing_service.py.
    """
    try:
        epsg = utm_epsg_code(point_wgs84.x(), point_wgs84.y())
        return QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
    except Exception:
        return QgsCoordinateReferenceSystem("EPSG:32632")


def local_metric_crs_epsg_string(point):
    """Restituisce la stringa "EPSG:<codice>" della zona UTM locale, o None.

    Coerente col comportamento storico di gbif_locality_geometry_service.py,
    che a differenza di ``local_metric_crs`` restituisce None (non un CRS di
    fallback) in caso di errore.
    """
    try:
        epsg = utm_epsg_code(point.x(), point.y())
        return f"EPSG:{epsg}"
    except Exception:
        return None


def coerce_geometry(value):
    """Restituisce ``value`` come QgsGeometry se possibile, altrimenti None."""
    try:
        if value is None or value.isEmpty():
            return None
        return QgsGeometry(value)
    except Exception:
        return None
