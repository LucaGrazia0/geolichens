"""HTTP requests using QGIS proxy, authentication and TLS settings."""

from threading import Timer

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsFeedback, QgsNetworkAccessManager


def fetch_text(url, timeout=20, headers=None):
    """Fetch UTF-8 text without exposing query parameters in error messages."""
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
        reply = QgsNetworkAccessManager.blockingGet(
            request, forceRefresh=True, feedback=feedback
        )
    finally:
        timer.cancel()
    if feedback.isCanceled():
        raise TimeoutError("Network request timed out.")
    status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
    if status is not None and int(status) >= 400:
        raise OSError(f"HTTP {int(status)} from remote service.")
    if reply.error() != QNetworkReply.NoError:
        raise OSError(f"Network request failed (code {int(reply.error())}).")
    return bytes(reply.content()).decode("utf-8", errors="replace")
