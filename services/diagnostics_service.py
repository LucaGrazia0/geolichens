"""Scoped QGIS diagnostics; never changes global logging or TLS settings."""
import re
from urllib.parse import urlsplit

from qgis.core import Qgis, QgsMessageLog, QgsSettings

SETTING = 'GeoLichen/diagnostics_enabled'


def enabled():
    return QgsSettings().value(SETTING, False, type=bool)


def set_enabled(value):
    QgsSettings().setValue(SETTING, bool(value))


def safe_message(message):
    """Keep host names, but remove URL credentials, paths and query contents."""
    def host_only(match):
        try:
            return 'https://' + (urlsplit(match.group()).hostname or '[server]')
        except ValueError:
            return '[URL]'
    text = re.sub(r'https?://[^\s<>]+', host_only, str(message))
    text = re.sub(r'(?i)\b(api[_ -]?key|token|password|authorization)\s*[:=]\s*(?:Bearer\s+)?\S+',
                  r'\1=[redacted]', text)
    return text[:1600]


def log(component, message, level='warning'):
    if level == 'debug' and not enabled():
        return
    levels = Qgis.MessageLevel
    severity = {'warning': levels.Warning, 'critical': levels.Critical}.get(level, levels.Info)
    QgsMessageLog.logMessage(f'[{component}] {safe_message(message)}', 'GeoLichen', severity, False)


def service_name(url):
    host = (urlsplit(url).hostname or '').lower()
    if host == 'italic.units.it':
        return 'ITALIC'
    if host == 'photon.komoot.io':
        return 'Photon'
    return host or 'Servizio online'
