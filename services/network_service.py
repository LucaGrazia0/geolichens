"""HTTP requests using QGIS proxy, authentication and TLS settings."""
from ..core.enum_utils import enum_value
from .diagnostics_service import log, service_name

from threading import Timer
from contextlib import contextmanager
from uuid import uuid4

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsFeedback, QgsNetworkAccessManager


@contextmanager
def identified_request(request, user_agent):
    """Keep this request's identity after QGIS replaces the User-Agent header.

    Use a private, non-transmitted request attribute, and remove the scoped
    preprocessor afterwards. Other QGIS requests/settings remain unaffected.
    """
    if not user_agent:
        yield
        return
    token = 'geolichen:' + uuid4().hex
    attribute = QNetworkRequest.Attribute.User
    previous = request.attribute(attribute)
    request.setAttribute(attribute, token)
    agent = user_agent.encode('utf-8') if isinstance(user_agent, str) else user_agent

    def identify(candidate):
        if candidate.attribute(attribute) == token:
            candidate.setRawHeader(b'User-Agent', agent)

    processor = QgsNetworkAccessManager.setRequestPreprocessor(identify)
    try:
        yield
    finally:
        QgsNetworkAccessManager.removeRequestPreprocessor(processor)
        request.setAttribute(attribute, previous)


def fetch_text(url, timeout=20, headers=None):
    """Fetch UTF-8 text without exposing query parameters in error messages."""
    component = service_name(url)
    log(component, "Richiesta HTTPS/HTTP avviata", "debug")
    request = QNetworkRequest(QUrl(url))
    for name, value in (headers or {}).items():
        request.setRawHeader(name.encode("ascii"), value.encode("utf-8"))
    feedback = QgsFeedback()
    # blockingGet does not dispatch timers in the caller's Qt event loop.
    # QgsFeedback cancellation can be signalled from another thread.
    timer = Timer(max(0.001, float(timeout)), feedback.cancel)
    timer.daemon = True
    timer.start()
    try:
        agent = next((v for k, v in (headers or {}).items() if k.lower() == 'user-agent'), None)
        with identified_request(request, agent):
            reply = QgsNetworkAccessManager.blockingGet(
                request, forceRefresh=True, feedback=feedback
            )
    finally:
        timer.cancel()
    if feedback.isCanceled():
        log(component, "Tempo di attesa superato; il servizio non ha risposto in tempo.")
        raise TimeoutError("Network request timed out.")
    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
    if status is not None and int(status) >= 400:
        log(component, f"HTTP {int(status)}: risposta di errore del servizio.")
        raise OSError(f"HTTP {int(status)} from remote service.")
    if reply.error() != QNetworkReply.NetworkError.NoError:
        code = enum_value(reply.error())
        if reply.error() == QNetworkReply.NetworkError.SslHandshakeFailedError:
            detail = "Certificato HTTPS non verificato. Richiesta interrotta; nessuna eccezione SSL applicata."
        else:
            detail = f"Connessione non riuscita (codice {code}); verificare rete e servizio."
        log(component, detail)
        raise OSError(f"{component}: {detail}")
    log(component, "Risposta ricevuta", "debug")
    return bytes(reply.content()).decode("utf-8", errors="replace")
