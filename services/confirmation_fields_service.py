"""Resolve and add confirmation columns without committing unrelated edits."""

import re
import unicodedata

from ..core.qgis_compat import ADD_ATTRIBUTES, FieldType
from qgis.core import QgsField


class ConfirmationFieldsService:
    # Short names also work with the ten-character Shapefile field limit.
    FIELDS = (
        ('x_field', 'longitude', 'Coordinata X', ('coordinata X', 'coordinate X', 'decimalLongitude', 'lon', 'x', 'coord_x', 'easting', 'est', 'utm_x')),
        ('y_field', 'latitude', 'Coordinata Y', ('coordinata Y', 'coordinate Y', 'decimalLatitude', 'lat', 'y', 'coord_y', 'northing', 'nord', 'utm_y')),
        ('dem_field', 'quota_dem', 'Quota DEM', ('quota DEM', 'altitude DEM', 'elevation DEM', 'altitude_m', 'quota', 'dem', 'altitudine', 'altitude', 'z')),
        ('uncertainty_field', 'inc_loc_m', 'Incertezza località (m)', ('incertezza località', 'incertezza località (m)', 'incertezza GBIF (m)', 'incertezza GBIF', 'coordinateUncertaintyInMeters', 'gbif_uncertainty', 'uncertainty_m', 'uncert_m')),
        ('model_radius_field', 'inc_geo_m', 'Incertezza GeoLichen (m)', ('incertezza geolichen', 'incertezza geolichen (m)', 'incertezza R55 S65', 'incertezza R55-S65', 'R55 S65', 'r55_s65', 'incertezza R55 S70', 'incertezza R55-S70', 'R55 S70', 'r55_s70', 'r55', 'model_r_m', 'model_radius_m', 'model_radius', 'incertezza_modello', 'incertezza_r55')),
    )

    @staticmethod
    def normalize(value):
        value = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode()
        return re.sub(r'[^a-z0-9]', '', value.casefold())

    @classmethod
    def resolve(cls, layer, defaults=None):
        names = layer.fields().names()
        normalized = {cls.normalize(name): name for name in names}
        result = {}
        for key, name, _, aliases in cls.FIELDS:
            configured = (defaults or {}).get(key)
            result[key] = configured if configured in names else next(
                (normalized[cls.normalize(alias)] for alias in (name,) + aliases
                 if cls.normalize(alias) in normalized), '')
        return result

    @classmethod
    def ensure_fields(cls, layer, mapping):
        if layer is None or not layer.isValid():
            raise ValueError('La tabella non è più disponibile.')
        result = dict(mapping)
        missing = [(key, name, label) for key, name, label, _ in cls.FIELDS
                   if not result.get(key) or layer.fields().indexOf(result[key]) < 0]
        if not missing:
            return result, []
        if not layer.dataProvider().capabilities() & ADD_ATTRIBUTES:
            raise ValueError('Il formato della tabella non consente di aggiungere colonne. '
                             'Esporta la tabella in GeoPackage e usa la copia modificabile.')
        started = not layer.isEditable()
        if started and not layer.startEditing():
            raise ValueError('Impossibile modificare la tabella. Controlla i permessi di scrittura.')
        layer.beginEditCommand('GeoLichen: crea campi di conferma')
        created = []
        try:
            for key, base, label in missing:
                name = base
                suffix = 1
                while layer.fields().indexOf(name) >= 0:
                    name = f'{base[:7]}_{suffix}'
                    suffix += 1
                if not layer.addAttribute(QgsField(name, FieldType.Double, len=20, prec=8)):
                    raise ValueError(f'Impossibile creare il campo {label}.')
                layer.updateFields()
                layer.setFieldAlias(layer.fields().indexOf(name), label)
                result[key] = name
                created.append(name)
            layer.endEditCommand()
            if started and not layer.commitChanges():
                raise ValueError('Salvataggio dei campi fallito: ' + '; '.join(layer.commitErrors()))
        except Exception:
            if started:
                layer.rollBack()
            else:
                layer.destroyEditCommand()
            raise
        return result, created
