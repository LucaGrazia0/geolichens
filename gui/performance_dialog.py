from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QGroupBox, QTextEdit
)
from qgis.core import QgsApplication, QgsProject, QgsMapLayerType


class PerformanceDialog(QDialog):
    def __init__(self, iface, performance_service, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.service = performance_service
        self.setWindowTitle("GeoLichen — Performance e robustezza")
        self.resize(900, 620)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Diagnostica osservativa: misura le operazioni già eseguite e controlla lo stato del progetto. "
            "Non modifica GSS, ranking, MCI, SSI o incertezza."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        env_box = QGroupBox("Ambiente runtime")
        env_layout = QVBoxLayout(env_box)
        self.txtEnvironment = QTextEdit()
        self.txtEnvironment.setReadOnly(True)
        self.txtEnvironment.setMaximumHeight(120)
        env_layout.addWidget(self.txtEnvironment)
        layout.addWidget(env_box)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Operazione", "Esecuzioni", "Errori", "Media (s)", "Min (s)", "Max (s)", "Ultima (s)"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.lblProject = QLabel()
        self.lblProject.setWordWrap(True)
        layout.addWidget(self.lblProject)

        buttons = QHBoxLayout()
        btn_refresh = QPushButton("Aggiorna")
        btn_refresh.clicked.connect(self.refresh)
        buttons.addWidget(btn_refresh)
        btn_export = QPushButton("Esporta JSON")
        btn_export.clicked.connect(self.export_json)
        buttons.addWidget(btn_export)
        btn_clear = QPushButton("Azzera registro")
        btn_clear.clicked.connect(self.clear_records)
        buttons.addWidget(btn_clear)
        buttons.addStretch(1)
        btn_close = QPushButton("Chiudi")
        btn_close.clicked.connect(self.close)
        buttons.addWidget(btn_close)
        layout.addLayout(buttons)
        self.refresh()

    def _environment(self):
        qgis_version = getattr(QgsApplication, "qgisVersion", lambda: "non disponibile")()
        return self.service.runtime_environment(qgis_version=qgis_version)

    def refresh(self):
        env = self._environment()
        self.txtEnvironment.setPlainText("\n".join(f"{k}: {v}" for k, v in env.items()))
        summary = self.service.summary()
        rows = summary.get("operations", [])
        self.table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            values = [
                row.get("operation", ""), row.get("runs", 0), row.get("failures", 0),
                f"{row.get('mean_s', 0.0):.3f}", f"{row.get('min_s', 0.0):.3f}",
                f"{row.get('max_s', 0.0):.3f}", f"{row.get('last_s', 0.0):.3f}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col > 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col, item)
        project = QgsProject.instance()
        layers = list(project.mapLayers().values())
        raster_count = sum(1 for layer in layers if layer.type() == QgsMapLayerType.RasterLayer)
        vector_count = sum(1 for layer in layers if layer.type() == QgsMapLayerType.VectorLayer)
        invalid = [layer.name() for layer in layers if not layer.isValid()]
        self.lblProject.setText(
            f"Progetto: {len(layers)} layer ({vector_count} vettoriali, {raster_count} raster). "
            + ("Layer non validi: " + ", ".join(invalid) if invalid else "Tutti i layer caricati risultano validi.")
        )
        self.table.resizeColumnsToContents()

    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Esporta diagnostica", "GeoLichen_performance.json", "JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            self.service.export_json(path, extra=self._environment())
            QMessageBox.information(self, "GeoLichen", "Diagnostica esportata correttamente.")
        except Exception as exc:
            QMessageBox.critical(self, "GeoLichen", f"Esportazione non riuscita:\n{exc}")

    def clear_records(self):
        self.service.clear()
        self.refresh()
