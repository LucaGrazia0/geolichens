from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
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

    def __init__(self, candidates, parent=None, title="Seleziona località", preview_callback=None,
                 search_callback=None, query='', area_search_callback=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1100, 460)
        self.candidates = candidates or []
        self.selected_feature = None
        self.preview_callback = preview_callback
        self.search_callback = search_callback
        self.area_search_callback = area_search_callback
        self.search_aliases = []

        layout = QVBoxLayout(self)

        count_text = ('È stata trovata una località. ' if len(self.candidates) == 1
                      else f'Sono state trovate {len(self.candidates)} località candidate. ')
        self.intro = QLabel(count_text +
            'Verifica la località e seleziona «Crea buffer» per proseguire. '
            'Puoi confermare anche con doppio click oppure annullare per usare gli strumenti manuali.')
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        self.query_edit = QLineEdit(query)
        self.query_edit.setPlaceholderText('Nome della località, anche corretto o alternativo')
        self.search_button = QPushButton('Cerca altre località')
        self.search_button.setToolTip('Confronta varianti del nome e del comune; conserva le alternative già trovate.')
        row = QHBoxLayout()
        row.addWidget(self.query_edit, 1); row.addWidget(self.search_button)
        layout.addLayout(row)
        self.query_edit.setVisible(search_callback is not None or area_search_callback is not None)
        self.search_button.setVisible(search_callback is not None)
        self.search_button.clicked.connect(self._search_more)
        self.area_search_button = QPushButton('Cerca nella zona iniziale della mappa')
        self.area_search_button.setToolTip(
            'Inquadra la zona prima di avviare Ricerca della località. Cerca solo in quella zona; '
            'l’anteprima dei candidati non la modifica. Non cambia l’area configurata né crea un buffer.')
        self.area_search_button.setVisible(area_search_callback is not None)
        self.area_search_button.clicked.connect(self._search_in_area)
        layout.addWidget(self.area_search_button)
        self.search_status = QLabel('')
        self.search_status.setWordWrap(True)
        layout.addWidget(self.search_status)

        self.table = QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Consigliato", "Nome", "Tipo", "Score ricerca", "Distanza centro comune", "Motivo", "Centro", "BBox"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setRowCount(len(self.candidates))

        self._populate()

        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(self._on_double_click)

        layout.addWidget(self.table)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Crea buffer')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.candidates))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setAutoDefault(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Annulla')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip('Usa la località selezionata per definire l’area di ricerca.')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip('Annulla questo passaggio senza confermare i dati.')
        self.buttons.accepted.connect(self._accept_selection)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _populate(self):
        count_text = ('È stata trovata una località. ' if len(self.candidates) == 1
                      else f'Sono disponibili {len(self.candidates)} località candidate. ')
        self.intro.setText(count_text + 'Verifica la località e seleziona «Crea buffer» per proseguire. '
                           'Puoi modificare il nome per approfondire la ricerca oppure annullare per usare gli strumenti manuali.')
        self.table.setRowCount(len(self.candidates))
        for row, feature in enumerate(self.candidates):
            self._set_item(row, 0, "✓" if row == 0 and not feature.get('_geolichen_partial_name') else "")
            self._set_item(row, 1, self._place_name(feature))
            self._set_item(row, 2, self._place_type(feature))
            self._set_item(row, 3, self._score(feature))
            self._set_item(row, 4, self._distance(feature))
            reason = str(feature.get('_geolichen_score_reason') or '-')
            if feature.get('_geolichen_partial_name'):
                reason = 'Nome parziale: identità della località da verificare; ' + reason
            if feature.get('_geolichen_confirmed_locality'):
                reason += '; archivio locale, confermata ' + str(feature.get('_geolichen_confirmed_at') or '')
            elif feature.get('provider'):
                reason += '; fonte: ' + str(feature['provider'])
            queries = feature.get('_geolichen_queries') or [feature.get('_geolichen_query')]
            queries = [str(q) for q in queries if q]
            if queries:
                reason += '; ricerche: ' + ' | '.join(queries)
            self._set_item(row, 5, reason)
            self._set_item(row, 6, self._center(feature))
            self._set_item(row, 7, self._bbox(feature))

        self.table.resizeColumnsToContents()
        if self.candidates:
            self.table.selectRow(0)
            self._preview_row(0)

    def _search_more(self):
        self._perform_search(self.search_callback)

    def _search_in_area(self):
        self._perform_search(self.area_search_callback)

    def _perform_search(self, callback):
        query = self.query_edit.text().strip()
        if not query or callback is None:
            return
        self.search_button.setEnabled(False)
        self.area_search_button.setEnabled(False)
        self.buttons.setEnabled(False)
        self.table.setEnabled(False)
        self.search_status.setText('Ricerca approfondita in corso…')
        self.search_status.repaint()
        try:
            result = callback(query, self.candidates)
            if result.candidates:
                self.candidates = result.candidates
                self.search_aliases.append(query)
                self._populate()
            warning = ' '.join(str(value) for value in (result.error, getattr(result, 'warning', None)) if value)
            if not result.candidates and self.candidates:
                warning += ' Nessun nuovo risultato; alternative precedenti conservate.'
            self.search_status.setText(f'{len(self.candidates)} località disponibili. {warning}')
        except Exception as exc:
            self.search_status.setText(f'Ricerca non disponibile: {exc}. Risultati precedenti conservati.')
        finally:
            self.search_button.setEnabled(True)
            self.area_search_button.setEnabled(True)
            self.buttons.setEnabled(True)
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.candidates))
            self.table.setEnabled(True)

    def _set_item(self, row, col, text):
        item = QTableWidgetItem(str(text or ""))
        item.setToolTip(str(text or ''))
        if col in [0, 3, 4]:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(row, col, item)

    def _place_name(self, feature):
        return feature.get("place_name") or feature.get("text") or "-"

    def _place_type(self, feature):
        props = feature.get('properties') or {}
        labels = {('natural', 'peak'): 'Cima', ('natural', 'saddle'): 'Passo',
                  ('mountain_pass', 'yes'): 'Passo', ('natural', 'water'): 'Specchio d’acqua',
                  ('water', 'lake'): 'Lago', ('natural', 'wood'): 'Bosco',
                  ('landuse', 'forest'): 'Bosco', ('natural', 'valley'): 'Valle',
                  ('tourism', 'alpine_hut'): 'Rifugio', ('tourism', 'wilderness_hut'): 'Bivacco',
                  ('highway', 'path'): 'Sentiero', ('highway', 'footway'): 'Percorso pedonale',
                  ('highway', 'track'): 'Pista', ('boundary', 'administrative'): 'Area amministrativa'}
        label = labels.get((props.get('osm_key'), props.get('osm_value')))
        if label:
            return label
        pt = feature.get("place_type") or feature.get("type") or ""
        if isinstance(pt, (list, tuple)):
            return ", ".join(str(x) for x in pt)
        return str(pt)

    def _score(self, feature):
        try:
            if '_geolichen_score' not in feature:
                return '—'
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
        if self.selected_feature is not None:
            self.accept()

    def selected(self):
        return self.selected_feature
