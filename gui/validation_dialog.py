import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget
)

from ..services.validation_service import ValidationService


class ValidationDialog(QDialog):
    OPTIONAL = '— Non disponibile —'

    FIELD_SPECS = [
        ('record_id', 'ID record', False, ['id', 'record_id', 'catalogNumber', 'numero']),
        ('reference_longitude', 'Longitudine riferimento', True, ['reference_longitude', 'ref_lon', 'gold_lon', 'longitude_ref']),
        ('reference_latitude', 'Latitudine riferimento', True, ['reference_latitude', 'ref_lat', 'gold_lat', 'latitude_ref']),
        ('geolichen_longitude', 'Longitudine GeoLichen', True, ['geolichen_longitude', 'geolichen_lon', 'longitude', 'x']),
        ('geolichen_latitude', 'Latitudine GeoLichen', True, ['geolichen_latitude', 'geolichen_lat', 'latitude', 'y']),
        ('gbif_longitude', 'Longitudine centro GBIF', False, ['decimalLongitude', 'gbif_lon', 'gbif_longitude']),
        ('gbif_latitude', 'Latitudine centro GBIF', False, ['decimalLatitude', 'gbif_lat', 'gbif_latitude']),
        ('uncertainty_m', 'Incertezza GBIF (m)', False, ['coordinateUncertaintyInMeters', 'uncertainty_m', 'gbif_uncertainty']),
        ('gss', 'GSS', False, ['gss', 'score']),
        ('mci', 'MCI', False, ['mci', 'model_confidence_index']),
        ('ssi', 'SSI', False, ['ssi', 'solution_stability_index']),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('GeoLichen — Fase 12.1 Validation Framework')
        self.resize(1050, 720)
        self.service = ValidationService()
        self.csv_path = ''
        self.headers = []
        self.source_rows = []
        self.results = []
        self.summary = {}
        self.combos = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        intro = QLabel('Confronta gli output GeoLichen con coordinate di riferimento (gold standard). Il modulo è separato dal motore e non modifica i risultati.')
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self.btnLoad = QPushButton('Carica dataset CSV')
        self.lblFile = QLabel('Nessun dataset caricato')
        self.lblFile.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.btnLoad)
        row.addWidget(self.lblFile, 1)
        layout.addLayout(row)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        mapping_page = QWidget()
        mapping_layout = QVBoxLayout(mapping_page)
        group = QGroupBox('Associazione dei campi')
        form = QFormLayout(group)
        for key, label, required, aliases in self.FIELD_SPECS:
            combo = QComboBox()
            combo.setEnabled(False)
            self.combos[key] = combo
            form.addRow(label + (' *' if required else ''), combo)
        mapping_layout.addWidget(group)
        self.btnRun = QPushButton('Esegui validazione')
        self.btnRun.setEnabled(False)
        mapping_layout.addWidget(self.btnRun)
        mapping_layout.addStretch(1)
        self.tabs.addTab(mapping_page, 'Dataset e campi')

        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        self.txtSummary = QTextEdit()
        self.txtSummary.setReadOnly(True)
        self.txtSummary.setMaximumHeight(190)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['ID', 'Errore GeoLichen (m)', 'Errore GBIF (m)', 'Incertezza (m)', 'Coperto', 'GSS', 'MCI', 'SSI'])
        self.table.setSortingEnabled(True)
        results_layout.addWidget(self.txtSummary)
        results_layout.addWidget(self.table, 1)
        export_row = QHBoxLayout()
        self.btnExportCsv = QPushButton('Esporta risultati CSV')
        self.btnExportHtml = QPushButton('Esporta report HTML')
        self.btnExportCsv.setEnabled(False)
        self.btnExportHtml.setEnabled(False)
        export_row.addWidget(self.btnExportCsv)
        export_row.addWidget(self.btnExportHtml)
        export_row.addStretch(1)
        results_layout.addLayout(export_row)
        self.tabs.addTab(results_page, 'Risultati')

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        btnClose = QPushButton('Chiudi')
        close_row.addWidget(btnClose)
        layout.addLayout(close_row)

        self.btnLoad.clicked.connect(self.load_csv)
        self.btnRun.clicked.connect(self.run_validation)
        self.btnExportCsv.clicked.connect(self.export_csv)
        self.btnExportHtml.clicked.connect(self.export_html)
        btnClose.clicked.connect(self.accept)

    def load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Apri dataset di validazione', '', 'CSV (*.csv *.txt);;Tutti i file (*)')
        if not path:
            return
        try:
            headers, rows = self.service.read_csv(path)
            if not headers or not rows:
                raise ValueError('Il file non contiene intestazioni o record.')
        except Exception as exc:
            QMessageBox.critical(self, 'Dataset non valido', str(exc))
            return
        self.csv_path, self.headers, self.source_rows = path, headers, rows
        self.lblFile.setText(f'{os.path.basename(path)} — {len(rows)} record')
        for key, label, required, aliases in self.FIELD_SPECS:
            combo = self.combos[key]
            combo.blockSignals(True)
            combo.clear()
            if not required:
                combo.addItem(self.OPTIONAL, '')
            for header in headers:
                combo.addItem(header, header)
            normalized = {h.lower().replace(' ', '').replace('_', ''): h for h in headers}
            chosen = None
            for alias in aliases:
                token = alias.lower().replace(' ', '').replace('_', '')
                if token in normalized:
                    chosen = normalized[token]
                    break
            if chosen:
                idx = combo.findData(chosen)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.setEnabled(True)
            combo.blockSignals(False)
        self.btnRun.setEnabled(True)

    def _mapping(self):
        return {key: self.combos[key].currentData() for key, _, _, _ in self.FIELD_SPECS}

    def run_validation(self):
        mapping = self._mapping()
        missing = [label for key, label, required, _ in self.FIELD_SPECS if required and not mapping.get(key)]
        if missing:
            QMessageBox.warning(self, 'Campi obbligatori', 'Associa i seguenti campi:\n• ' + '\n• '.join(missing))
            return
        try:
            self.results, skipped = self.service.validate(self.source_rows, mapping)
            if not self.results:
                raise ValueError('Nessun record valido dopo il controllo delle coordinate.')
            self.summary = self.service.summarize(self.results, len(skipped))
            self._show_results(skipped)
        except Exception as exc:
            QMessageBox.critical(self, 'Errore di validazione', str(exc))

    @staticmethod
    def _fmt(value, digits=1):
        return '—' if value is None else f'{value:.{digits}f}'

    def _show_results(self, skipped):
        geo = self.summary.get('geolichen', {})
        gbif = self.summary.get('gbif_center', {})
        coverage = self.summary.get('uncertainty_coverage_pct')
        text = [
            f"Record validati: {self.summary.get('records_validated', 0)}    Record scartati: {self.summary.get('records_skipped', 0)}",
            '',
            'PUNTO GEOLICHEN',
            f"MAE: {self._fmt(geo.get('mae_m'))} m    Mediana: {self._fmt(geo.get('median_m'))} m    RMSE: {self._fmt(geo.get('rmse_m'))} m    Massimo: {self._fmt(geo.get('max_m'))} m",
            f"Entro 50 m: {self._fmt(geo.get('within_50_pct'))}%    Entro 100 m: {self._fmt(geo.get('within_100_pct'))}%    Entro 500 m: {self._fmt(geo.get('within_500_pct'))}%    Entro 1 km: {self._fmt(geo.get('within_1000_pct'))}%",
        ]
        if gbif:
            text.extend(['', 'CENTRO CORRETTO GBIF', f"MAE: {self._fmt(gbif.get('mae_m'))} m    Mediana: {self._fmt(gbif.get('median_m'))} m    RMSE: {self._fmt(gbif.get('rmse_m'))} m"])
        text.extend(['', f"Copertura coordinateUncertaintyInMeters: {self._fmt(coverage)}% ({self.summary.get('uncertainty_coverage_n', 0)} record valutabili)"])
        if skipped:
            text.append(f"Prime righe scartate: {', '.join(str(i) for i, _ in skipped[:10])}")
        self.txtSummary.setPlainText('\n'.join(text))

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.results))
        for r, result in enumerate(self.results):
            values = [
                result.record_id, self._fmt(result.geolichen_error_m), self._fmt(result.gbif_error_m),
                self._fmt(result.uncertainty_m),
                'Sì' if result.reference_inside_uncertainty is True else ('No' if result.reference_inside_uncertainty is False else '—'),
                self._fmt(result.gss, 2), self._fmt(result.mci), self._fmt(result.ssi)
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c in (1, 2, 3, 5, 6, 7) and value != '—':
                    try:
                        item.setData(Qt.EditRole, float(value))
                    except Exception:
                        pass
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self.btnExportCsv.setEnabled(True)
        self.btnExportHtml.setEnabled(True)
        self.tabs.setCurrentIndex(1)

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Esporta risultati', 'GeoLichen_validation_results.csv', 'CSV (*.csv)')
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        try:
            self.service.export_csv(path, self.results)
            QMessageBox.information(self, 'Esportazione completata', path)
        except Exception as exc:
            QMessageBox.critical(self, 'Errore esportazione', str(exc))

    def export_html(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Esporta report', 'GeoLichen_validation_report.html', 'HTML (*.html)')
        if not path:
            return
        if not path.lower().endswith('.html'):
            path += '.html'
        try:
            self.service.export_html(path, self.summary, self.results, self.csv_path)
            QMessageBox.information(self, 'Report creato', path)
        except Exception as exc:
            QMessageBox.critical(self, 'Errore esportazione', str(exc))
