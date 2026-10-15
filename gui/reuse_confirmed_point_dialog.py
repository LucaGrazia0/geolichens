from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class ReuseConfirmedPointDialog(QDialog):
    """Seleziona una georeferenziazione già confermata da riutilizzare."""

    COLUMNS = (
        ("taxon", "Taxon"),
        ("locality", "Località"),
        ("municipality", "Comune"),
        ("longitude", "X"),
        ("latitude", "Y"),
        ("altitude_m", "Quota DEM"),
        ("uncert_m", "Incertezza GBIF"),
        ("model_r_m", "R55–S70"),
        ("confirmed", "Confermato il"),
    )

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Riutilizza punto già confermato")
        self.resize(1050, 520)
        self._rows = list(rows or [])
        self._visible_rows = []

        layout = QVBoxLayout(self)
        label = QLabel(
            "Seleziona il punto da copiare nel record corrente. "
            "Coordinate, quota DEM e incertezze verranno riutilizzate senza rieseguire l’analisi."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Cerca"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Taxon, località, comune o coordinate")
        search_row.addWidget(self.search)
        layout.addLayout(search_row)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([title for _, title in self.COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self.accept)
        layout.addWidget(self.table)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Copia questo punto")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.search.textChanged.connect(self._apply_filter)
        self._apply_filter("")

    @staticmethod
    def _display_value(value):
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.6f}".rstrip("0").rstrip(".")
        return str(value)

    def _apply_filter(self, text):
        needle = (text or "").strip().casefold()
        self._visible_rows = []
        for row in self._rows:
            haystack = " ".join(str(row.get(key, "")) for key, _ in self.COLUMNS).casefold()
            if not needle or needle in haystack:
                self._visible_rows.append(row)

        self.table.setRowCount(len(self._visible_rows))
        for row_idx, row in enumerate(self._visible_rows):
            for col_idx, (key, _) in enumerate(self.COLUMNS):
                item = QTableWidgetItem(self._display_value(row.get(key)))
                if key in {"longitude", "latitude", "altitude_m", "uncert_m", "model_r_m"}:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row_idx, col_idx, item)
        self.table.resizeColumnsToContents()
        if self._visible_rows:
            self.table.selectRow(0)

    def selected_row(self):
        row_idx = self.table.currentRow()
        if row_idx < 0 or row_idx >= len(self._visible_rows):
            return None
        return dict(self._visible_rows[row_idx])
