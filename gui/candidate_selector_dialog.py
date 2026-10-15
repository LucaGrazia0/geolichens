from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class CandidateSelectorDialog(QDialog):
    """Dialog per scegliere manualmente il candidato di geocoding più corretto.

    Migliorie:
    - doppio click per confermare;
    - distanza dal comune, se disponibile;
    - motivazione dello score;
    - callback opzionale per preview bbox/centro sulla mappa.
    """

    def __init__(self, candidates, parent=None, title="Seleziona località", preview_callback=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1100, 460)
        self.candidates = candidates or []
        self.selected_feature = None
        self.preview_callback = preview_callback

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Sono stati trovati più candidati plausibili. "
            "Seleziona la località corretta e conferma con OK. "
            "Puoi confermare anche con doppio click."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Consigliato", "Nome", "Tipo", "Score", "Distanza comune", "Motivo", "Centro", "BBox"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setRowCount(len(self.candidates))

        for row, feature in enumerate(self.candidates):
            self._set_item(row, 0, "✓" if row == 0 else "")
            self._set_item(row, 1, self._place_name(feature))
            self._set_item(row, 2, self._place_type(feature))
            self._set_item(row, 3, self._score(feature))
            self._set_item(row, 4, self._distance(feature))
            self._set_item(row, 5, str(feature.get("_geolichen_score_reason") or "-"))
            self._set_item(row, 6, self._center(feature))
            self._set_item(row, 7, self._bbox(feature))

        self.table.resizeColumnsToContents()
        if self.candidates:
            self.table.selectRow(0)
            self._preview_row(0)

        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(self._on_double_click)

        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_item(self, row, col, text):
        item = QTableWidgetItem(str(text or ""))
        if col in [0, 3, 4]:
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row, col, item)

    def _place_name(self, feature):
        return feature.get("place_name") or feature.get("text") or "-"

    def _place_type(self, feature):
        pt = feature.get("place_type") or feature.get("type") or ""
        if isinstance(pt, (list, tuple)):
            return ", ".join(str(x) for x in pt)
        return str(pt)

    def _score(self, feature):
        try:
            return f"{float(feature.get('_geolichen_score', 0.0)):.1f}"
        except Exception:
            return "-"

    def _distance(self, feature):
        dist = feature.get("_geolichen_distance_to_municipality_m")
        try:
            if dist is None:
                return "-"
            dist = float(dist)
            if dist < 1000:
                return f"{round(dist)} m"
            return f"{dist/1000:.1f} km"
        except Exception:
            return "-"

    def _center(self, feature):
        center = feature.get("center")
        if center and len(center) == 2:
            try:
                return f"{float(center[0]):.6f}, {float(center[1]):.6f}"
            except Exception:
                return str(center)
        return "-"

    def _bbox(self, feature):
        bbox = feature.get("bbox")
        if bbox and len(bbox) == 4:
            try:
                return ", ".join(f"{float(v):.5f}" for v in bbox)
            except Exception:
                return str(bbox)
        return "-"

    def _current_row(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return 0 if self.candidates else -1
        return indexes[0].row()

    def _on_selection_changed(self):
        self._preview_row(self._current_row())

    def _preview_row(self, row):
        if self.preview_callback is None:
            return
        if 0 <= row < len(self.candidates):
            try:
                self.preview_callback(self.candidates[row])
            except Exception:
                pass

    def _on_double_click(self, item):
        self._accept_selection()

    def _accept_selection(self):
        row = self._current_row()
        self.selected_feature = self.candidates[row] if 0 <= row < len(self.candidates) else None
        self.accept()

    def selected(self):
        return self.selected_feature
