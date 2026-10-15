import os
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox
)


class ReleaseReadinessDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.report = None
        self.setWindowTitle("GeoLichen — Controllo Release Candidate")
        self.resize(940, 650)
        layout = QVBoxLayout(self)
        self.lblStatus = QLabel()
        self.lblStatus.setWordWrap(True)
        layout.addWidget(self.lblStatus)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Esito", "Controllo", "Dettaglio", "Gravità"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        btn_run = QPushButton("Esegui nuovamente i controlli")
        btn_run.clicked.connect(self.run_checks)
        buttons.addWidget(btn_run)
        btn_export = QPushButton("Esporta report JSON")
        btn_export.clicked.connect(self.export_report)
        buttons.addWidget(btn_export)
        buttons.addStretch(1)
        btn_close = QPushButton("Chiudi")
        btn_close.clicked.connect(self.close)
        buttons.addWidget(btn_close)
        layout.addLayout(buttons)
        self.run_checks()

    def run_checks(self):
        self.report = self.service.run()
        ready = self.report.get("ready", False)
        status = "PRONTO PER RELEASE CANDIDATE" if ready else "NON PRONTO: sono presenti errori bloccanti"
        self.lblStatus.setText(
            f"<b>{status}</b><br>Controlli superati: {self.report.get('passed', 0)}/{self.report.get('total', 0)} — "
            f"Errori bloccanti: {self.report.get('blocking_failures', 0)} — Avvisi: {self.report.get('warnings', 0)}"
        )
        checks = self.report.get("checks", [])
        self.table.setRowCount(len(checks))
        for row_idx, check in enumerate(checks):
            values = [
                "✓" if check.get("ok") else "⚠" if check.get("severity") == "warning" else "✗",
                check.get("name", ""), check.get("detail", ""), check.get("severity", ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col in (0, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col, item)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(2, max(380, self.table.columnWidth(2)))

    def export_report(self):
        if not self.report:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Esporta controllo release", "GeoLichen_release_readiness.json", "JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            self.service.export_json(self.report, path)
            QMessageBox.information(self, "GeoLichen", "Report di release esportato correttamente.")
        except Exception as exc:
            QMessageBox.critical(self, "GeoLichen", f"Esportazione non riuscita:\n{exc}")
