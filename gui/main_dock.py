from pathlib import Path

from qgis.PyQt.QtCore import QSize, Qt, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt import sip
from ..services.search_area_service import SearchAreaService
from ..models.geocoding_config import DEFAULT_PHOTON_ENDPOINT
from .collapsible_section import CollapsibleSection
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
    QSizePolicy,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class MainDock(QDockWidget):
    def capture_session_state(self):
        """Retain controls in process memory only, including the configured Photon endpoint."""
        state = {}
        for name, widget in vars(self).items():
            if isinstance(widget, QLineEdit) and name != 'txtSuitabilityGridStep':
                state[name] = ('text', widget.text())
            elif isinstance(widget, QComboBox):
                if name in ('cmbRecordLayer', 'cmbMunicipalityBoundaryLayer'):
                    state[name] = ('source', widget.currentData())
                else:
                    state[name] = ('combo', widget.currentText())
            elif isinstance(widget, QCheckBox):
                state[name] = ('checked', widget.isChecked())
            elif isinstance(widget, QListWidget):
                state[name] = ('items', [(widget.item(i).text(), widget.item(i).checkState())
                                         for i in range(widget.count())])
        return state

    def restore_session_state(self, state):
        for name, (kind, value) in state.items():
            widget = getattr(self, name, None)
            if widget is None:
                continue
            if kind == 'text':
                widget.setText(value)
            elif kind in ('combo', 'source'):
                if name == 'cmbSuitabilityView' and value == 'Heatmap':
                    value = 'Suitability Surface'
                index = widget.findData(value) if kind == 'source' else widget.findText(value)
                if index >= 0:
                    widget.setCurrentIndex(index)
            elif kind == 'checked':
                widget.setChecked(value)
            elif kind == 'items':
                remaining = [widget.takeItem(0) for _ in range(widget.count())]
                for text, checked in value:
                    item = next((item for item in remaining if item.text() == text), None)
                    if item is not None:
                        remaining.remove(item)
                        item.setCheckState(checked)
                        widget.addItem(item)
                for item in remaining:
                    widget.addItem(item)

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
        self.configurationSection = CollapsibleSection('Configurazione layer e campi tabella record', full_width=True)
        gb_config = self.configurationSection
        config_form = QFormLayout()
        gb_config.content_layout.addLayout(config_form)
        config_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.txtGeocoderUrl = QLineEdit(str(QSettings().value(
            'geolichen/photon_endpoint', DEFAULT_PHOTON_ENDPOINT)))
        self.txtGeocoderUrl.setPlaceholderText(DEFAULT_PHOTON_ENDPOINT)
        self.txtGeocoderUrl.setToolTip('URL dell’API Photon basata su OpenStreetMap. Nessuna chiave MapTiler richiesta.')
        self.lblGeocoderSource = QLabel('Località: Photon / OpenStreetMap · © OpenStreetMap contributors')
        self.lblGeocoderSource.setWordWrap(True)
        self.lblGeocoderSource.setToolTip('Servizio pubblico dimostrativo per uso moderato; per uso intensivo configura una tua istanza Photon.')

        self.cmbSearchArea = QComboBox()
        self.cmbSearchArea.addItems(SearchAreaService.names())
        self.cmbSearchArea.setCurrentText(SearchAreaService.DEFAULT_AREA)

        self.chkLimitSearchArea = QCheckBox('Limita la ricerca all’area selezionata')
        self.chkLimitSearchArea.setToolTip('Limita le località cercate all’area geografica scelta.')
        self.chkLimitSearchArea.setChecked(True)
        self.chkAutoExpandSearchArea = QCheckBox('Espandi automaticamente se nessun\nrisultato plausibile')
        self.chkAutoExpandSearchArea.setToolTip('Allarga la ricerca se non trova località plausibili nell’area scelta.')
        self.chkAutoExpandSearchArea.setChecked(True)

        self.txtBbox = QLineEdit(
            SearchAreaService.bbox_to_text(
                SearchAreaService.bbox_for(SearchAreaService.DEFAULT_AREA)
            )
        )
        self.txtBbox.setPlaceholderText('xmin,ymin,xmax,ymax')
        self.txtBbox.setEnabled(False)

        self.btnConfigureFields = QPushButton('⚙  Configura campi input')
        self.btnConfigureFields.setToolTip('Associa le colonne della tabella a località, specie e altri dati del record.')

        config_form.addRow(self.lblGeocoderSource)
        config_form.addRow('Servizio Photon', self.txtGeocoderUrl)
        config_form.addRow('Area di ricerca', self.cmbSearchArea)
        config_form.addRow(self.chkLimitSearchArea)
        config_form.addRow(self.chkAutoExpandSearchArea)
        config_form.addRow('BBox personalizzata', self.txtBbox)
        self.cmbMunicipalityBoundaryLayer = QComboBox()
        self.cmbMunicipalityBoundaryLayer.addItem('Nessun layer dei confini comunali', '')
        self.cmbMunicipalityBoundaryField = QComboBox()
        self.cmbMunicipalityBoundaryLayer.setToolTip('Layer poligonale dei confini comunali caricato nel progetto; facoltativo.')
        self.cmbMunicipalityBoundaryField.setToolTip('Colonna con il nome del comune. Serve a verificare i candidati, mantenendo il buffer circolare.')
        self.chkUseLocalityArchive = QCheckBox('Usa l’archivio delle località\nconfermate e salva le nuove scelte')
        self.chkUseLocalityArchive.setChecked(QSettings().value('geolichen/use_locality_archive', True, type=bool))
        self.chkUseLocalityArchive.setToolTip('Conserva nel profilo QGIS i punti geografici che confermi, disponibili anche dopo la chiusura e senza rete.')
        self.btnLocalityArchive = QPushButton('Archivio località confermate…')
        self.btnLocalityArchive.setToolTip('Consulta o rimuovi le località memorizzate; ogni record conserva la propria analisi ecologica.')
        config_form.addRow('Confini comunali (facoltativo)', self.cmbMunicipalityBoundaryLayer)
        config_form.addRow('Campo nome comune', self.cmbMunicipalityBoundaryField)
        config_form.addRow(self.chkUseLocalityArchive)
        config_form.addRow(self.btnLocalityArchive)
        config_form.addRow(self.btnConfigureFields)
        outer_layout.addWidget(gb_config)

        # ------------------------------------------------------------
        # GEOREFERENZIAZIONE - controller operativo principale
        # ------------------------------------------------------------
        gb_geo = QGroupBox('Georeferenziazione Località')
        gb_geo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.georeferencingGroup = gb_geo
        geo_layout = QVBoxLayout(gb_geo)
        geo_layout.setSpacing(8)

        source_form = QFormLayout()
        self.cmbRecordLayer = QComboBox()
        self.cmbRecordLayer.setToolTip('Tabella da cui leggere la riga selezionata e in cui salvare i risultati.')
        source_form.addRow('Tabella record', self.cmbRecordLayer)
        geo_layout.addLayout(source_form)

        self.btnAnalyze = QPushButton('Ricerca della località')
        self.btnAnalyze.setToolTip('Cerca la località della riga selezionata e definisce l’area di ricerca.')
        self.btnAnalyze.setFixedHeight(52)
        self.btnAnalyze.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btnUseLocalityCentroid = QPushButton()
        self.btnUseLocalityCentroid.setIcon(QIcon(str(Path(__file__).parent / 'icons' / 'locality_centroid.png')))
        self.btnUseLocalityCentroid.setIconSize(QSize(40, 40))
        self.btnUseLocalityCentroid.setFixedHeight(52)
        self.btnUseLocalityCentroid.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btnUseLocalityCentroid.setAccessibleName('Sono a posto così — centroide della località')
        self.btnUseLocalityCentroid.setToolTip(
            'Sono a posto così: concludi con il centroide del buffer e la quota DEM, senza ranking ecologico')
        self.localityActionsLayout = QHBoxLayout()
        self.localityActionsLayout.setSpacing(8)
        self.localityActionsLayout.addWidget(self.btnAnalyze, 4)
        self.localityActionsLayout.addWidget(self.btnUseLocalityCentroid, 1)
        geo_layout.addLayout(self.localityActionsLayout)

        self.lblBufferGridInfo = QLabel('Buffer: nessuna area definita • Passo griglia: —')
        self.lblBufferGridInfo.setWordWrap(True)
        self.lblBufferGridInfo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lblBufferGridInfo.setToolTip(
            'Superficie dell’area di ricerca corrente e passo base della griglia. '
            'Il raffinamento locale può usare passi più piccoli. Per le aree automatiche '
            'il raggio di riferimento è metà del lato maggiore del rettangolo che le contiene.'
        )
        geo_layout.addWidget(self.lblBufferGridInfo)

        # Strumenti mantenuti per compatibilità con il controller, ma non
        # più mostrati nell'interfaccia principale.
        self.btnItalic = QPushButton('Leggi profilo ITALIC')
        self.btnItalic.setToolTip('Scarica il profilo ecologico ITALIC della specie del record corrente.')
        self.btnItalic.setVisible(False)
        self.btnRedefineBuffer = QPushButton('Ridefinisci buffer')
        self.btnRedefineBuffer.setToolTip('Avvia la ridefinizione del buffer dalla mappa.')
        self.btnRedefineBuffer.setVisible(False)
        self.txtHeatmapRadius = QLineEdit('18')
        self.txtHeatmapRadius.setVisible(False)
        self.txtHeatmapOpacity = QLineEdit('60')
        self.txtHeatmapOpacity.setVisible(False)

        self.manualGeometrySection = CollapsibleSection('Punto e linea manuali')
        manual_layout = self.manualGeometrySection.content_layout
        geo_layout.addWidget(self.manualGeometrySection)

        # Punto manuale
        point_box = QGroupBox('Punto manuale')
        point_form = QFormLayout(point_box)
        self.txtManualBuffer = QLineEdit('250')
        self.txtManualBuffer.setPlaceholderText('Raggio in metri')
        self.btnManualPoint = QPushButton('Punto manuale + buffer')
        self.btnManualPoint.setToolTip('Scegli un centro sulla mappa e crea un buffer con il raggio indicato.')
        point_form.addRow('Buffer (m)', self.txtManualBuffer)
        point_form.addRow(self.btnManualPoint)
        manual_layout.addWidget(point_box)

        # Linea manuale
        line_box = QGroupBox('Linea manuale')
        line_form = QFormLayout(line_box)
        self.txtManualLineOffset = QLineEdit('500')
        self.txtManualLineOffset.setPlaceholderText('Offset laterale in metri')
        self.btnManualLine = QPushButton('Linea manuale + offset')
        self.btnManualLine.setToolTip('Disegna una linea sulla mappa e crea un’area di ricerca con l’offset indicato.')
        line_form.addRow('Offset (m)', self.txtManualLineOffset)
        line_form.addRow(self.btnManualLine)
        manual_layout.addWidget(line_box)

        model_form = QFormLayout()
        self.txtSuitabilityGridStep = QLineEdit('10', gb_geo)
        self.txtSuitabilityGridStep.setVisible(False)
        self.txtSuitabilityGridStep.setPlaceholderText('Passo griglia in metri')
        self.cmbSuitabilityView = QComboBox()
        self.cmbSuitabilityView.addItems(['Punti candidati', 'Suitability Surface', 'Entrambi'])
        self.cmbSuitabilityView.setToolTip(
            'Suitability Surface visualizza una heatmap dell’idoneità ecologica nell’area di ricerca.')
        self.cmbSuitabilityView.setItemData(
            1, 'Visualizza una heatmap dell’idoneità ecologica nell’area di ricerca.', Qt.ItemDataRole.ToolTipRole)
        self.cmbSuitabilityView.setCurrentText('Punti candidati')
        model_form.addRow('Visualizzazione', self.cmbSuitabilityView)
        geo_layout.addLayout(model_form)
        self.lblOsmTrailsInfo = QLabel('')
        self.lblOsmTrailsInfo.setWordWrap(True)
        self.lblOsmTrailsInfo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lblOsmTrailsInfo.setVisible(False)
        geo_layout.addWidget(self.lblOsmTrailsInfo)

        outer_layout.addWidget(gb_geo)

        self.ecologicalAnalysisGroup = QGroupBox('Analisi ecologica')
        self.ecologicalAnalysisGroup.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        ecological_layout = QVBoxLayout(self.ecologicalAnalysisGroup)
        ecological_layout.setSpacing(8)
        self.btnHabitatSuitability = QPushButton('Analisi ecologica\nstep by step')
        self.btnHabitatSuitability.setAccessibleName('Analisi ecologica step by step')
        self.btnHabitatSuitability.setToolTip(
            'Calcola la griglia e scegli un candidato sulla mappa prima di confermare i dati.')
        self.btnAutomaticPoint = QPushButton('Analisi ecologica\nautomatica')
        self.btnAutomaticPoint.setAccessibleName('Analisi ecologica automatica')
        self.btnAutomaticPoint.setToolTip(
            'Ricerca la località, calcola la griglia e salva il punto di rank 1 nella riga selezionata.')
        self.ecologicalActionsLayout = QHBoxLayout()
        self.ecologicalActionsLayout.setSpacing(8)
        for button in (self.btnHabitatSuitability, self.btnAutomaticPoint):
            button.setMinimumHeight(40)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.ecologicalActionsLayout.addWidget(button, 1)
        ecological_layout.addLayout(self.ecologicalActionsLayout)

        self.lblCandidatePreview = QLabel('')
        self.lblCandidatePreview.setWordWrap(True)
        self.lblCandidatePreview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lblCandidatePreview.setToolTip(
            'Coordinate del candidato in WGS84 (EPSG:4326). L’incertezza GeoLichen '
            'è il raggio del modello R55–S65, distinto dall’incertezza della località.')
        self.lblCandidatePreview.setVisible(False)
        ecological_layout.addWidget(self.lblCandidatePreview)

        self.btnReuseConfirmedPoint = QPushButton('Copia su altri record')
        self.btnReuseConfirmedPoint.setToolTip('Scegli un punto già confermato e copiane i dati su una o più righe.')
        self.btnReuseConfirmedPoint.setMinimumHeight(32)
        ecological_layout.addWidget(self.btnReuseConfirmedPoint)
        outer_layout.addWidget(self.ecologicalAnalysisGroup)

        self.lblOperationalStatus = QLabel('Pronto')
        self.lblOperationalStatus.setWordWrap(True)
        outer_layout.addWidget(self.lblOperationalStatus)

        # ------------------------------------------------------------
        # LAYER AMBIENTALI - invariati
        # ------------------------------------------------------------
        # Keep every existing widget and controller binding, grouped by layer.
        layers_layout = gb_config.content_layout
        self.cmbGeologyLayer = QComboBox()
        self.cmbGeologyField = QComboBox()
        self.btnCreateGroupLito = QPushButton('Crea / aggiorna GRUPPO_LITO')
        self.btnCreateGroupLito.setToolTip('Crea o aggiorna il campo GRUPPO_LITO nel layer geologico selezionato.')
        self.lblGroupLitoInfo = QLabel('-')
        self.lblGroupLitoInfo.setWordWrap(True)
        self.cmbSoilLayer = QComboBox()
        self.cmbSoilField = QComboBox()
        self.cmbTreesLayer = QComboBox()
        self.cmbTreesField = QComboBox()
        self.cmbTrailLayer = QComboBox()
        self.chkUseOsmTrails = QCheckBox('Usa dati sentieristici OpenStreetMap')
        self.chkUseOsmTrails.setToolTip('Scarica i sentieri e le vie di accesso OSM, ritaglia i tratti nel buffer corrente e li usa per calcolare le distanze. Non certifica la percorribilità.')
        self.chkUseOsmTrails.setChecked(True)
        self.chkShowOsmTrails = QCheckBox('Mostra layer OSM scaricato')
        self.chkShowOsmTrails.setToolTip('Mostra sulla mappa i dati OpenStreetMap scaricati per l’area di ricerca.')
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
        self.lstDemLayers.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        def layer_box(title, rows, hint=None):
            box = QGroupBox(title)
            form = QFormLayout(box)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for label, widget in rows:
                if label:
                    form.addRow(label, widget)
                else:
                    form.addRow(widget)
            if hint:
                text = QLabel(hint)
                text.setWordWrap(True)
                form.addRow(text)
            layers_layout.addWidget(box)
            return box

        self.geologyBox = layer_box('Geologia / Litologia', [
            ('Layer', self.cmbGeologyLayer), ('Campo litologico', self.cmbGeologyField),
            ('', self.btnCreateGroupLito), ('Esito', self.lblGroupLitoInfo),
        ], 'Riconoscimento automatico delle descrizioni italiane e inglesi durante l’analisi. '
           'La creazione di GRUPPO_LITO è facoltativa.')
        self.soilBox = layer_box('Suolo / Acidità', [
            ('Layer', self.cmbSoilLayer), ('Campo pH / suolo', self.cmbSoilField),
        ], 'Lettura automatica del pH numerico o delle classi acido, neutro e basico.')
        self.treesBox = layer_box('Alberi / Boschi', [
            ('Layer', self.cmbTreesLayer), ('Campo alberi', self.cmbTreesField),
        ])
        self.accessibilityBox = layer_box('Accessibilità', [
            ('Layer', self.lstAccessibilityLayers), ('', self.chkUseOsmTrails),
            ('', self.chkShowOsmTrails),
        ])
        self.vegetationBox = layer_box('Fasce vegetazionali', [
            ('Layer', self.cmbVegetationBeltLayer), ('Campo fascia', self.cmbVegetationBeltField),
        ])
        self.demBox = layer_box('Modelli digitali del terreno (DEM)', [
            ('Priorità dall’alto', self.lstDemLayers),
        ])

        # ------------------------------------------------------------
        # PROFILO ITALIC - invariato, letto dalla pipeline
        # ------------------------------------------------------------
        self.italicSection = CollapsibleSection('Profilo ITALIC')
        gb_italic = self.italicSection
        italic_form = QFormLayout()
        gb_italic.content_layout.addLayout(italic_form)
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
        self.lblItalicEcology.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.lblItalicEcology.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        self.btnResultDetails.setToolTip('Mostra o nasconde query, località trovate e riepilogo dei candidati.')
        self.btnResultDetails.setCheckable(True)
        self.btnResultDetails.setChecked(False)
        self.btnResultDetails.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btnResultDetails.setArrowType(Qt.ArrowType.RightArrow)
        result_layout.addWidget(self.btnResultDetails)

        self.resultDetailsWidget = QWidget()
        details_form = QFormLayout(self.resultDetailsWidget)
        self.lblTriedQueries = QLabel('-')
        self.lblTriedQueries.setWordWrap(True)
        self.lblCandidates = QLabel('-')
        self.lblCandidates.setWordWrap(True)
        self.txtHabitatTop10 = QTextEdit()
        self.txtHabitatTop10.setReadOnly(True)
        self.txtHabitatTop10.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.txtHabitatTop10.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.txtHabitatTop10.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
            self.btnResultDetails.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

        self.btnResultDetails.toggled.connect(_toggle_result_details)
        self.resultGroup = gb_result
        gb_result.setVisible(False)
        outer_layout.addWidget(gb_result)

        # ------------------------------------------------------------
        # CAMPI INPUT CORRENTI - spostati in fondo come riepilogo
        # ------------------------------------------------------------
        gb_input = QGroupBox('Campi input correnti')
        input_form = QFormLayout(gb_input)
        self.lblMapping = QLabel('Non configurati')
        self.lblMapping.setWordWrap(True)
        input_form.addRow(self.lblMapping)
        self.inputSummaryGroup = gb_input
        gb_input.setVisible(False)
        outer_layout.addWidget(gb_input)

        outer_layout.addStretch(1)

        # Layer names must not become the minimum width of the dock. The popup
        # still exposes their complete text; forms can put fields below labels.
        for combo in outer.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            hint = combo.toolTip()
            combo.currentTextChanged.connect(
                lambda _text, widget=combo, help_text=hint: widget.setToolTip(
                    '\n'.join(part for part in (help_text, widget.currentText()) if part)))
            combo.setToolTip('\n'.join(part for part in (hint, combo.currentText()) if part))
        for form in outer.findChildren(QFormLayout):
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for label in outer.findChildren(QLabel):
            if label.wordWrap():
                policy = label.sizePolicy()
                policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
                label.setSizePolicy(policy)

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
        self.lblOperationalStatus.setText(text)

    def set_candidate_preview(self, text=''):
        self.lblCandidatePreview.setText(text)
        self.lblCandidatePreview.setVisible(bool(text))

    def set_osm_trails_info(self, text):
        self.lblOsmTrailsInfo.setText(text or '')
        self.lblOsmTrailsInfo.setToolTip(text or '')
        self.lblOsmTrailsInfo.setVisible(bool(text))

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
        Mostra i layer lineari utilizzabili dal motore delle distanze.
        """
        if not hasattr(self, "lstAccessibilityLayers") or self.lstAccessibilityLayers is None or sip.isdeleted(self.lstAccessibilityLayers):
            return

        previous_checked = set()
        for i in range(self.lstAccessibilityLayers.count()):
            item = self.lstAccessibilityLayers.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
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
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if (label in previous_checked or default_checked) else Qt.CheckState.Unchecked)
            self.lstAccessibilityLayers.addItem(item)
        self.lstAccessibilityLayers.blockSignals(False)


    def populate_dem_layer_list(self, layer_names):
        if not hasattr(self, "lstDemLayers") or self.lstDemLayers is None or sip.isdeleted(self.lstDemLayers):
            return
        checked = []
        for i in range(self.lstDemLayers.count()):
            item = self.lstDemLayers.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                checked.append(item.text())
        ordered = [n for n in checked if n in layer_names]
        ordered += [n for n in layer_names if n not in ordered]
        self.lstDemLayers.blockSignals(True)
        self.lstDemLayers.clear()
        for name in ordered:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked)
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
