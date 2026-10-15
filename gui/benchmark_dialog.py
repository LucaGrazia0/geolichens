import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget
)

from ..services.benchmark_service import BenchmarkService


class BenchmarkDialog(QDialog):
    OPTIONAL = '— Non disponibile —'
    METHOD_DEFAULTS = ('GeoLichen', 'GEOLocate', 'Geocoder semplice', 'Centroide comunale', 'Manuale')

    BASE_FIELDS = [
        ('record_id', 'ID record', False, ['id', 'record_id', 'catalogNumber', 'numero']),
        ('reference_longitude', 'Longitudine gold standard', True, ['reference_longitude', 'ref_lon', 'gold_lon', 'longitude_ref']),
        ('reference_latitude', 'Latitudine gold standard', True, ['reference_latitude', 'ref_lat', 'gold_lat', 'latitude_ref']),
    ]

    METHOD_ALIASES = {
        'GeoLichen': (['geolichen_latitude', 'geolichen_lat', 'latitude'], ['geolichen_longitude', 'geolichen_lon', 'longitude'], ['geolichen_runtime_s', 'runtime_s']),
        'GEOLocate': (['geolocate_latitude', 'geolocate_lat'], ['geolocate_longitude', 'geolocate_lon'], ['geolocate_runtime_s']),
        'Geocoder semplice': (['geocoder_latitude', 'geocoder_lat'], ['geocoder_longitude', 'geocoder_lon'], ['geocoder_runtime_s']),
        'Centroide comunale': (['centroid_latitude', 'municipality_latitude', 'comune_lat'], ['centroid_longitude', 'municipality_longitude', 'comune_lon'], ['centroid_runtime_s']),
        'Manuale': (['manual_latitude', 'manual_lat'], ['manual_longitude', 'manual_lon'], ['manual_runtime_s']),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('GeoLichen — Fase 12.2 Benchmark Framework')
        self.resize(1180, 780)
        self.service = BenchmarkService()
        self.csv_path = ''
        self.headers = []
        self.source_rows = []
        self.results = []
        self.winner_rows = []
        self.summary = {}
        self.base_combos = {}
        self.method_widgets = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        intro = QLabel('Confronta GeoLichen con altri metodi usando lo stesso gold standard. Il modulo legge coordinate già prodotte: non richiama né simula GEOLocate o altri software.')
        intro.setWordWrap(True)
        layout.addWidget(intro)

        file_row = QHBoxLayout()
        self.btnLoad = QPushButton('Carica dataset CSV')
        self.lblFile = QLabel('Nessun dataset caricato')
        self.lblFile.setTextInteractionFlags(Qt.TextSelectableByMouse)
        file_row.addWidget(self.btnLoad)
        file_row.addWidget(self.lblFile, 1)
        layout.addLayout(file_row)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        setup_page = QWidget()
        setup_layout = QVBoxLayout(setup_page)
        base_group = QGroupBox('Gold standard')
        base_form = QFormLayout(base_group)
        for key, label, required, aliases in self.BASE_FIELDS:
            combo = QComboBox()
            combo.setEnabled(False)
            self.base_combos[key] = combo
            base_form.addRow(label + (' *' if required else ''), combo)
        setup_layout.addWidget(base_group)

        methods_group = QGroupBox('Metodi da confrontare')
        methods_layout = QVBoxLayout(methods_group)
        for default_name in self.METHOD_DEFAULTS:
            box = QGroupBox(default_name)
            form = QFormLayout(box)
            name_edit = QLineEdit(default_name)
            lat_combo = QComboBox(); lat_combo.setEnabled(False)
            lon_combo = QComboBox(); lon_combo.setEnabled(False)
            runtime_combo = QComboBox(); runtime_combo.setEnabled(False)
            form.addRow('Nome metodo', name_edit)
            form.addRow('Latitudine', lat_combo)
            form.addRow('Longitudine', lon_combo)
            form.addRow('Tempo di esecuzione (s)', runtime_combo)
            methods_layout.addWidget(box)
            self.method_widgets.append({
                'default_name': default_name, 'name': name_edit,
                'latitude': lat_combo, 'longitude': lon_combo, 'runtime_s': runtime_combo,
            })
        self.btnRun = QPushButton('Esegui benchmark')
        self.btnRun.setEnabled(False)
        methods_layout.addWidget(self.btnRun)
        setup_layout.addWidget(methods_group)
        setup_layout.addStretch(1)
        self.tabs.addTab(setup_page, 'Dataset e metodi')

        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        self.txtSummary = QTextEdit()
        self.txtSummary.setReadOnly(True)
        self.txtSummary.setMaximumHeight(230)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(['Pos.', 'Metodo', 'N', 'MAE (m)', 'Mediana (m)', 'RMSE (m)', '≤100 m', '≤500 m', 'Vittorie', 'Tempo medio (s)'])
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

        close_row = QHBoxLayout(); close_row.addStretch(1)
        btnClose = QPushButton('Chiudi'); close_row.addWidget(btnClose)
        layout.addLayout(close_row)

        self.btnLoad.clicked.connect(self.load_csv)
        self.btnRun.clicked.connect(self.run_benchmark)
        self.btnExportCsv.clicked.connect(self.export_csv)
        self.btnExportHtml.clicked.connect(self.export_html)
        btnClose.clicked.connect(self.accept)

    @staticmethod
    def _norm(value):
        return str(value).lower().replace(' ', '').replace('_', '').replace('-', '')

    def _populate_combo(self, combo, optional=True, aliases=None):
        combo.blockSignals(True)
        combo.clear()
        if optional:
            combo.addItem(self.OPTIONAL, '')
        for header in self.headers:
            combo.addItem(header, header)
        normalized = {self._norm(h): h for h in self.headers}
        for alias in aliases or []:
            candidate = normalized.get(self._norm(alias))
            if candidate:
                idx = combo.findData(candidate)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                    break
        combo.setEnabled(True)
        combo.blockSignals(False)

    def load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Apri dataset di benchmark', '', 'CSV (*.csv *.txt);;Tutti i file (*)')
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
        for key, label, required, aliases in self.BASE_FIELDS:
            self._populate_combo(self.base_combos[key], optional=not required, aliases=aliases)
        for widgets in self.method_widgets:
            lat_aliases, lon_aliases, runtime_aliases = self.METHOD_ALIASES.get(widgets['default_name'], ([], [], []))
            self._populate_combo(widgets['latitude'], True, lat_aliases)
            self._populate_combo(widgets['longitude'], True, lon_aliases)
            self._populate_combo(widgets['runtime_s'], True, runtime_aliases)
        self.btnRun.setEnabled(True)

    def _methods(self):
        methods = []
        for widgets in self.method_widgets:
            lat = widgets['latitude'].currentData()
            lon = widgets['longitude'].currentData()
            if lat or lon:
                methods.append({
                    'name': widgets['name'].text().strip(),
                    'latitude': lat,
                    'longitude': lon,
                    'runtime_s': widgets['runtime_s'].currentData(),
                })
        return methods

    def run_benchmark(self):
        base = {key: combo.currentData() for key, combo in self.base_combos.items()}
        missing = [label for key, label, required, _ in self.BASE_FIELDS if required and not base.get(key)]
        if missing:
            QMessageBox.warning(self, 'Campi obbligatori', 'Associa i seguenti campi:\n• ' + '\n• '.join(missing))
            return
        methods = self._methods()
        incomplete = [m['name'] or '(senza nome)' for m in methods if not m.get('latitude') or not m.get('longitude')]
        if incomplete:
            QMessageBox.warning(self, 'Metodi incompleti', 'Ogni metodo selezionato deve avere latitudine e longitudine:\n• ' + '\n• '.join(incomplete))
            return
        if len(methods) < 2:
            QMessageBox.warning(self, 'Benchmark non eseguibile', 'Seleziona almeno due metodi completi da confrontare.')
            return
        try:
            self.results, skipped, self.winner_rows = self.service.benchmark(self.source_rows, base, methods)
            if not self.results:
                raise ValueError('Nessun risultato valido dopo il controllo delle coordinate.')
            self.summary = self.service.summarize(self.results, self.winner_rows, len(skipped))
            self._show_results(skipped)
        except Exception as exc:
            QMessageBox.critical(self, 'Errore benchmark', str(exc))

    @staticmethod
    def _fmt(value, digits=1):
        return '—' if value is None else f'{value:.{digits}f}'

    def _show_results(self, skipped):
        ranking = self.summary.get('ranking_by_mae', [])
        methods = self.summary.get('methods', {})
        best = self.summary.get('best_method_by_mae')
        lines = [
            f"Record confrontati: {self.summary.get('records_compared', 0)}    Record scartati: {self.summary.get('records_skipped', 0)}",
            f"Metodi valutati: {len(methods)}",
            '',
            f"Migliore MAE complessivo: {best or '—'}",
        ]
        for pos, name in enumerate(ranking, start=1):
            s = methods[name]
            lines.append(f"{pos}. {name}: MAE {self._fmt(s.get('mae_m'))} m; mediana {self._fmt(s.get('median_m'))} m; RMSE {self._fmt(s.get('rmse_m'))} m; vittorie {self._fmt(s.get('win_pct'))}%")
        if skipped:
            lines.extend(['', f"Prime righe scartate: {', '.join(str(i) for i, _ in skipped[:10])}"])
        self.txtSummary.setPlainText('\n'.join(lines))

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(ranking))
        for row_idx, name in enumerate(ranking):
            s = methods[name]
            values = [
                row_idx + 1, name, s.get('n', 0), self._fmt(s.get('mae_m')),
                self._fmt(s.get('median_m')), self._fmt(s.get('rmse_m')),
                self._fmt(s.get('within_100_pct')) + '%', self._fmt(s.get('within_500_pct')) + '%',
                self._fmt(s.get('win_pct')) + '%', self._fmt(s.get('mean_runtime_s'), 2),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col in (0, 2, 3, 4, 5, 6, 7, 8, 9):
                    try:
                        item.setData(Qt.EditRole, float(str(value).replace('%', '')))
                    except Exception:
                        pass
                self.table.setItem(row_idx, col, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self.btnExportCsv.setEnabled(True)
        self.btnExportHtml.setEnabled(True)
        self.tabs.setCurrentIndex(1)

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Esporta benchmark', 'GeoLichen_benchmark_results.csv', 'CSV (*.csv)')
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        try:
            self.service.export_long_csv(path, self.results)
            QMessageBox.information(self, 'Esportazione completata', path)
        except Exception as exc:
            QMessageBox.critical(self, 'Errore esportazione', str(exc))

    def export_html(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Esporta report', 'GeoLichen_benchmark_report.html', 'HTML (*.html)')
        if not path:
            return
        if not path.lower().endswith('.html'):
            path += '.html'
        try:
            self.service.export_html(path, self.summary, self.results, self.winner_rows, self.csv_path)
            QMessageBox.information(self, 'Report creato', path)
        except Exception as exc:
            QMessageBox.critical(self, 'Errore esportazione', str(exc))
