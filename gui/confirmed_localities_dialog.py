"""Inspect and remove saved locality anchors without editing specimen tables."""
from qgis.PyQt.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                                QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)


class ConfirmedLocalitiesDialog(QDialog):
    def __init__(self, archive, parent=None):
        super().__init__(parent)
        self.archive = archive
        self.setWindowTitle('Archivio località confermate')
        self.resize(850, 420)
        layout = QVBoxLayout(self)
        label = QLabel('Punti geografici confermati, conservati nel profilo QGIS anche dopo la chiusura. '
                       'Ogni record mantiene la propria analisi ecologica.')
        label.setWordWrap(True); layout.addWidget(label)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Nome del record', 'Comune', 'Località scelta', 'Confermata il (UTC)'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        remove = QPushButton('Rimuovi la località selezionata dall’archivio')
        remove.setToolTip('Dimentica questa associazione; alla prossima ricerca verrà nuovamente interrogato il geocoder.')
        remove.clicked.connect(self._remove); layout.addWidget(remove)
        self.status = QLabel(''); self.status.setWordWrap(True); layout.addWidget(self.status)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject); layout.addWidget(close)
        self._refresh()

    def _refresh(self):
        self.entries = self.archive.entries()
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            values = [entry.get('query', ''), entry.get('municipality', ''),
                      entry['feature'].get('place_name', entry['feature'].get('text', '')),
                      entry.get('confirmed_at', '')]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()

    def _remove(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return
        entry = self.entries[indexes[0].row()]
        try:
            self.archive.remove(entry['query'], entry['municipality'])
            self._refresh()
            self.status.setText('Località rimossa dall’archivio.')
        except (OSError, ValueError) as exc:
            self.status.setText(f'Impossibile aggiornare l’archivio: {exc}')
