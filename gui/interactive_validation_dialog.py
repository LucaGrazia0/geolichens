from dataclasses import asdict

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTextBrowser,
    QVBoxLayout, QScrollArea, QWidget, QApplication,
)
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.gui import QgsMapToolEmitPoint

from ..services.interactive_validation_service import InteractiveValidationService


class InteractiveValidationDialog(QDialog):
    def __init__(self, *, iface, context, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.context = dict(context or {})
        self.service = InteractiveValidationService()
        self.result = None
        self._previous_map_tool = None
        self._capture_tool = None
        self._capture_active = False
        self._host_dialog = parent if isinstance(parent, QDialog) else None

        self.setWindowTitle("Valida questo risultato")
        self.resize(680, 650)
        self.setMinimumSize(560, 420)

        outer_layout = QVBoxLayout(self)
        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget(self.scrollArea)
        layout = QVBoxLayout(content)
        self.scrollArea.setWidget(content)
        outer_layout.addWidget(self.scrollArea, 1)

        intro = QLabel(
            "Inserisci la posizione nota (gold standard), oppure selezionala sulla mappa. "
            "La validazione misura l'errore del punto GeoLichen e verifica la copertura dell'incertezza GBIF."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.txtRecordId = QLineEdit()
        self.lat = QDoubleSpinBox(); self.lat.setRange(-90, 90); self.lat.setDecimals(8)
        self.lon = QDoubleSpinBox(); self.lon.setRange(-180, 180); self.lon.setDecimals(8)
        self.alt = QDoubleSpinBox(); self.alt.setRange(-500, 10000); self.alt.setDecimals(1); self.alt.setSpecialValueText("Non disponibile"); self.alt.setValue(-500)
        form.addRow("ID record (facoltativo)", self.txtRecordId)
        form.addRow("Latitudine reale (WGS84)", self.lat)
        form.addRow("Longitudine reale (WGS84)", self.lon)
        form.addRow("Quota reale (m, facoltativa)", self.alt)
        layout.addLayout(form)

        capture_row = QHBoxLayout()
        self.btnCapture = QPushButton("Seleziona posizione reale sulla mappa")
        self.btnCenter = QPushButton("Usa centro della mappa")
        self.btnCapture.clicked.connect(self._start_capture)
        self.btnCenter.clicked.connect(self._use_canvas_center)
        capture_row.addWidget(self.btnCapture); capture_row.addWidget(self.btnCenter)
        layout.addLayout(capture_row)

        self.btnCalculate = QPushButton("Calcola validazione")
        self.btnCalculate.clicked.connect(self._calculate)
        layout.addWidget(self.btnCalculate)

        self.output = QTextBrowser()
        self.output.setMinimumHeight(260)
        self.output.setHtml("<p><i>Nessuna validazione calcolata.</i></p>")
        layout.addWidget(self.output, 1)

        export_row = QHBoxLayout()
        self.btnSave = QPushButton("Aggiungi al CSV di validazione")
        self.btnSave.setEnabled(False)
        self.btnSave.clicked.connect(self._save_csv)
        export_row.addWidget(self.btnSave); export_row.addStretch(1)
        layout.addLayout(export_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        outer_layout.addWidget(buttons)

    def _canvas_point_to_wgs84(self, point):
        canvas = self.iface.mapCanvas()
        source = canvas.mapSettings().destinationCrs()
        target = QgsCoordinateReferenceSystem("EPSG:4326")
        if source == target:
            return point
        return QgsCoordinateTransform(source, target, QgsProject.instance()).transform(point)

    def _set_reference_point(self, point):
        wgs = self._canvas_point_to_wgs84(point)
        self.lon.setValue(float(wgs.x())); self.lat.setValue(float(wgs.y()))

    def _use_canvas_center(self):
        try:
            self._set_reference_point(self.iface.mapCanvas().center())
        except Exception as exc:
            QMessageBox.warning(self, "Validazione", str(exc))

    def _start_capture(self):
        if self._capture_active:
            return
        canvas = self.iface.mapCanvas()
        self._previous_map_tool = canvas.mapTool()
        self._capture_tool = QgsMapToolEmitPoint(canvas)
        self._capture_tool.canvasClicked.connect(self._captured)
        self._capture_active = True

        # Dalla 12.3.2 sia questo dialogo sia la finestra di conferma sono
        # non modali. Li nascondiamo durante la cattura per lasciare il canvas
        # completamente libero, poi processiamo subito gli eventi Qt prima di
        # attivare il QgsMapTool.
        self.hide()
        if self._host_dialog is not None:
            self._host_dialog.hide()
        QApplication.processEvents()

        self._capture_tool.setCursor(Qt.CrossCursor)
        canvas.setMapTool(self._capture_tool)
        canvas.setFocus(Qt.OtherFocusReason)
        canvas.activateWindow()
        try:
            canvas.window().raise_()
            canvas.window().activateWindow()
        except Exception:
            pass
        QApplication.processEvents()
        self.iface.messageBar().pushMessage(
            "GeoLichen",
            "Clicca sulla posizione reale del record sulla mappa.",
            level=0,
            duration=10,
        )

    def _finish_capture(self):
        canvas = self.iface.mapCanvas()
        try:
            if self._capture_tool is not None:
                try:
                    self._capture_tool.canvasClicked.disconnect(self._captured)
                except Exception:
                    pass
            if self._previous_map_tool is not None:
                canvas.setMapTool(self._previous_map_tool)
            else:
                canvas.unsetMapTool(self._capture_tool)
        finally:
            self._capture_active = False
            self._capture_tool = None
            self._previous_map_tool = None

            if self._host_dialog is not None:
                self._host_dialog.show()
                self._host_dialog.raise_()
            self.show()
            self.raise_()
            self.activateWindow()

    def _captured(self, point, button):
        try:
            self._set_reference_point(point)
        except Exception as exc:
            QMessageBox.warning(self, "Validazione", f"Impossibile acquisire il punto:\n{exc}")
        finally:
            self._finish_capture()

    def reject(self):
        if self._capture_active:
            self._finish_capture()
        super().reject()

    def closeEvent(self, event):
        if self._capture_active:
            self._finish_capture()
        super().closeEvent(event)

    def _calculate(self):
        try:
            unc = self.context.get("uncertainty_m")
            ref_alt = None if self.alt.value() == self.alt.minimum() else self.alt.value()
            self.result = self.service.validate(
                reference_latitude=self.lat.value(), reference_longitude=self.lon.value(),
                geolichen_latitude=self.context.get("geolichen_latitude"),
                geolichen_longitude=self.context.get("geolichen_longitude"),
                gbif_latitude=self.context.get("gbif_latitude"), gbif_longitude=self.context.get("gbif_longitude"),
                uncertainty_m=unc, reference_altitude_m=ref_alt,
                geolichen_altitude_m=self.context.get("geolichen_altitude_m"),
                gss=self.context.get("gss"), mci=self.context.get("mci"), ssi=self.context.get("ssi"),
                candidate_rank=self.context.get("candidate_rank"), record_id=self.txtRecordId.text(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Validazione", f"Impossibile calcolare la validazione:\n{exc}")
            return
        self.output.setHtml(self._result_html(self.result))
        self.btnSave.setEnabled(True)

    @staticmethod
    def _result_html(result):
        def number(value, digits=1, suffix=""):
            return "Non disponibile" if value is None else f"{value:.{digits}f}{suffix}"
        if result.reference_inside_uncertainty is True:
            coverage = "✓ Sì — la posizione reale è compresa nell'incertezza stimata"
        elif result.reference_inside_uncertainty is False:
            coverage = "✗ No — la posizione reale è fuori dall'incertezza stimata"
        else:
            coverage = "Non valutabile"
        ratio = result.error_uncertainty_ratio
        if ratio is None:
            ratio_text = "Non valutabile"
        else:
            ratio_text = f"{ratio:.2f} ({ratio * 100:.0f}% del raggio di incertezza)"
        return (
            "<h2>Risultato della validazione</h2>"
            f"<p><b>Errore del punto GeoLichen:</b> {number(result.geolichen_error_m, 1, ' m')}<br>"
            f"<b>Errore del centro corretto GBIF:</b> {number(result.gbif_error_m, 1, ' m')}<br>"
            f"<b>Incertezza GBIF:</b> {number(result.uncertainty_m, 1, ' m')}<br>"
            f"<b>Copertura dell'incertezza:</b> {coverage}<br>"
            f"<b>Rapporto errore/incertezza:</b> {ratio_text}<br>"
            f"<b>Errore altitudinale:</b> {number(result.altitude_error_m, 1, ' m')}</p>"
            "<h3>Metriche del modello associate</h3>"
            f"<p><b>Rank:</b> {result.candidate_rank if result.candidate_rank is not None else '—'} &nbsp; "
            f"<b>GSS:</b> {number(result.gss, 2)} &nbsp; "
            f"<b>MCI:</b> {number(result.mci, 0, '%')} &nbsp; "
            f"<b>SSI:</b> {number(result.ssi, 0, '%')}</p>"
            "<p><i>La validazione non modifica il punto, il ranking o le metriche di GeoLichen.</i></p>"
        )

    def _save_csv(self):
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salva/aggiorna dataset di validazione", "GeoLichen_validation_session.csv", "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            self.service.append_csv(path, self.result)
            QMessageBox.information(self, "Validazione", f"Risultato aggiunto a:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Validazione", f"Salvataggio non riuscito:\n{exc}")
