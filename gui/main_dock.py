from qgis.PyQt.QtCore import Qt
from qgis.PyQt import sip
from ..services.search_area_service import SearchAreaService
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class MainDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__('GeoLichen', parent or iface.mainWindow())
        self.iface = iface
        self.setMinimumWidth(420)

        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(8)

        # ------------------------------------------------------------
        # CONFIGURAZIONE
        # ------------------------------------------------------------
        gb_config = QGroupBox('Configurazione')
        config_form = QFormLayout(gb_config)
        config_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.txtApiKey = QLineEdit()
        self.txtApiKey.setPlaceholderText('API key MapTiler')

        self.cmbSearchArea = QComboBox()
        self.cmbSearchArea.addItems(SearchAreaService.names())
        self.cmbSearchArea.setCurrentText(SearchAreaService.DEFAULT_AREA)

        self.chkLimitSearchArea = QCheckBox('Limita la ricerca all’area selezionata')
        self.chkLimitSearchArea.setChecked(True)
        self.chkAutoExpandSearchArea = QCheckBox('Espandi automaticamente se nessun risultato plausibile')
        self.chkAutoExpandSearchArea.setChecked(True)

        self.txtBbox = QLineEdit(
            SearchAreaService.bbox_to_text(
                SearchAreaService.bbox_for(SearchAreaService.DEFAULT_AREA)
            )
        )
        self.txtBbox.setPlaceholderText('xmin,ymin,xmax,ymax')
        self.txtBbox.setEnabled(False)

        self.btnConfigureFields = QPushButton('⚙  Configura campi input')

        config_form.addRow('API key', self.txtApiKey)
        config_form.addRow('Area di ricerca', self.cmbSearchArea)
        config_form.addRow(self.chkLimitSearchArea)
        config_form.addRow(self.chkAutoExpandSearchArea)
        config_form.addRow('BBox personalizzata', self.txtBbox)
        config_form.addRow(self.btnConfigureFields)
        outer_layout.addWidget(gb_config)

        # ------------------------------------------------------------
        # GEOREFERENZIAZIONE - controller operativo principale
        # ------------------------------------------------------------
        gb_geo = QGroupBox('Georeferenziazione')
        geo_layout = QVBoxLayout(gb_geo)
        geo_layout.setSpacing(8)

        self.btnAnalyze = QPushButton('Analizza record selezionato')
        self.btnAnalyze.setMinimumHeight(32)
        geo_layout.addWidget(self.btnAnalyze)

        # Strumenti mantenuti per compatibilità con il controller, ma non
        # più mostrati nell'interfaccia principale.
        self.btnItalic = QPushButton('Leggi profilo ITALIC')
        self.btnItalic.setVisible(False)
        self.btnRedefineBuffer = QPushButton('Ridefinisci buffer')
        self.btnRedefineBuffer.setVisible(False)
        self.txtHeatmapRadius = QLineEdit('18')
        self.txtHeatmapRadius.setVisible(False)
        self.txtHeatmapOpacity = QLineEdit('60')
        self.txtHeatmapOpacity.setVisible(False)

        # Punto manuale
        point_box = QGroupBox('Punto manuale')
        point_form = QFormLayout(point_box)
        self.txtManualBuffer = QLineEdit('250')
        self.txtManualBuffer.setPlaceholderText('Raggio in metri')
        self.btnManualPoint = QPushButton('Punto manuale + buffer')
        point_form.addRow('Buffer (m)', self.txtManualBuffer)
        point_form.addRow(self.btnManualPoint)
        geo_layout.addWidget(point_box)

        # Linea manuale
        line_box = QGroupBox('Linea manuale')
        line_form = QFormLayout(line_box)
        self.txtManualLineOffset = QLineEdit('500')
        self.txtManualLineOffset.setPlaceholderText('Offset laterale in metri')
        self.btnManualLine = QPushButton('Linea manuale + offset')
        line_form.addRow('Offset (m)', self.txtManualLineOffset)
        line_form.addRow(self.btnManualLine)
        geo_layout.addWidget(line_box)

        model_form = QFormLayout()
        self.txtSuitabilityGridStep = QLineEdit('30')
        self.txtSuitabilityGridStep.setPlaceholderText('Passo griglia in metri')
        self.cmbSuitabilityView = QComboBox()
        self.cmbSuitabilityView.addItems(['Punti candidati', 'Suitability Surface', 'Entrambi'])
        self.cmbSuitabilityView.setCurrentText('Punti candidati')
        model_form.addRow('Passo griglia (m)', self.txtSuitabilityGridStep)
        model_form.addRow('Visualizzazione', self.cmbSuitabilityView)
        geo_layout.addLayout(model_form)

        self.btnHabitatSuitability = QPushButton('Trova punto ecologico più probabile')
        self.btnHabitatSuitability.setMinimumHeight(32)
        geo_layout.addWidget(self.btnHabitatSuitability)

        actions = QHBoxLayout()
        self.btnReuseConfirmedPoint = QPushButton('Copia punto')
        self.btnConfirmPoint = QPushButton('Conferma punto ecologico')
        actions.addWidget(self.btnReuseConfirmedPoint)
        actions.addWidget(self.btnConfirmPoint)
        geo_layout.addLayout(actions)

        outer_layout.addWidget(gb_geo)

        # ------------------------------------------------------------
        # LAYER AMBIENTALI - invariati
        # ------------------------------------------------------------
        gb_layers = QGroupBox('Layer ambientali')
        layers_form = QFormLayout(gb_layers)
        self.cmbGeologyLayer = QComboBox()
        self.cmbGeologyField = QComboBox()
        self.btnCreateGroupLito = QPushButton('Crea / aggiorna GRUPPO_LITO')
        self.lblGroupLitoInfo = QLabel('-')
        self.lblGroupLitoInfo.setWordWrap(True)
        self.cmbSoilLayer = QComboBox()
        self.cmbSoilField = QComboBox()
        self.cmbTreesLayer = QComboBox()
        self.cmbTreesField = QComboBox()
        self.cmbTrailLayer = QComboBox()
        self.chkUseOsmTrails = QCheckBox('Usa dati sentieristici OpenStreetMap')
        self.chkUseOsmTrails.setChecked(True)
        self.chkShowOsmTrails = QCheckBox('Mostra layer OSM scaricato')
        self.chkShowOsmTrails.setChecked(True)
        self.lstAccessibilityLayers = QListWidget()
        self.lstAccessibilityLayers.setMinimumHeight(90)
        self.lstAccessibilityLayers.setMaximumHeight(160)
        self.cmbVegetationBeltLayer = QComboBox()
        self.cmbVegetationBeltField = QComboBox()
        self.cmbDemLayer = QComboBox()
        self.cmbDemLayer.setVisible(False)
        self.lstDemLayers = QListWidget()
        self.lstDemLayers.setMinimumHeight(90)
        self.lstDemLayers.setMaximumHeight(160)
        self.lstDemLayers.setDragDropMode(QListWidget.InternalMove)
        layers_form.addRow('Geologia/Litologia', self.cmbGeologyLayer)
        layers_form.addRow('Campo geologia', self.cmbGeologyField)
        layers_form.addRow(self.btnCreateGroupLito)
        layers_form.addRow('Esito GRUPPO_LITO', self.lblGroupLitoInfo)
        layers_form.addRow('Suolo', self.cmbSoilLayer)
        layers_form.addRow('Campo suolo', self.cmbSoilField)
        layers_form.addRow('Alberi/Boschi', self.cmbTreesLayer)
        layers_form.addRow('Campo alberi', self.cmbTreesField)
        layers_form.addRow('Layer accessibilità', self.lstAccessibilityLayers)
        layers_form.addRow(self.chkUseOsmTrails)
        layers_form.addRow(self.chkShowOsmTrails)
        layers_form.addRow('Fasce vegetazionali', self.cmbVegetationBeltLayer)
        layers_form.addRow('Campo fascia vegetazionale', self.cmbVegetationBeltField)
        layers_form.addRow('Layer DEM (priorità dall’alto)', self.lstDemLayers)
        outer_layout.addWidget(gb_layers)

        # ------------------------------------------------------------
        # PROFILO ITALIC - invariato, letto dalla pipeline
        # ------------------------------------------------------------
        gb_italic = QGroupBox('Profilo ITALIC')
        italic_form = QFormLayout(gb_italic)
        self.lblItalicTaxon = QLabel('-')
        self.lblItalicTaxon.setWordWrap(True)
        self.lblItalicSubstrata = QLabel('-')
        self.lblItalicSubstrata.setWordWrap(True)
        self.lblItalicRock = QLabel('-')
        self.lblItalicRock.setWordWrap(True)
        self.lblItalicTree = QLabel('-')
        self.lblItalicTree.setWordWrap(True)
        self.lblItalicEcology = QTextEdit()
        self.lblItalicEcology.setReadOnly(True)
        self.lblItalicEcology.setLineWrapMode(QTextEdit.WidgetWidth)
        self.lblItalicEcology.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.lblItalicEcology.setMinimumHeight(140)
        self.lblItalicEcology.setMaximumHeight(260)
        self.lblItalicUrl = QLabel('-')
        self.lblItalicUrl.setWordWrap(True)
        italic_form.addRow('Taxon ITALIC', self.lblItalicTaxon)
        italic_form.addRow('Substrata', self.lblItalicSubstrata)
        italic_form.addRow('Roccia', self.lblItalicRock)
        italic_form.addRow('Albero', self.lblItalicTree)
        italic_form.addRow('Note ecologiche', self.lblItalicEcology)
        italic_form.addRow('Fonte', self.lblItalicUrl)
        outer_layout.addWidget(gb_italic)

        # ------------------------------------------------------------
        # RISULTATO - Esito + Punto ecologico condensati
        # ------------------------------------------------------------
        gb_result = QGroupBox('Risultato')
        result_layout = QVBoxLayout(gb_result)
        result_form = QFormLayout()

        self.lblStatus = QLabel('Pronto')
        self.lblStatus.setWordWrap(True)
        self.lblFoundPlace = QLabel('-')
        self.lblFoundPlace.setWordWrap(True)
        self.lblMatchType = QLabel('-')
        self.lblMatchType.setWordWrap(True)
        self.lblHabitatSuitability = QLabel('-')
        self.lblHabitatSuitability.setWordWrap(True)

        result_form.addRow('Stato', self.lblStatus)
        result_form.addRow('Luogo trovato', self.lblFoundPlace)
        result_form.addRow('Tipo match', self.lblMatchType)
        result_form.addRow('Punto ecologico', self.lblHabitatSuitability)
        result_layout.addLayout(result_form)

        self.btnResultDetails = QToolButton()
        self.btnResultDetails.setText('Dettagli')
        self.btnResultDetails.setCheckable(True)
        self.btnResultDetails.setChecked(False)
        self.btnResultDetails.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btnResultDetails.setArrowType(Qt.RightArrow)
        result_layout.addWidget(self.btnResultDetails)

        self.resultDetailsWidget = QWidget()
        details_form = QFormLayout(self.resultDetailsWidget)
        self.lblTriedQueries = QLabel('-')
        self.lblTriedQueries.setWordWrap(True)
        self.lblCandidates = QLabel('-')
        self.lblCandidates.setWordWrap(True)
        self.txtHabitatTop10 = QTextEdit()
        self.txtHabitatTop10.setReadOnly(True)
        self.txtHabitatTop10.setLineWrapMode(QTextEdit.NoWrap)
        self.txtHabitatTop10.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.txtHabitatTop10.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.txtHabitatTop10.setMinimumHeight(120)
        self.txtHabitatTop10.setMaximumHeight(220)
        self.txtHabitatTop10.setPlainText('-')
        details_form.addRow('Query provate', self.lblTriedQueries)
        details_form.addRow('Candidati', self.lblCandidates)
        details_form.addRow('Top 10 punti candidati', self.txtHabitatTop10)
        self.resultDetailsWidget.setVisible(False)
        result_layout.addWidget(self.resultDetailsWidget)

        def _toggle_result_details(checked):
            self.resultDetailsWidget.setVisible(bool(checked))
            self.btnResultDetails.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

        self.btnResultDetails.toggled.connect(_toggle_result_details)
        outer_layout.addWidget(gb_result)

        # ------------------------------------------------------------
        # CAMPI INPUT CORRENTI - spostati in fondo come riepilogo
        # ------------------------------------------------------------
        gb_input = QGroupBox('Campi input correnti')
        input_form = QFormLayout(gb_input)
        self.lblMapping = QLabel('Non configurati')
        self.lblMapping.setWordWrap(True)
        input_form.addRow(self.lblMapping)
        outer_layout.addWidget(gb_input)

        outer_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(outer)
        self.setWidget(scroll)

    def set_search_area(self, area_name, custom_bbox=None, limit=True, auto_expand=True):
        if hasattr(self, "cmbSearchArea"):
            idx = self.cmbSearchArea.findText(area_name or SearchAreaService.DEFAULT_AREA)
            if idx < 0:
                idx = self.cmbSearchArea.findText(SearchAreaService.DEFAULT_AREA)
            if idx >= 0:
                self.cmbSearchArea.setCurrentIndex(idx)
        if hasattr(self, "txtBbox"):
            bbox = SearchAreaService.bbox_for(area_name or SearchAreaService.DEFAULT_AREA, custom_bbox)
            if bbox:
                self.txtBbox.setText(SearchAreaService.bbox_to_text(bbox))
            self.txtBbox.setEnabled((area_name or "") == SearchAreaService.CUSTOM_AREA_NAME)
        if hasattr(self, "chkLimitSearchArea"):
            self.chkLimitSearchArea.setChecked(bool(limit))
        if hasattr(self, "chkAutoExpandSearchArea"):
            self.chkAutoExpandSearchArea.setChecked(bool(auto_expand))

    def update_search_area_bbox(self):
        area = self.cmbSearchArea.currentText() if hasattr(self, "cmbSearchArea") else SearchAreaService.DEFAULT_AREA
        if area == SearchAreaService.CUSTOM_AREA_NAME:
            self.txtBbox.setEnabled(True)
            return
        bbox = SearchAreaService.bbox_for(area)
        if bbox:
            self.txtBbox.setText(SearchAreaService.bbox_to_text(bbox))
        self.txtBbox.setEnabled(False)


    def set_status(self, text):
        self.lblStatus.setText(text)

    def set_mapping_summary(self, mapping_model):
        parts = []
        for label, value in [
            ('ID', mapping_model.record_id),
            ('Comune', mapping_model.municipality),
            ('Località', mapping_model.locality),
            ('Specie', mapping_model.scientific_name),
            ('Substrato', mapping_model.substrate),
            ('Roccia', mapping_model.rock_type),
            ('Albero', mapping_model.tree_type),
            ('Quota', mapping_model.elevation),
            ('Note', mapping_model.notes),
        ]:
            if value:
                parts.append(f'{label}: {value}')
        self.lblMapping.setText('\n'.join(parts) if parts else 'Non configurati')

    def set_found_place(self, text):
        self.lblFoundPlace.setText(text or '-')

    def set_match_type(self, text):
        self.lblMatchType.setText(text or '-')

    def set_tried_queries(self, items):
        if not items:
            self.lblTriedQueries.setText('-')
            return
        lines = []
        for ref_type, query in items[:6]:
            lines.append(f"[{ref_type}] {query}")
        self.lblTriedQueries.setText("\n".join(lines))

    def set_candidates(self, items):
        if not items:
            self.lblCandidates.setText('-')
            return
        self.lblCandidates.setText("\n".join(items[:3]))

    def set_group_lito_info(self, text):
        self.lblGroupLitoInfo.setText(text or '-')


    def set_habitat_suitability(self, text):
        self.lblHabitatSuitability.setText(text or '-')

    def set_habitat_top10(self, text):
        self.txtHabitatTop10.setPlainText(text or '-')


    def set_italic_profile(self, profile):
        if not profile:
            self.lblItalicTaxon.setText('-')
            self.lblItalicSubstrata.setText('-')
            self.lblItalicRock.setText('-')
            self.lblItalicTree.setText('-')
            self.lblItalicEcology.setPlainText('-')
            self.lblItalicUrl.setText('-')
            return
        self.lblItalicTaxon.setText(profile.get('scientific_name') or '-')
        self.lblItalicSubstrata.setText(', '.join(profile.get('substrata', []) or []) or '-')
        self.lblItalicRock.setText(profile.get('rock_type') or '-')
        self.lblItalicTree.setText(profile.get('tree_type') or '-')
        ecology_text = profile.get('ecology_traits') or profile.get('notes') or '-'
        diagnostic_lines = []
        diagnostic_lines.append('Input: ' + str(profile.get('original_name') or profile.get('queried_name') or '-'))
        diagnostic_lines.append('Normalizzato: ' + str(profile.get('normalized_name') or '-'))
        if profile.get('matched_name') or profile.get('accepted_name'):
            diagnostic_lines.append('Matched: ' + str(profile.get('matched_name') or '-'))
            diagnostic_lines.append('Accepted: ' + str(profile.get('accepted_name') or '-'))
            diagnostic_lines.append('Status: ' + str(profile.get('nomenclature_status') or '-'))
            diagnostic_lines.append('Taxon ID: ' + str(profile.get('taxon_id') or '-'))
        if profile.get('diagnostic'):
            diagnostic_lines.append('Diagnostica: ' + str(profile.get('diagnostic')))
        diag = profile.get('diagnostic_info') or {}
        if diag:
            ma = diag.get('match_attempts') or []
            ta = diag.get('taxonpage_attempts') or []
            diagnostic_lines.append('Match attempts: ' + str(len(ma)))
            for a in ma[:3]:
                diagnostic_lines.append(' - ' + ('OK' if a.get('ok') else 'NO') + ' ' + str(a.get('url'))[:120])
                if a.get('error'):
                    diagnostic_lines.append('   err: ' + str(a.get('error'))[:160])
            diagnostic_lines.append('Taxonpage attempts: ' + str(len(ta)))
            for a in ta[:5]:
                diagnostic_lines.append(' - ' + ('OK' if a.get('ok') else 'NO') + ' ' + str(a.get('method')) + ' ' + str(a.get('url'))[:120])
                if a.get('found_link'):
                    diagnostic_lines.append('   link: ' + str(a.get('found_link'))[:160])
                if a.get('error'):
                    diagnostic_lines.append('   err: ' + str(a.get('error'))[:160])
        if diagnostic_lines:
            ecology_text = ecology_text + "\n\n" + "\n".join(diagnostic_lines)
        self.lblItalicEcology.setPlainText(ecology_text)
        self.lblItalicUrl.setText(profile.get('taxon_url') or '-')


    def populate_accessibility_layer_list(self, layer_items):
        """Popola la lista multi-layer accessibilità.

        layer_items può contenere stringhe o tuple (label, checked).
        Include anche layer non vettoriali classici, per esempio Vector Tile MapTiler.
        """
        if not hasattr(self, "lstAccessibilityLayers") or self.lstAccessibilityLayers is None or sip.isdeleted(self.lstAccessibilityLayers):
            return

        previous_checked = set()
        for i in range(self.lstAccessibilityLayers.count()):
            item = self.lstAccessibilityLayers.item(i)
            if item and item.checkState() == Qt.Checked:
                previous_checked.add(item.text())

        self.lstAccessibilityLayers.blockSignals(True)
        self.lstAccessibilityLayers.clear()
        for entry in layer_items or []:
            if isinstance(entry, (list, tuple)):
                label = str(entry[0])
                default_checked = bool(entry[1]) if len(entry) > 1 else False
            else:
                label = str(entry)
                default_checked = False
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if (label in previous_checked or default_checked) else Qt.Unchecked)
            self.lstAccessibilityLayers.addItem(item)
        self.lstAccessibilityLayers.blockSignals(False)


    def populate_dem_layer_list(self, layer_names):
        if not hasattr(self, "lstDemLayers") or self.lstDemLayers is None or sip.isdeleted(self.lstDemLayers):
            return
        checked = []
        for i in range(self.lstDemLayers.count()):
            item = self.lstDemLayers.item(i)
            if item and item.checkState() == Qt.Checked:
                checked.append(item.text())
        ordered = [n for n in checked if n in layer_names]
        ordered += [n for n in layer_names if n not in ordered]
        self.lstDemLayers.blockSignals(True)
        self.lstDemLayers.clear()
        for name in ordered:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            item.setCheckState(Qt.Checked if name in checked else Qt.Unchecked)
            self.lstDemLayers.addItem(item)
        self.lstDemLayers.blockSignals(False)

    def populate_raster_combo(self, combo, layer_names):
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem('')
        combo.addItems(layer_names)
        idx = combo.findText(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def populate_layer_combos(self, layer_names):
        combos = [self.cmbGeologyLayer, self.cmbSoilLayer, self.cmbTreesLayer, self.cmbTrailLayer, self.cmbVegetationBeltLayer]
        for combo in combos:
            if combo is None or sip.isdeleted(combo):
                continue
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem('')
            combo.addItems(layer_names)
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)


    def populate_field_combo(self, combo, field_names):
        if combo is None or sip.isdeleted(combo):
            return
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem('')
        combo.addItems(field_names)
        idx = combo.findText(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)
