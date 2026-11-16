"""Explicit multi-row destinations for copying a confirmed georeference."""

from qgis.PyQt.QtCore import Qt, QItemSelectionModel
from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..services.confirmation_fields_service import ConfirmationFieldsService


class CopyPointTargetsDialog(QDialog):
    COLUMNS = (('record_id', 'Record'), ('taxon', 'Taxon'), ('locality', 'Località'),
               ('municipality', 'Comune'))

    @staticmethod
    def normalize(value):
        return ' '.join(str(value or '').casefold().split())

    @classmethod
    def same_locality(cls, row, source):
        locality = cls.normalize(source.get('locality'))
        municipality = cls.normalize(source.get('municipality'))
        return bool(locality and cls.normalize(row.get('locality')) == locality
                    and cls.normalize(row.get('municipality')) == municipality)

    def __init__(self, layer, rows, source, target_fields, selected_ids=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle('Copia su altri record — scegli le righe di destinazione')
        self.resize(950, 570)
        self.layer = layer
        self.rows = list(rows)
        self.source = source
        self.target_fields = dict(target_fields)
        layout = QVBoxLayout(self)
        summary = QLabel(f"Tabella: {layer.name()}\nPunto sorgente: {source.get('locality') or '-'} — "
                         f"{source.get('municipality') or '-'}\n"
                         'Seleziona le righe con Cmd/Ctrl o Maiusc. Nessuna riga viene selezionata automaticamente per somiglianza.')
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filtra per record, taxon, località o comune')
        layout.addWidget(self.search)
        self.chkSameLocality = QCheckBox('Mostra solo righe con la stessa località e lo stesso comune')
        self.chkSameLocality.setToolTip('Filtra le righe per località e comune del punto sorgente, senza selezionarle.')
        self.chkSameLocality.setChecked(bool(self.normalize(source.get('locality'))))
        layout.addWidget(self.chkSameLocality)
        self.table = QTableWidget(len(self.rows), len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _, label in self.COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        for index, row in enumerate(self.rows):
            for column, (key, _) in enumerate(self.COLUMNS):
                item = QTableWidgetItem(str(row.get(key) or ''))
                item.setData(Qt.ItemDataRole.UserRole, row['fid'])
                self.table.setItem(index, column, item)
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        self.lblSelection = QLabel()
        layout.addWidget(self.lblSelection)
        self.lblFields = QLabel()
        self.lblFields.setWordWrap(True)
        layout.addWidget(self.lblFields)
        actions = QHBoxLayout()
        self.btnCreateFields = QPushButton('Crea le colonne mancanti')
        self.btnCreateFields.setToolTip('Crea nella tabella le colonne mancanti per ricevere i dati del punto copiato.')
        self.btnCreateFields.clicked.connect(self._create_fields)
        actions.addWidget(self.btnCreateFields)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip('Mostra il riepilogo prima di copiare i dati sulle righe selezionate.')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip('Annulla questo passaggio senza confermare i dati.')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Continua')
        self.buttons.accepted.connect(self._accept_targets)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.search.textChanged.connect(self._filter)
        self.chkSameLocality.toggled.connect(self._filter)
        self.table.itemSelectionChanged.connect(self._update_status)
        self._filter()
        selection = self.table.selectionModel()
        for index, row in enumerate(self.rows):
            if row['fid'] in selected_ids and not self.table.isRowHidden(index):
                selection.select(self.table.model().index(index, 0),
                                 QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self._update_status()

    def _filter(self, *_):
        needle = self.normalize(self.search.text())
        for index, row in enumerate(self.rows):
            visible = ((not self.chkSameLocality.isChecked() or self.same_locality(row, self.source))
                       and (not needle or needle in self.normalize(' '.join(str(row.get(k) or '') for k, _ in self.COLUMNS))))
            if not visible:
                # Hidden rows must never remain selected for a later write.
                self.table.selectionModel().select(self.table.model().index(index, 0),
                                                  QItemSelectionModel.SelectionFlag.Deselect | QItemSelectionModel.SelectionFlag.Rows)
            self.table.setRowHidden(index, not visible)
        self._update_status()

    def selected_ids(self):
        return [self.rows[index.row()]['fid'] for index in self.table.selectionModel().selectedRows()
                if not self.table.isRowHidden(index.row())]

    def _update_status(self):
        count = len(self.selected_ids())
        self.lblSelection.setText(f'{count} righe selezionate')
        missing = [label for key, _, label, _ in ConfirmationFieldsService.FIELDS
                   if not self.target_fields.get(key)]
        self.lblFields.setText('Colonne mancanti: ' + ', '.join(missing) if missing else 'Tutte le colonne di destinazione sono disponibili.')
        self.btnCreateFields.setVisible(bool(missing))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            bool(count and self.target_fields.get('x_field') and self.target_fields.get('y_field')))

    def _create_fields(self):
        try:
            self.target_fields, _ = ConfirmationFieldsService.ensure_fields(self.layer, self.target_fields)
            self._update_status()
        except Exception as exc:
            QMessageBox.warning(self, 'Creazione colonne', str(exc))

    def _accept_targets(self):
        if self.selected_ids() and self.target_fields.get('x_field') and self.target_fields.get('y_field'):
            self.accept()
