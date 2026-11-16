"""OSM locality lookup through a configurable Photon endpoint.

The public demo is for moderate, interactive use. Cache responses, serialize
requests and never fall back to the public Nominatim service.
"""

import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import urlencode, urlsplit

from ..models.geocoding_config import DEFAULT_PHOTON_ENDPOINT
from .network_service import fetch_text
from .storage_service import profile_data_path


class PhotonGeocoder:
    DEFAULT_ENDPOINT = DEFAULT_PHOTON_ENDPOINT
    CACHE_TTL_S = 30 * 86400
    MIN_INTERVAL_S = 1.1
    SEARCH_TIMEOUT_S = 80.0
    _lock = threading.Lock()
    _last_request = 0.0

    def __init__(self, endpoint=None, timeout=35, cache_dir=None):
        self.endpoint = self.validate_endpoint(endpoint or self.DEFAULT_ENDPOINT)
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.last_from_cache = False
        self.network_requests = 0
        self.max_requests = 6
        self._deadline = None

    def begin_search(self):
        self.network_requests = 0
        self._deadline = time.monotonic() + self.SEARCH_TIMEOUT_S

    @staticmethod
    def validate_endpoint(endpoint):
        endpoint = str(endpoint or '').strip()
        parts = urlsplit(endpoint)
        if parts.scheme not in ('https', 'http') or not parts.hostname:
            raise ValueError('Indirizzo Photon non valido: usa un URL HTTP/HTTPS completo.')
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('L’indirizzo Photon non deve contenere credenziali, query o frammenti.')
        if parts.hostname.lower() in ('nominatim.openstreetmap.org', 'api.maptiler.com'):
            raise ValueError('Questo campo richiede un servizio Photon, non Nominatim o MapTiler.')
        return endpoint

    def _cache_path(self, url):
        folder = self.cache_dir or Path(profile_data_path('photon_cache'))
        folder.mkdir(parents=True, exist_ok=True)
        return folder / (hashlib.sha256(url.encode('utf-8')).hexdigest() + '.json')

    def search(self, query, bbox=None, proximity=None, limit=10, cache_only=False):
        params = {'q': str(query).strip(), 'limit': min(10, max(1, int(limit)))}
        if bbox:
            params['bbox'] = ','.join(str(v) for v in bbox)
        if proximity:
            params.update(lon=proximity[0], lat=proximity[1])
        url = self.endpoint.rstrip('/') + '/?' + urlencode(params)
        path = None
        self.last_from_cache = False
        try:
            path = self._cache_path(url)
            cached = json.loads(path.read_text(encoding='utf-8'))
            age = time.time() - float(cached['created'])
            if 0 <= age < self.CACHE_TTL_S:
                data = self.normalize(cached['response'], bbox)
                self.last_from_cache = True
                return data
        except (OSError, ValueError, KeyError, TypeError):
            pass

        if cache_only:
            raise OSError('Nessuna risposta Photon valida nella cache per questa ricerca.')

        with self._lock:
            if self.network_requests >= self.max_requests:
                raise OSError('Limite di richieste per ricerca raggiunto; usa la selezione manuale o riprova con un nome più preciso.')
            if self._deadline is not None and time.monotonic() >= self._deadline:
                raise TimeoutError('Tempo limite complessivo della ricerca Photon superato (80 s).')
            delay = self.MIN_INTERVAL_S - (time.monotonic() - PhotonGeocoder._last_request)
            if delay > 0:
                time.sleep(delay)
            PhotonGeocoder._last_request = time.monotonic()
            remaining = self.timeout if self._deadline is None else min(self.timeout, self._deadline - time.monotonic())
            if remaining <= 0:
                raise TimeoutError('Tempo limite complessivo della ricerca Photon superato (80 s).')
            self.network_requests += 1
            payload = json.loads(fetch_text(url, timeout=remaining, headers={
                'User-Agent': 'GeoLichen/15.6.32 (+https://github.com/LucaGrazia0/geolichens)',
                'Accept': 'application/json',
            }))
        data = self.normalize(payload, bbox)
        if path is not None:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                                 dir=path.parent, delete=False) as handle:
                    temporary = Path(handle.name)
                    json.dump({'created': time.time(), 'response': payload}, handle,
                              ensure_ascii=False)
                temporary.replace(path)
            except OSError:
                pass
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return copy.deepcopy(data)

    @staticmethod
    def normalize(payload, bbox=None):
        if not isinstance(payload, dict) or not isinstance(payload.get('features'), list):
            raise ValueError('Risposta Photon non valida: manca la lista delle località.')
        results = []
        for item in payload['features']:
            try:
                props = item.get('properties') or {}
                geometry = item.get('geometry') or {}
                if geometry.get('type') != 'Point':
                    continue
                lon, lat = [float(v) for v in geometry['coordinates'][:2]]
                if not (math.isfinite(lon) and math.isfinite(lat)
                        and -180 <= lon <= 180 and -90 <= lat <= 90):
                    continue
                if bbox and not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                    continue
                name = str(props.get('name') or props.get('city') or props.get('locality') or '').strip()
                if not name:
                    continue
                parts = list(dict.fromkeys(str(props[k]) for k in
                             ('name', 'locality', 'district', 'city', 'county', 'state', 'country')
                             if props.get(k)))
                osm_key, osm_value = props.get('osm_key'), props.get('osm_value')
                if osm_key == 'place' and osm_value in ('city', 'town'):
                    types = ['municipality', 'place']
                elif osm_key == 'place':
                    types = ['locality', 'place']
                elif osm_key in ('highway', 'railway'):
                    types = ['street']
                elif osm_key == 'boundary':
                    types = ['municipality' if props.get('type') == 'city' else 'region']
                else:
                    types = ['poi']
                feature = {
                    'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
                    'center': [lon, lat], 'text': name, 'place_name': ', '.join(parts) or name,
                    'place_type': types, 'properties': dict(props),
                    'provider': 'Photon / OpenStreetMap',
                    'attribution': '© OpenStreetMap contributors',
                    'id': f"osm:{props.get('osm_type', '')}:{props.get('osm_id', '')}",
                    'osm_id': props.get('osm_id'), 'osm_type': props.get('osm_type'),
                }
                extent = props.get('extent')
                if extent and len(extent) == 4:
                    west, north, east, south = [float(v) for v in extent]
                    if (all(math.isfinite(v) for v in (west, north, east, south))
                            and -180 <= west < east <= 180 and -90 <= south < north <= 90):
                        feature['bbox'] = [west, south, east, north]
                results.append(feature)
            except (AttributeError, KeyError, TypeError, ValueError, IndexError):
                continue
        return {'type': 'FeatureCollection', 'features': results,
                'attribution': '© OpenStreetMap contributors', 'provider': 'Photon / OpenStreetMap'}
