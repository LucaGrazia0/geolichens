"""User-confirmed locality anchors, independent of ecological point outputs."""
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile

from ..core.locality_names import normalize_name
from .storage_service import profile_data_path


class ConfirmedLocalitiesService:
    VERSION = 1
    FIELDS = ('id', 'text', 'place_name', 'center', 'bbox', 'geometry', 'properties',
              'place_type', 'osm_id', 'osm_type', 'provider', 'attribution')

    def __init__(self, path=None):
        self.path = Path(path or profile_data_path('confirmed_localities.json'))

    @staticmethod
    def _valid(feature):
        try:
            lon, lat = feature['center']
            return (all(math.isfinite(float(v)) for v in (lon, lat))
                    and -180 <= float(lon) <= 180 and -90 <= float(lat) <= 90)
        except (KeyError, TypeError, ValueError):
            return False

    def entries(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('version') != self.VERSION or not isinstance(data.get('entries'), list):
                return []
            return [e for e in data['entries'] if isinstance(e, dict)
                    and isinstance(e.get('aliases'), list) and self._valid(e.get('feature'))]
        except (OSError, ValueError, AttributeError):
            return []

    def _write(self, entries):
        # Do not silently overwrite an unreadable or incompatible archive.
        if self.path.exists():
            existing = json.loads(self.path.read_text(encoding='utf-8'))
            if (not isinstance(existing, dict) or existing.get('version') != self.VERSION
                    or not isinstance(existing.get('entries'), list)):
                raise ValueError('Archivio località non compatibile: conserva il file prima di sostituirlo.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.path.parent, delete=False) as handle:
                temp = Path(handle.name)
                json.dump({'version': self.VERSION, 'entries': entries}, handle, ensure_ascii=False, indent=2)
            os.replace(temp, self.path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def remember(self, query, municipality, feature, aliases=()):
        if not normalize_name(query) or not self._valid(feature):
            return
        entries = self.entries()
        key = (normalize_name(query), normalize_name(municipality))
        old_aliases = [v for e in entries
                       if (normalize_name(e.get('query')), normalize_name(e.get('municipality'))) == key
                       for v in e['aliases']]
        entries = [e for e in entries if (normalize_name(e.get('query')), normalize_name(e.get('municipality'))) != key]
        values = list(dict.fromkeys(str(v).strip() for v in (query, *old_aliases, *aliases) if str(v or '').strip()))
        entries.append({'query': str(query), 'municipality': str(municipality or ''), 'aliases': values,
                        'confirmed_at': datetime.now(timezone.utc).isoformat(),
                        'feature': {k: copy.deepcopy(feature[k]) for k in self.FIELDS if k in feature}})
        self._write(entries)

    def lookup(self, query, municipality, bbox=None):
        result = []
        for entry in self.entries():
            if normalize_name(entry.get('municipality')) != normalize_name(municipality):
                continue
            if normalize_name(query) not in {normalize_name(v) for v in entry['aliases']}:
                continue
            feature = copy.deepcopy(entry['feature'])
            lon, lat = map(float, feature['center'])
            if bbox and not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                continue
            feature['_geolichen_confirmed_locality'] = True
            feature['_geolichen_confirmed_at'] = entry.get('confirmed_at', '')
            result.append(feature)
        return result

    def remove(self, query, municipality):
        key = (normalize_name(query), normalize_name(municipality))
        self._write([e for e in self.entries()
                     if (normalize_name(e.get('query')), normalize_name(e.get('municipality'))) != key])
