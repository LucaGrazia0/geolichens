"""Shared, identified QGIS transport for the two read-only Overpass clients."""
import json
import time
from threading import Timer
from urllib.parse import quote_plus

from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsBlockingNetworkRequest, QgsFeedback

from ..core.enum_utils import enum_value
from .network_service import identified_request
from .diagnostics_service import log

_cooldown_until = {}
USER_AGENT = b'GeoLichen/15.6.32 (+https://github.com/LucaGrazia0/geolichens)'
NO_ERROR = QgsBlockingNetworkRequest.ErrorCode.NoError


def download_overpass(query, endpoints, timeout_s, *, wait_timeout_s=None):
    """Keep the server execution budget separate from the network deadline.

    The latter must also allow for queuing and response transfer. Existing
    short locality lookups retain their deadline unless explicitly overridden.
    Never return partial/error responses as datasets.
    """
    errors = []
    endpoint_used = ''
    wait_s = max(0.1, float(timeout_s) + 2.0 if wait_timeout_s is None else float(wait_timeout_s))
    body = QByteArray(('data=' + quote_plus(query)).encode('utf-8'))
    for endpoint in endpoints[:2]:
        endpoint_used = endpoint
        log('Overpass', 'Tentativo di download sentieri/geometrie', 'debug')
        if _cooldown_until.get(endpoint, 0) > time.monotonic():
            return None, 'Overpass temporaneamente sospeso: attendi prima di riprovare.', endpoint
        try:
            request = QNetworkRequest(QUrl(endpoint))
            request.setRawHeader(b'User-Agent', USER_AGENT)
            request.setRawHeader(b'Accept', b'application/json')
            # Let the total watchdog cancel first, avoiding a race between
            # Qt's inactivity abort and feedback cancellation diagnostics.
            request.setTransferTimeout(int(wait_s * 1000) + 1000)
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                              'application/x-www-form-urlencoded; charset=UTF-8')
            blocking = QgsBlockingNetworkRequest()
            # Transfer timeout only limits inactivity. Also impose a total
            # deadline so a stalled server cannot block QGIS indefinitely.
            feedback = QgsFeedback()
            timer = Timer(wait_s, feedback.cancel)
            timer.daemon = True
            timer.start()
            try:
                with identified_request(request, USER_AGENT):
                    result = blocking.post(request, body, forceRefresh=True, feedback=feedback)
            finally:
                timer.cancel()
            if feedback.isCanceled():
                log('Overpass', f'Tempo limite di rete superato ({wait_s:g} s).')
                errors.append(f'Tempo limite Overpass superato ({wait_s:g} s) su {endpoint}')
                continue
            reply = blocking.reply()
            status_value = (reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                            if reply is not None else None)
            status = int(status_value) if status_value is not None else 0
            # Respect service refusal/rate limits without immediately changing hosts.
            if status in (406, 429):
                _cooldown_until[endpoint] = time.monotonic() + (300 if status == 406 else 30)
                return None, f'Overpass HTTP {status}: richiesta rifiutata o limite raggiunto; riprova più tardi.', endpoint
            if status >= 400:
                log('Overpass', f'HTTP {status}: il servizio ha rifiutato o non completato la richiesta.')
                detail = 'server occupato o temporaneamente non disponibile' if status in (502, 503, 504) else 'richiesta non riuscita'
                errors.append(f'Overpass HTTP {status}: {detail} ({endpoint})')
                continue
            if enum_value(result) != enum_value(NO_ERROR):
                errors.append(blocking.errorMessage() or f'Errore richiesta {endpoint}')
                continue
            # Some QGIS versions return NoError for the blocking call even
            # when its underlying reply timed out or was canceled.
            if reply is not None and reply.error() != QNetworkReply.NetworkError.NoError:
                if reply.error() == QNetworkReply.NetworkError.TimeoutError:
                    errors.append(f'Tempo limite Overpass superato ({wait_s:g} s) su {endpoint}')
                else:
                    errors.append(f'Errore di rete Overpass: {reply.errorString()} ({endpoint})')
                continue
            raw = bytes(reply.content()) if reply is not None else b''
            if not raw:
                errors.append(f'Risposta vuota da {endpoint}')
                continue
            payload = json.loads(raw.decode('utf-8'))
            if not isinstance(payload, dict) or not isinstance(payload.get('elements'), list):
                errors.append(f'Risposta OSM non riconosciuta da {endpoint}')
                continue
            if payload.get('remark'):
                errors.append(f'Overpass: {payload["remark"]}')
                continue
            return payload, None, endpoint
        except Exception as exc:
            errors.append(f'{endpoint}: {exc}')
    return None, 'Download Overpass fallito: ' + ' | '.join(errors[-2:]), endpoint_used
