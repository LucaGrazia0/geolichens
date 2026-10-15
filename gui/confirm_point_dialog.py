import json
import os
import math

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QPushButton,
    QTextBrowser,
    QFileDialog,
    QHBoxLayout,
    QWidget,
    QScrollArea,
)


class ConfirmPointDialog(QDialog):
    """Dialog per confermare e scrivere X/Y/Quota DEM/Incertezza nel record."""

    def __init__(
        self,
        fields,
        x_value,
        y_value,
        dem_value=None,
        defaults=None,
        parent=None,
        candidate_rank=None,
        candidate_score=None,
        snap_distance_m=None,
        uncertainty_info=None,
        locality_context=None,
        ecological_point_wgs84=None,
        explainability_report=None,
        iface=None,
        candidate_dem_value=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Usa questo candidato")
        self.fields = list(fields or [])
        self.defaults = defaults or {}
        self.uncertainty_info = uncertainty_info or {}
        self.locality_context = locality_context
        self.ecological_point_wgs84 = ecological_point_wgs84
        self.explainability_report = explainability_report or {}
        self.iface = iface
        self.candidate_rank = candidate_rank
        self.candidate_score = candidate_score
        self.candidate_dem_value = candidate_dem_value if candidate_dem_value is not None else dem_value

        self.resize(820, 760)
        layout = QVBoxLayout(self)

        # Tutto il contenuto principale vive in un'area scorrevole.
        # Il dialogo può diventare più alto dello schermo (soprattutto su macOS),
        # quindi senza QScrollArea i campi e i pulsanti finali risultavano coperti.
        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scrollContent = QWidget(self.scrollArea)
        contentLayout = QVBoxLayout(self.scrollContent)
        contentLayout.setContentsMargins(6, 6, 6, 6)
        self.scrollArea.setWidget(self.scrollContent)
        layout.addWidget(self.scrollArea, 1)

        rank_text = "-" if candidate_rank is None else str(candidate_rank)
        try:
            score_text = f"{float(candidate_score):.2f}"
        except Exception:
            score_text = "-"
        try:
            snap_text = f"{float(snap_distance_m):.1f} m"
        except Exception:
            snap_text = "-"
        try:
            unc_text = f"{float(self.defaults.get('uncertainty', 0) or 0):.1f} m"
        except Exception:
            unc_text = "-"

        model_radius = float(self.uncertainty_info.get("model_radius_m") or 0.0)
        model_confidence = (
            self.uncertainty_info.get("model_confidence")
            or self.uncertainty_info.get("confidence")
            or "-"
        )
        locality_type = getattr(self.locality_context, "locality_type", "unknown") or "unknown"
        geometry_type = getattr(self.locality_context, "geometry_type", "unknown") or "unknown"
        class_conf = getattr(self.locality_context, "classification_confidence", 0.0) or 0.0
        corrected = self.uncertainty_info.get("corrected_center")
        corrected_lon = self.uncertainty_info.get("corrected_center_lon")
        corrected_lat = self.uncertainty_info.get("corrected_center_lat")
        if corrected_lon is None and corrected is not None:
            try:
                corrected_lon = float(corrected.x())
                corrected_lat = float(corrected.y())
            except Exception:
                corrected_lon = corrected_lat = None
        if corrected_lon is None:
            corrected_text = "non calcolabile"
        else:
            corrected_text = f"{float(corrected_lat):.6f}, {float(corrected_lon):.6f}"

        eco_text = "-"
        if self.ecological_point_wgs84 is not None:
            try:
                eco_text = (
                    f"{float(self.ecological_point_wgs84.y()):.6f}, "
                    f"{float(self.ecological_point_wgs84.x()):.6f}"
                )
            except Exception:
                pass

        locality_label = self._locality_type_label(locality_type)
        geometry_label = self._geometry_type_label(geometry_type)
        center_method_label = self._center_method_label(
            self.uncertainty_info.get("corrected_center_method")
        )
        model_confidence_label = self._model_confidence_label(model_confidence)
        model_confidence_score = self.uncertainty_info.get("model_confidence_index")
        if model_confidence_score is None:
            model_confidence_score = self.uncertainty_info.get("model_confidence_score")
        try:
            model_confidence_text = f"{float(model_confidence_score):.0f}% ({model_confidence_label})"
        except Exception:
            model_confidence_text = model_confidence_label
        confidence_reasons = self.uncertainty_info.get("model_confidence_reasons") or []
        confidence_reasons_html = ""
        if confidence_reasons:
            confidence_reasons_html = "<br><span style='font-size:12px;'>" + "<br>".join(
                f"• {str(reason)}" for reason in confidence_reasons[:4]
            ) + "</span>"
        ssi_score = self.uncertainty_info.get("solution_stability_index")
        ssi_class = self.uncertainty_info.get("solution_stability_class")
        try:
            ssi_text = f"{float(ssi_score):.0f}% ({self._model_confidence_label(ssi_class)})"
        except Exception:
            ssi_text = "-"
        ssi_reasons = self.uncertainty_info.get("solution_stability_reasons") or []
        ssi_reasons_html = ""
        if ssi_reasons:
            ssi_reasons_html = "<br><span style='font-size:12px;'>" + "<br>".join(
                f"• {str(reason)}" for reason in ssi_reasons[:3]
            ) + "</span>"
        center_distance_text = self._center_distance_text(
            corrected_lon, corrected_lat, self.ecological_point_wgs84
        )
        dwc_complete = bool(self.uncertainty_info.get("gbif_dwc_complete"))
        georeferenced_by = str(self.uncertainty_info.get("georeferencedBy") or "").strip()
        if dwc_complete and georeferenced_by:
            dwc_status = "Completo"
        elif dwc_complete:
            dwc_status = "Dati geografici completi; compilare georeferencedBy prima della pubblicazione"
        else:
            dwc_status = "Incompleto"
        datum_text = str(self.uncertainty_info.get("geodeticDatum") or "EPSG:4326")
        precision_value = self.uncertainty_info.get("coordinatePrecision")
        try:
            precision_text = f"{float(precision_value):.6f}°"
        except Exception:
            precision_text = "-"
        def _unc_component(value):
            try:
                parsed = float(value or 0.0)
                return parsed if parsed > 0 else 0.0
            except Exception:
                return 0.0

        geometry_floor_value = _unc_component(
            self.uncertainty_info.get("geometry_uncertainty_floor_m")
        )
        geometry_floor_reason = str(
            self.uncertainty_info.get("geometry_uncertainty_floor_reason") or ""
        ).strip()
        point_floor_html = ""
        if self.uncertainty_info.get("geometry_uncertainty_calculated"):
            geometry_type_unc = str(
                self.uncertainty_info.get("geometry_uncertainty_geometry_type") or "-"
            )
            geographic_radial_m = _unc_component(
                self.uncertainty_info.get("geographic_radial_m")
            )
            bbox_m = _unc_component(
                self.uncertainty_info.get("geometry_uncertainty_bbox_m")
            )
            bbox_used = bool(
                self.uncertainty_info.get("geometry_uncertainty_bbox_used_as_geometry")
                or self.uncertainty_info.get("gbif_bbox_geometry_applied")
            )
            gbif_calculable = bool(self.uncertainty_info.get("gbif_calculable"))
            provider_m = _unc_component(
                self.uncertainty_info.get("geometry_uncertainty_provider_accuracy_m")
            )
            explicit_m = _unc_component(
                self.uncertainty_info.get("geometry_uncertainty_explicit_source_m")
            )
            coordinate_m = _unc_component(self.uncertainty_info.get("coordinate_error_m"))
            measurement_m = _unc_component(self.uncertainty_info.get("measurement_error_m"))
            datum_m = _unc_component(self.uncertainty_info.get("datum_error_m"))
            source_error_m = _unc_component(self.uncertainty_info.get("source_error_m"))
            grid_error_m = _unc_component(self.uncertainty_info.get("grid_error_m"))
            operational_extent_used = bool(self.uncertainty_info.get("gbif_operational_extent_used"))
            operational_extent_source = str(
                self.uncertainty_info.get("gbif_operational_extent_source") or ""
            )
            final_unc_m = _unc_component(
                self.uncertainty_info.get("coordinate_uncertainty_m")
                or self.uncertainty_info.get("gbif_uncertainty_m")
                or self.uncertainty_info.get("uncertainty_m")
            )
            dominant_label = str(
                self.uncertainty_info.get("geometry_uncertainty_dominant_label") or "-"
            )
            dominant_m = _unc_component(
                self.uncertainty_info.get("geometry_uncertainty_dominant_m")
            )

            def _component_line(label, value, note=""):
                marker = "☑" if value > 0 else "☐"
                value_text = f"{value:.1f} m" if value > 0 else "non disponibile"
                suffix = f" ({note})" if note else ""
                return f"<br>{marker} {label}: {value_text}{suffix}"

            if bbox_used:
                bbox_note = "usata come geometria documentale; non sommata come errore"
            elif bbox_m > 0:
                bbox_note = "disponibile ma non applicabile alla geometria corrente"
            else:
                bbox_note = "non disponibile"

            source_origin = dominant_label if source_error_m > 0 else "Nessun errore di sorgente aggiuntivo"
            geometry_note = {
                "POINT": ("area di ricerca della località usata come estensione" if operational_extent_used else "estensione della geometria puntuale"),
                "LINE": "distanza massima dalla geometria lineare",
                "POLYGON": "distanza massima dal bordo del poligono",
                "ADMIN": "distanza massima dal confine amministrativo",
            }.get(geometry_type_unc.upper(), "distanza massima dalla geometria documentale")

            point_floor_html = (
                "<br><br><b>CALCOLO DELL’INCERTEZZA</b>"
                "<br><span style='font-size:12px;'>"
                f"<b>Metodo:</b> Point-Radius dinamico ({geometry_type_unc})"
                + _component_line(
                    "Estensione spaziale usata",
                    geographic_radial_m,
                    geometry_note,
                )
                + _component_line("Bounding box del geocoder", bbox_m, bbox_note)
                + _component_line("Accuratezza dichiarata dalla fonte", provider_m)
                + _component_line("Errore della fonte fornito", explicit_m)
                + _component_line("Stima semantica facoltativa", geometry_floor_value,
                                  "suggerita ma NON applicata automaticamente" if geometry_floor_value > 0 else "non prevista")
                + _component_line("Precisione delle coordinate", coordinate_m)
                + _component_line("Errore di misurazione", measurement_m)
                + _component_line("Errore del datum", datum_m)
                + (
                    f"<br>ℹ Risoluzione del candidato: {grid_error_m:.1f} m "
                    "(passo griglia / √2; NON sommata all’incertezza GBIF)"
                    if grid_error_m > 0
                    else "<br>ℹ Risoluzione del candidato: non disponibile"
                )
                + f"<br><b>Componente di sorgente selezionata:</b> {source_origin}"
                + (f" ({dominant_m:.1f} m)" if dominant_m > 0 else "")
                + f"<br><b>Errore di sorgente combinato in quadratura:</b> {source_error_m:.1f} m"
                + (
                    f"<br><b>Valore finale coordinateUncertaintyInMeters:</b> {final_unc_m:.1f} m"
                    if gbif_calculable and final_unc_m > 0
                    else "<br><b>Valore finale coordinateUncertaintyInMeters:</b> non stimabile in modo affidabile"
                )
                + (
                    f"<br><b>Raggio del buffer operativo effettivo:</b> "
                    f"{_unc_component(self.uncertainty_info.get('effective_buffer_radius_m')):.1f} m "
                    "(misurato sulla geometria realmente usata per generare i candidati)."
                    if self.uncertainty_info.get("effective_buffer_radius_m") is not None
                    else ""
                )
                + (
                    "<br><b>Origine del radial:</b> "
                    + (
                        "buffer operativo effettivamente usato per generare i candidati."
                        if operational_extent_source == "candidate_generation_effective_buffer"
                        else "SearchGeometry SLGE usata come fallback."
                    )
                    if operational_extent_used else ""
                )
                + (
                    "<br><b>Revisione necessaria:</b> non è disponibile alcuna estensione spaziale utilizzabile."
                    if not gbif_calculable else ""
                )
                + "</span>"
            )
            if geometry_floor_reason:
                point_floor_html += (
                    f"<br><span style='font-size:11px;'><i>{geometry_floor_reason}</i></span>"
                )


        slge_active = bool(self.uncertainty_info.get("slge_active"))
        slge_feature = self._slge_feature_label(self.uncertainty_info.get("slge_feature_type"))
        slge_expected = self._slge_geometry_label(self.uncertainty_info.get("slge_expected_geometry"))
        slge_rule = self._slge_rule_label(self.uncertainty_info.get("slge_matched_rule"))
        slge_source = str(
            self.uncertainty_info.get("slge_documented_source_label")
            or self.uncertainty_info.get("slge_documented_source")
            or "-"
        )
        slge_method = str(
            self.uncertainty_info.get("slge_documented_method_label")
            or self.uncertainty_info.get("slge_documented_method")
            or "-"
        )
        slge_geom_type = self._slge_geometry_label(
            self.uncertainty_info.get("slge_documented_geometry_type") or geometry_type
        )
        slge_gci_class = str(self.uncertainty_info.get("slge_geometry_confidence_class") or "-").replace("_", " ")
        try:
            slge_confidence = f"{float(self.uncertainty_info.get('slge_geometry_confidence') or 0) * 100.0:.0f}%"
        except Exception:
            slge_confidence = "-"
        try:
            slge_semantic_confidence = f"{float(self.uncertainty_info.get('slge_semantic_confidence') or 0) * 100.0:.0f}%"
        except Exception:
            slge_semantic_confidence = "-"
        slge_review = "Sì" if self.uncertainty_info.get("slge_requires_review") else "No"
        slge_estimated = "Sì" if self.uncertainty_info.get("slge_documented_estimated") else "No"
        slge_available = bool(self.uncertainty_info.get("slge_documented_available", True))
        slge_search_strategy = self._slge_search_strategy_label(
            self.uncertainty_info.get("slge_search_strategy")
        )
        slge_search_source = self._slge_search_source_label(
            self.uncertainty_info.get("slge_search_source")
        )
        slge_filters = self._slge_filters_label(
            self.uncertainty_info.get("slge_search_filters") or []
        )
        effective_radius = self._format_optional_m(
            self.uncertainty_info.get("effective_buffer_radius_m")
        )
        effective_geometry_type = str(
            self.uncertainty_info.get("effective_search_geometry_type") or "Non disponibile"
        )
        effective_vertex_count = self.uncertainty_info.get("effective_search_geometry_vertex_count")
        effective_vertex_text = (
            str(int(effective_vertex_count))
            if effective_vertex_count is not None
            else "Non disponibile"
        )
        effective_area_ha = self.uncertainty_info.get("effective_search_geometry_area_ha")
        effective_area_text = (
            f"{float(effective_area_ha):.2f} ha"
            if effective_area_ha is not None
            else "Non disponibile"
        )
        effective_clipped = bool(
            self.uncertainty_info.get("effective_search_geometry_clipped")
            or self.uncertainty_info.get("slge_search_clipped")
        )
        effective_expanded = bool(
            self.uncertainty_info.get("effective_search_geometry_expanded")
            or self.uncertainty_info.get("slge_search_expanded")
        )
        uncertainty_method_label = self._uncertainty_method_label(
            self.uncertainty_info.get("uncertainty_method")
        )
        admin_diag = dict(self.uncertainty_info.get("slge_administrative_geometry_diagnostics") or {})
        admin_diag_html = self._administrative_geometry_diagnostics_html(admin_diag)
        slge_reasons = self.uncertainty_info.get("slge_geometry_confidence_reasons") or []
        slge_reasons_html = ""
        if slge_reasons:
            slge_reasons_html = "<br><span style='font-size:12px;'>" + "<br>".join(
                f"• {str(reason)}" for reason in slge_reasons[:5]
            ) + "</span>"
        terrain_available = bool(self.uncertainty_info.get("terrain_reconstruction_available"))
        terrain_used = bool(self.uncertainty_info.get("terrain_reconstruction_used"))
        terrain_fallback = bool(self.uncertainty_info.get("terrain_fallback_used"))
        terrain_review = bool(self.uncertainty_info.get("terrain_manual_review_required"))
        terrain_decision = str(self.uncertainty_info.get("terrain_decision") or "-").replace("_", " ")
        try:
            terrain_area = f"{float(self.uncertainty_info.get('terrain_polygon_area_km2')):.3f} km²"
        except Exception:
            terrain_area = "-"
        try:
            terrain_summit = f"{float(self.uncertainty_info.get('terrain_summit_elevation_m')):.1f} m"
        except Exception:
            terrain_summit = "-"
        try:
            terrain_validation = f"{float(self.uncertainty_info.get('terrain_validation_confidence')) * 100.0:.0f}%"
        except Exception:
            terrain_validation = "-"
        try:
            terrain_resolution = f"{float(self.uncertainty_info.get('terrain_dem_resolution_m')):.1f} m"
        except Exception:
            terrain_resolution = "-"
        terrain_status = "UTILIZZATA" if terrain_used else ("FALLBACK SEMANTICO" if terrain_fallback else "NON ESEGUITA")
        terrain_html = ""
        if terrain_available or terrain_used:
            terrain_html = (
                "<br><br><b style='font-size:15px;'>RICOSTRUZIONE MORFOLOGICA DEL TERRENO</b><br>"
                f"<b>Esito:</b> {terrain_status}<br>"
                f"<b>Decisione:</b> {terrain_decision}<br>"
                f"<b>Cima individuata:</b> {terrain_summit}<br>"
                f"<b>Area del poligono:</b> {terrain_area}<br>"
                f"<b>Confidenza della validazione:</b> {terrain_validation}<br>"
                f"<b>DEM:</b> {str(self.uncertainty_info.get('terrain_dem_layer_name') or self.uncertainty_info.get('terrain_dem_source') or '-')}"
                f" &nbsp;&nbsp; <b>Risoluzione:</b> {terrain_resolution}<br>"
                f"<b>Fallback:</b> {'Sì' if terrain_fallback else 'No'} &nbsp;&nbsp; "
                f"<b>Revisione manuale:</b> {'Sì' if terrain_review else 'No'}"
            )

        slge_html = ""
        if slge_active:
            slge_html = (
                "<br><br><b style='font-size:15px;'>MOTORE SEMANTICO DELLA LOCALITÀ E DELLA GEOMETRIA (SLGE)</b><br>"
                f"<b>Tipo di località:</b> {slge_feature}<br>"
                "<hr><b>DOCUMENT GEOMETRY</b><br>"
                f"<b>Disponibile:</b> {'Sì' if slge_available else 'No'}<br>"
                f"<b>Geometria attesa:</b> {slge_expected}<br>"
                f"<b>Forma GIS:</b> {(slge_geom_type if slge_available else '—')}<br>"
                f"<b>Origine:</b> {slge_source}<br>"
                f"<b>Metodo:</b> {slge_method}<br>"
                f"<b>Confidenza dell’interpretazione:</b> {slge_semantic_confidence} &nbsp;&nbsp; <b>Regola semantica:</b> {slge_rule}<br>"
                f"<b>Affidabilità della geometria (GCI):</b> {slge_confidence} ({slge_gci_class})"
                f"{slge_reasons_html}<br>"
                f"<b>Geometria stimata:</b> {slge_estimated} &nbsp;&nbsp; <b>Revisione manuale consigliata:</b> {slge_review}<br>"
                "<hr><b>SEARCH GEOMETRY</b><br>"
                f"<b>Strategia di costruzione:</b> {slge_search_strategy}<br>"
                f"<b>Origine della SearchGeometry:</b> {slge_search_source}<br>"
                f"<b>Geometria operativa finale:</b> {effective_geometry_type}<br>"
                f"<b>Raggio operativo effettivo:</b> {effective_radius}<br>"
                f"<b>Area effettiva:</b> {effective_area_text} &nbsp;&nbsp; "
                f"<b>Vertici:</b> {effective_vertex_text}<br>"
                f"<b>Ritagliata:</b> {'Sì' if effective_clipped else 'No'} &nbsp;&nbsp; "
                f"<b>Espansa:</b> {'Sì' if effective_expanded else 'No'}<br>"
                f"<b>Metodo dell’incertezza:</b> {uncertainty_method_label}<br>"
                f"<b>Filtri e valutazioni:</b> {slge_filters}"
                f"{admin_diag_html}"
                f"{terrain_html}"
            )

        info = QLabel(
            "<div style='line-height:1.28;'>"
            "<b style='font-size:15px;'>RISULTATO ECOLOGICO</b><br>"
            f"<b>Punto GeoLichen:</b> {eco_text}<br>"
            f"<b>Rank:</b> {rank_text} &nbsp;&nbsp; <b>GSS:</b> {score_text}<br>"
            f"<b>Distanza click–candidato:</b> {snap_text}<br>"
            f"<b>Raggio del modello R55–S70:</b> {model_radius:.1f} m<br>"
            f"<b>Affidabilità del modello (MCI):</b> {model_confidence_text}"
            f"{confidence_reasons_html}<br>"
            f"<b>Stabilità della soluzione (SSI):</b> {ssi_text}"
            f"{ssi_reasons_html}<br><br>"
            "<b style='font-size:15px;'>GEOREFERENZIAZIONE GBIF</b><br>"
            f"<b>Tipo di località:</b> {locality_label} ({geometry_label})<br>"
            f"<b>Confidenza della classificazione:</b> {float(class_conf) * 100.0:.0f}%<br>"
            f"<b>Centro corretto GBIF:</b> {corrected_text}<br>"
            f"<b>Distanza dal punto GeoLichen:</b> {center_distance_text}<br>"
            f"<b>Incertezza geografica GBIF:</b> {unc_text}"
            f"{point_floor_html}<br>"
            f"<b>Risoluzione del candidato:</b> "
            f"{self._format_optional_m(self.uncertainty_info.get('candidate_resolution_m'))}<br>"
            "<i>L'incertezza deriva dalla geometria della località; la risoluzione del candidato è una diagnostica separata.</i><br>"
            f"<b>Metodo di calcolo del centro:</b> {center_method_label}<br>"
            f"<b>Datum:</b> {datum_text} &nbsp;&nbsp; <b>Precisione coordinate:</b> {precision_text}<br>"
            f"<b>Stato Darwin Core:</b> {dwc_status}"
            f"{slge_html}"
            "</div>"
        )
        info.setWordWrap(True)
        info.setTextFormat(1)  # Qt.RichText senza import aggiuntivi
        contentLayout.addWidget(info)

        self.btnExplain = QPushButton("Mostra spiegazione del risultato")
        self.btnExplain.setEnabled(bool(self.explainability_report))
        self.btnExplain.clicked.connect(self._show_explainability)
        contentLayout.addWidget(self.btnExplain)

        self.btnValidateResult = QPushButton("Valida questo risultato")
        self.btnValidateResult.setEnabled(self.iface is not None and self.ecological_point_wgs84 is not None)
        self.btnValidateResult.clicked.connect(self._show_interactive_validation)
        contentLayout.addWidget(self.btnValidateResult)

        form = QFormLayout()

        self.txtX = QLineEdit(str(x_value))
        self.txtY = QLineEdit(str(y_value))
        self.txtDem = QLineEdit("" if dem_value is None else str(dem_value))

        self.cmbXField = QComboBox()
        self.cmbYField = QComboBox()
        self.cmbDemField = QComboBox()
        self.cmbUncertaintyField = QComboBox()
        self.cmbModelRadiusField = QComboBox()

        for cmb in [self.cmbXField, self.cmbYField, self.cmbDemField, self.cmbUncertaintyField, self.cmbModelRadiusField]:
            cmb.addItem("")
            cmb.addItems(self.fields)

        self._apply_default_or_auto(self.cmbXField, self.defaults.get("x_field"), ["x", "coord_x", "easting", "est", "utm_x"])
        self._apply_default_or_auto(self.cmbYField, self.defaults.get("y_field"), ["y", "coord_y", "northing", "nord", "utm_y"])
        self._apply_default_or_auto(self.cmbDemField, self.defaults.get("dem_field"), ["quota", "quota_dem", "dem", "altitudine", "altitude", "z"])
        self._apply_default_or_auto(
            self.cmbUncertaintyField,
            self.defaults.get("uncertainty_field"),
            [
                "coordinateuncertaintyinmeters",
                "incertezza gbif (m)",
                "incertezza gbif",
                "gbif_uncertainty",
                "uncertainty_m",
                "uncert_m",
            ],
        )
        self._apply_default_or_auto(
            self.cmbModelRadiusField,
            self.defaults.get("model_radius_field"),
            ["r55_s70", "r55", "model_radius_m", "model_radius", "incertezza_modello", "incertezza_r55"],
        )

        self.spinUncertainty = QDoubleSpinBox()
        self.spinUncertainty.setDecimals(1)
        self.spinUncertainty.setRange(0, 1000000)
        self.spinUncertainty.setSuffix(" m")
        self.spinUncertainty.setSpecialValueText("Non stimabile")
        try:
            self.spinUncertainty.setValue(float(self.defaults.get("uncertainty", 0) or 0))
        except Exception:
            self.spinUncertainty.setValue(0)

        self.txtModelRadius = QLineEdit(self._format_optional_m(model_radius))
        self.txtModelRadius.setReadOnly(True)

        try:
            gbif_uncertainty_value = float(self.spinUncertainty.value() or 0.0)
            model_radius_value = float(model_radius or 0.0)
            if gbif_uncertainty_value > 0.0 and model_radius_value > 0.0:
                comparison_text = f"{model_radius_value - gbif_uncertainty_value:+.1f} m"
            else:
                comparison_text = "-"
        except Exception:
            comparison_text = "-"
        self.txtUncertaintyDifference = QLineEdit(comparison_text)
        self.txtUncertaintyDifference.setReadOnly(True)

        self.txtCandidateResolution = QLineEdit(
            self._format_optional_m(self.uncertainty_info.get("candidate_resolution_m"))
        )
        self.txtCandidateResolution.setReadOnly(True)

        form.addRow("Coordinate X", self.txtX)
        form.addRow("Campo X", self.cmbXField)
        form.addRow("Coordinate Y", self.txtY)
        form.addRow("Campo Y", self.cmbYField)
        form.addRow("Quota DEM", self.txtDem)
        form.addRow("Campo quota DEM", self.cmbDemField)
        form.addRow("Incertezza GBIF", self.spinUncertainty)
        form.addRow("Campo incertezza GBIF", self.cmbUncertaintyField)
        form.addRow("Incertezza R55–S70", self.txtModelRadius)
        form.addRow("Campo incertezza R55–S70", self.cmbModelRadiusField)
        form.addRow("Differenza R55–S70 − GBIF", self.txtUncertaintyDifference)
        form.addRow("Risoluzione del candidato", self.txtCandidateResolution)
        contentLayout.addLayout(form)
        contentLayout.addStretch(1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = self.buttons.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText("Usa questo candidato")
        self.buttons.accepted.connect(self._validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)


    def _show_interactive_validation(self):
        try:
            from .interactive_validation_dialog import InteractiveValidationDialog
            eco_lat = float(self.ecological_point_wgs84.y())
            eco_lon = float(self.ecological_point_wgs84.x())
            mci = self.uncertainty_info.get("model_confidence_index")
            if mci is None:
                mci = self.uncertainty_info.get("model_confidence_score")
            context = {
                "geolichen_latitude": eco_lat,
                "geolichen_longitude": eco_lon,
                "gbif_latitude": self.uncertainty_info.get("corrected_center_lat"),
                "gbif_longitude": self.uncertainty_info.get("corrected_center_lon"),
                "uncertainty_m": self.spinUncertainty.value(),
                "geolichen_altitude_m": self.candidate_dem_value,
                "gss": self.candidate_score,
                "mci": mci,
                "ssi": self.uncertainty_info.get("solution_stability_index"),
                "candidate_rank": self.candidate_rank,
            }
            # Il dialogo deve restare non modale: in caso contrario il suo
            # event loop impedisce al QgsMapTool di acquisire il click sul canvas.
            # La referenza viene conservata per evitare la distruzione da parte
            # del garbage collector mentre la finestra è aperta.
            dialog = InteractiveValidationDialog(iface=self.iface, context=context, parent=self)
            dialog.setWindowModality(Qt.NonModal)
            dialog.setModal(False)
            dialog.setAttribute(Qt.WA_DeleteOnClose, True)
            self._interactive_validation_dialog = dialog
            dialog.destroyed.connect(lambda *_: setattr(self, '_interactive_validation_dialog', None))
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception as exc:
            QMessageBox.critical(self, "Validazione", f"Impossibile aprire la validazione:\n{exc}")

    def _show_explainability(self):
        report = self.explainability_report or {}
        if not report:
            QMessageBox.information(self, "Explainable GeoLichen", "Spiegazione non disponibile.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Explainable GeoLichen — Fase 11.3.1")
        dialog.resize(780, 680)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        browser.setOpenExternalLinks(False)
        browser.setHtml(self._explainability_html(report))
        layout.addWidget(browser)
        actions = QHBoxLayout()
        btn_json = QPushButton("Esporta JSON")
        btn_html = QPushButton("Esporta HTML")
        btn_pdf = QPushButton("Esporta PDF")
        btn_json.clicked.connect(lambda: self._export_explainability(report, "json"))
        btn_html.clicked.connect(lambda: self._export_explainability(report, "html"))
        btn_pdf.clicked.connect(lambda: self._export_explainability(report, "pdf"))
        actions.addWidget(btn_json)
        actions.addWidget(btn_html)
        actions.addWidget(btn_pdf)
        actions.addStretch(1)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec_()


    def _export_explainability(self, report, export_format):
        filters = {
            "json": "JSON (*.json)",
            "html": "HTML (*.html)",
            "pdf": "PDF (*.pdf)",
        }
        default_name = f"GeoLichen_explainability_rank_{report.get('selected_rank') or 1}.{export_format}"
        path, _ = QFileDialog.getSaveFileName(self, "Esporta report GeoLichen", default_name, filters[export_format])
        if not path:
            return
        if not path.lower().endswith("." + export_format):
            path += "." + export_format
        try:
            if export_format == "json":
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(report, handle, ensure_ascii=False, indent=2, default=str)
            elif export_format == "html":
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("<!doctype html><html><head><meta charset='utf-8'><title>GeoLichen Explainability Report</title></head><body>")
                    handle.write(self._explainability_html(report))
                    handle.write("</body></html>")
            else:
                from qgis.PyQt.QtGui import QTextDocument
                from qgis.PyQt.QtPrintSupport import QPrinter
                document = QTextDocument()
                document.setHtml(self._explainability_html(report))
                printer = QPrinter(QPrinter.HighResolution)
                printer.setOutputFormat(QPrinter.PdfFormat)
                printer.setOutputFileName(path)
                document.print_(printer)
            QMessageBox.information(self, "Explainable GeoLichen", f"Report esportato in:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Explainable GeoLichen", f"Esportazione non riuscita:\n{exc}")

    @classmethod
    def _explainability_html(cls, report):
        def esc(value):
            text = str(value if value is not None else "")
            return (text.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))

        html = [
            "<div style='font-family:sans-serif; line-height:1.35;'>",
            "<h2>Spiegazione del risultato ecologico</h2>",
            f"<p><b>Candidato selezionato:</b> Rank {esc(report.get('selected_rank'))} &nbsp; "
            f"<b>GSS:</b> {float(report.get('selected_score') or 0):.2f}<br>"
            f"<b>Architettura di scoring:</b> {esc(report.get('architecture'))}</p>",
            f"<p>{esc(report.get('main_reason'))}</p>",
            "<h3>1. Scomposizione del GSS</h3>",
            "<table cellspacing='0' cellpadding='5' border='1' width='100%'>"
            "<tr><th align='left'>Macro-componente</th><th>Score</th><th>Peso</th><th>Contributo al GSS</th></tr>",
        ]
        for row in report.get("macro_rows") or []:
            html.append(
                "<tr>"
                f"<td>{esc(row.get('label'))}</td>"
                f"<td align='right'>{float(row.get('score') or 0):.1f}</td>"
                f"<td align='right'>{float(row.get('weight') or 0):.1f}%</td>"
                f"<td align='right'><b>{float(row.get('contribution') or 0):.2f}</b></td>"
                "</tr>"
            )
        html.append("</table>")

        env_rows = report.get("environment_rows") or []
        if env_rows:
            html.extend([
                f"<h3>2. Dettaglio ambientale ({esc(report.get('environment_group'))})</h3>",
                "<table cellspacing='0' cellpadding='5' border='1' width='100%'>"
                "<tr><th align='left'>Sottocomponente</th><th>Stato</th><th>Score</th><th>Peso nominale</th><th>Peso effettivo</th><th>Contributo</th><th align='left'>Motivazione</th></tr>",
            ])
            for row in env_rows:
                score = row.get("score")
                score_text = "N/A" if score is None else f"{float(score):.1f}"
                weight = row.get("weight")
                weight_text = "-" if weight is None else f"{float(weight):.1f}%"
                effective_weight = row.get("effective_weight")
                effective_weight_text = "-" if effective_weight is None else f"{float(effective_weight):.1f}%"
                contribution = row.get("contribution")
                contribution_text = "-" if contribution is None else f"{float(contribution):.2f}"
                html.append(
                    "<tr>"
                    f"<td>{esc(row.get('label'))}</td>"
                    f"<td>{esc(row.get('status'))}</td>"
                    f"<td align='right'>{score_text}</td>"
                    f"<td align='right'>{weight_text}</td>"
                    f"<td align='right'>{effective_weight_text}</td>"
                    f"<td align='right'>{contribution_text}</td>"
                    f"<td>{esc(row.get('reason'))}</td>"
                    "</tr>"
                )
            html.append("</table>")

        html.append("<h3>3. Confronto con il miglior candidato alternativo</h3>")
        html.append(f"<p>{esc(report.get('comparison_summary'))}</p>")
        comp_rows = report.get("comparison_rows") or []
        if comp_rows:
            html.append(
                "<table cellspacing='0' cellpadding='5' border='1' width='100%'>"
                "<tr><th align='left'>Macro-componente</th><th>Selezionato</th><th>Alternativa</th><th>Differenza</th></tr>"
            )
            for row in comp_rows:
                html.append(
                    "<tr>"
                    f"<td>{esc(row.get('label'))}</td>"
                    f"<td align='right'>{float(row.get('selected') or 0):.1f}</td>"
                    f"<td align='right'>{float(row.get('other') or 0):.1f}</td>"
                    f"<td align='right'>{float(row.get('difference') or 0):+.1f}</td>"
                    "</tr>"
                )
            html.append("</table>")

        selected_diag = report.get("selected_diagnostics") or []
        if selected_diag:
            html.append("<h3>4. Diagnostica del candidato selezionato</h3><ul>")
            html.extend(f"<li>{esc(item)}</li>" for item in selected_diag)
            html.append("</ul>")

        diagnostics = report.get("candidate_diagnostics") or []
        if diagnostics:
            html.append("<h3>5. Diagnostica delle alternative</h3>")
            for item in diagnostics:
                html.append(
                    f"<p><b>Rank {esc(item.get('rank'))}</b> — GSS {float(item.get('score') or 0):.2f} "
                    f"(Δ {float(item.get('delta_gss') or 0):+.2f})</p><ul>"
                )
                details = item.get("items") or ["Nessuna diagnostica aggiuntiva disponibile."]
                html.extend(f"<li>{esc(detail)}</li>" for detail in details)
                html.append("</ul>")

        html.append("<h3>6. Catena decisionale</h3><ol>")
        html.extend(f"<li>{esc(step)}</li>" for step in (report.get("pipeline") or []))
        html.append("</ol>")

        provenance = report.get("provenance") or {}
        sources = provenance.get("sources") or []
        if sources:
            html.append("<h3>7. Provenienza dei dati</h3><table cellspacing='0' cellpadding='5' border='1' width='100%'><tr><th align='left'>Componente</th><th>Stato</th><th align='left'>Fonte</th><th align='left'>Dettaglio</th><th align='left'>Evidenza</th></tr>")
            for row in sources:
                html.append(
                    f"<tr><td>{esc(row.get('component'))}</td>"
                    f"<td>{esc(row.get('status'))}</td>"
                    f"<td>{esc(row.get('source'))}</td>"
                    f"<td>{esc(row.get('detail'))}</td>"
                    f"<td>{esc(row.get('evidence'))}</td></tr>"
                )
            html.append("</table>")

        decision_log = provenance.get("decision_log") or provenance.get("timeline") or []
        if decision_log:
            html.append("<h3>8. Decision Log</h3><table cellspacing='0' cellpadding='5' border='1' width='100%'><tr><th align='left'>Fase</th><th>Stato</th><th>Elementi</th><th align='left'>Dettaglio</th><th>Tempo</th></tr>")
            for row in decision_log:
                count = "-" if row.get("count") is None else esc(row.get("count"))
                duration = "-" if row.get("duration_ms") is None else f"{float(row.get('duration_ms')):.1f} ms"
                html.append(
                    f"<tr><td>{esc(row.get('stage'))}</td>"
                    f"<td>{esc(row.get('status'))}</td>"
                    f"<td align='right'>{count}</td>"
                    f"<td>{esc(row.get('detail'))}</td>"
                    f"<td align='right'>{duration}</td></tr>"
                )
            html.append("</table>")
            if provenance.get("timing_note"):
                html.append(f"<p><i>{esc(provenance.get('timing_note'))}</i></p>")

        dwc = provenance.get("darwin_core") or {}
        populated_dwc = [(key, value) for key, value in dwc.items() if value not in (None, "")]
        if populated_dwc:
            html.append("<h3>9. Metadati Darwin Core</h3><table cellspacing='0' cellpadding='5' border='1' width='100%'><tr><th align='left'>Campo</th><th align='left'>Valore</th></tr>")
            for key, value in populated_dwc:
                if key == "footprintWKT":
                    value = cls._summarize_footprint_wkt(value)
                html.append(f"<tr><td>{esc(key)}</td><td>{esc(value)}</td></tr>")
            html.append("</table>")
            if dwc.get("footprintWKT"):
                html.append("<p><i>Il WKT completo resta disponibile nell’esportazione JSON; nel report leggibile è mostrata solo una sintesi.</i></p>")

        html.append(
            "<p><i>La spiegazione legge esclusivamente i valori già prodotti dal motore. "
            "Non modifica GSS, ranking, MCI, SSI o georeferenziazione GBIF.</i></p></div>"
        )
        return "".join(html)


    @staticmethod
    def _summarize_footprint_wkt(value):
        text = str(value or "").strip()
        if not text:
            return "Non disponibile"
        geometry_type = text.split("(", 1)[0].strip().upper() or "GEOMETRIA"
        import re
        pairs = re.findall(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", text)
        vertex_count = len(pairs)
        summary = f"{geometry_type}; {vertex_count} vertici"
        if vertex_count >= 3:
            try:
                coords = [(float(x), float(y)) for x, y in pairs]
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                mean_lat = sum(y for _, y in coords[:-1]) / max(1, len(coords) - 1)
                m_per_deg_lat = 111132.0
                m_per_deg_lon = 111320.0 * math.cos(math.radians(mean_lat))
                xy = [(x * m_per_deg_lon, y * m_per_deg_lat) for x, y in coords]
                area = abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:]))) / 2.0
                if area >= 10000:
                    summary += f"; area approssimativa {area / 10000.0:.2f} ha"
                else:
                    summary += f"; area approssimativa {area:.0f} m²"
            except Exception:
                pass
        return summary

    @staticmethod
    def _locality_type_label(value):
        labels = {
            "municipality": "Comune",
            "municipality_only": "Solo comune",
            "named_feature": "Località geografica denominata",
            "near_feature": "Località in prossimità di un elemento geografico",
            "between_features": "Località compresa tra due elementi geografici",
            "linear_feature": "Elemento geografico lineare",
            "coordinates": "Coordinate esplicite",
            "unknown": "Tipo non determinato",
        }
        return labels.get(str(value or "unknown"), str(value or "unknown"))

    @staticmethod
    def _geometry_type_label(value):
        labels = {
            "point": "punto",
            "area": "area",
            "polygon": "area",
            "line": "linea",
            "linestring": "linea",
            "unknown": "geometria non determinata",
        }
        return labels.get(str(value or "unknown").lower(), str(value or "unknown"))

    @staticmethod
    def _slge_feature_label(value):
        labels = {
            "mountain": "Montagna",
            "mountain_group": "Gruppo montuoso",
            "peak": "Cima",
            "pass": "Passo",
            "refuge": "Rifugio",
            "church": "Chiesa o edificio religioso",
            "municipality": "Comune",
            "valley": "Valle",
            "lake": "Lago",
            "river": "Corso d’acqua",
            "trail": "Sentiero",
            "road": "Strada",
            "ridge": "Cresta o dorsale",
            "forest": "Area forestale",
            "meadow": "Prato o pascolo",
            "glacier": "Ghiacciaio",
            "generic_locality": "Località geografica",
            "unknown": "Tipo non determinato",
        }
        key = str(value or "unknown").lower()
        return labels.get(key, str(value or "-").replace("_", " ").capitalize())

    @staticmethod
    def _administrative_geometry_diagnostics_html(diag):
        if not isinstance(diag, dict) or not diag.get("active"):
            return ""

        def safe(value, default="-"):
            text = str(default if value in (None, "") else value)
            return (text.replace("&", "&amp;").replace("<", "&lt;")
                        .replace(">", "&gt;").replace('"', "&quot;"))

        def metres(value):
            try:
                return f"{float(value):.0f} m"
            except Exception:
                return "-"

        reasons = diag.get("reasons") or []
        reasons_html = ""
        if reasons:
            reasons_html = "<br>" + "<br>".join(f"• {safe(r)}" for r in reasons[:8])
        official_status = (
            "Non implementata in questo servizio"
            if not diag.get("official_layer_lookup_implemented")
            else safe(diag.get("official_layer_lookup_status"))
        )
        osm_status = "Riuscita" if diag.get("osm_lookup_success") else "Fallita"
        compatible = "Sì" if diag.get("osm_administrative_polygon_compatible") else "No"
        fallback = "Sì" if diag.get("fallback_used") else "No"
        cache = "Sì" if diag.get("osm_from_cache") else "No"
        error_line = ""
        if diag.get("osm_error"):
            error_line = f"<br><b>Errore OSM:</b> {safe(diag.get('osm_error'))}"

        return (
            "<br><br><b>DIAGNOSTICA DELLA GEOMETRIA AMMINISTRATIVA</b><br>"
            f"<b>Comune richiesto:</b> {safe(diag.get('requested_municipality'))}<br>"
            f"<b>Ricerca su layer comunale ufficiale:</b> {official_status}<br>"
            f"<b>BBox del geocoder:</b> {'Disponibile' if diag.get('geocoder_bbox_available') else 'Assente'} "
            f"({metres(diag.get('geocoder_bbox_width_m'))} × {metres(diag.get('geocoder_bbox_height_m'))})<br>"
            f"<b>Ricerca OSM amministrativa:</b> {osm_status} &nbsp;&nbsp; "
            f"<b>Da cache:</b> {cache}<br>"
            f"<b>Elemento OSM:</b> {safe(diag.get('osm_object_type'))} {safe(diag.get('osm_id'))} — "
            f"{safe(diag.get('osm_name'))}<br>"
            f"<b>Geometria OSM:</b> {safe(diag.get('osm_geometry_type'))} &nbsp;&nbsp; "
            f"<b>boundary:</b> {safe(diag.get('osm_boundary_tag'))} &nbsp;&nbsp; "
            f"<b>admin_level:</b> {safe(diag.get('osm_admin_level'))}<br>"
            f"<b>Poligono amministrativo compatibile:</b> {compatible}<br>"
            f"<b>Strategia finale:</b> {safe(diag.get('search_strategy'))}<br>"
            f"<b>Geometria finale:</b> {safe(diag.get('final_search_geometry_type'))} &nbsp;&nbsp; "
            f"<b>Fallback usato:</b> {fallback}"
            f"{error_line}"
            f"{reasons_html}"
        )

    @staticmethod
    def _slge_geometry_label(value):
        labels = {
            "POINT": "Punto",
            "LINE": "Linea",
            "POLYGON": "Poligono",
            "ADMIN": "Confine amministrativo",
            "UNKNOWN": "Non determinata",
        }
        key = str(value or "UNKNOWN").upper()
        return labels.get(key, str(value or "-").replace("_", " ").capitalize())

    @staticmethod
    def _slge_rule_label(value):
        text = str(value or "-").strip()
        return ConfirmPointDialog._slge_feature_label(text) if text != "-" else text

    @staticmethod
    def _slge_search_strategy_label(value):
        labels = {
            "mountain_bbox_or_adaptive_buffer": "Estensione montana o buffer adattivo",
            "mountain_group_bbox_or_adaptive_buffer": "Estensione del gruppo montuoso o buffer adattivo",
            "geocoder_bbox_plus_150m": "Estensione del geocoder ampliata di 150 m",
            "geocoder_bbox_plus_250m": "Estensione del geocoder ampliata di 250 m",
            "geocoder_bbox_plus_500m": "Estensione del geocoder ampliata di 500 m",
            "municipality_geocoder_extent": "Intero confine comunale disponibile",
            "municipality_point_fallback_2000m": "Buffer comunale provvisorio di 2 km",
            "legacy_boundary": "Area di ricerca originaria",
        }
        key = str(value or "-")
        if key.startswith("point_fallback_buffer_"):
            radius = key.replace("point_fallback_buffer_", "").replace("m", " m")
            return f"Buffer operativo di {radius}"
        return labels.get(key, key.replace("_", " ").capitalize())

    @staticmethod
    def _slge_search_source_label(value):
        labels = {
            "explicit_search_geometry": "Geometria operativa dedicata",
            "documented_geometry_seed": "Geometria documentale usata come base",
            "openstreetmap_geometry": "Geometria reale OpenStreetMap",
            "semantic_geometry_fallback": "Ricostruzione semantica di fallback",
        }
        key = str(value or "-")
        return labels.get(key, key.replace("_", " ").capitalize())

    @staticmethod
    def _slge_filters_label(values):
        labels = {
            "record_environment_overlay": "Vincoli ambientali applicati all’area",
            "record_environment_overlay_scoring_only": "Vincoli ambientali valutati nel punteggio GSS",
            "altitude_hard_filter": "Filtro altitudinale vincolante",
        }
        items = [labels.get(str(v), str(v).replace("_", " ").capitalize()) for v in (values or [])]
        return "; ".join(items) if items else "Nessun filtro aggiuntivo"

    @staticmethod
    def _uncertainty_method_label(value):
        labels = {
            "gbif_point_radius_effective_buffer": (
                "distanza massima dal centro corretto GBIF al bordo della geometria operativa effettiva"
            ),
            "gbif_point_radius": "metodo point-radius GBIF sulla geometria selezionata",
            "max_distance_to_polygon": "distanza massima dal centro corretto al bordo del poligono",
            "minimum_enclosing_circle": "cerchio minimo contenente la geometria",
        }
        key = str(value or "").strip()
        return labels.get(key, key.replace("_", " ") if key else "Non disponibile")

    @staticmethod
    def _format_optional_m(value):
        try:
            if value is None:
                return "Non disponibile"
            return f"{float(value):.1f} m"
        except Exception:
            return "Non disponibile"

    @staticmethod
    def _center_method_label(value):
        labels = {
            "centroid_within_extent": "Centro geometrico interno all’estensione della località",
            "point_on_surface": "Punto interno rappresentativo della località",
            "geocoder_point": "Punto restituito dal geocoder",
            "declared_coordinates": "Coordinate dichiarate nel record",
            "manual_point": "Punto indicato manualmente",
            "ecological_point_fallback": "Punto GeoLichen usato come ripiego",
        }
        key = str(value or "").strip()
        return labels.get(key, key.replace("_", " ") if key else "Non disponibile")

    @staticmethod
    def _model_confidence_label(value):
        labels = {
            "very_low": "Molto bassa",
            "low": "Bassa",
            "medium": "Media",
            "moderate": "Media",
            "high": "Alta",
            "very_high": "Molto alta",
        }
        key = str(value or "-").strip().lower()
        return labels.get(key, str(value or "-"))

    @staticmethod
    def _center_distance_text(lon, lat, ecological_point):
        if lon is None or lat is None or ecological_point is None:
            return "non calcolabile"
        try:
            eco_lon = float(ecological_point.x())
            eco_lat = float(ecological_point.y())
            lon = float(lon)
            lat = float(lat)
            radius = 6371008.8
            phi1 = math.radians(eco_lat)
            phi2 = math.radians(lat)
            dphi = math.radians(lat - eco_lat)
            dlambda = math.radians(lon - eco_lon)
            a = (
                math.sin(dphi / 2.0) ** 2
                + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
            )
            distance = radius * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
            return f"{distance:.1f} m"
        except Exception:
            return "non calcolabile"

    def _apply_default_or_auto(self, combo, default_field, candidates):
        if default_field and default_field in self.fields:
            combo.setCurrentText(default_field)
            return
        self._auto_select_field(combo, candidates)

    def _auto_select_field(self, combo, candidates):
        lower_fields = {str(f).lower(): f for f in self.fields}
        for cand in candidates:
            if cand.lower() in lower_fields:
                combo.setCurrentText(lower_fields[cand.lower()])
                return
        for f in self.fields:
            lf = str(f).lower()
            if any(c in lf for c in candidates):
                combo.setCurrentText(f)
                return

    def _validate_and_accept(self):
        if not self.cmbXField.currentText().strip() or not self.cmbYField.currentText().strip():
            QMessageBox.warning(self, "Campi mancanti", "Seleziona almeno i campi X e Y.")
            return
        uncertainty_field = self.cmbUncertaintyField.currentText().strip()
        model_radius_field = self.cmbModelRadiusField.currentText().strip()
        if not uncertainty_field:
            QMessageBox.warning(
                self,
                "Campo incertezza GBIF mancante",
                "Seleziona il campo in cui scrivere l'incertezza GBIF calcolata.",
            )
            return
        if not model_radius_field:
            QMessageBox.warning(
                self,
                "Campo R55–S70 mancante",
                "Seleziona un campo distinto in cui scrivere l'incertezza R55–S70.",
            )
            return
        if uncertainty_field == model_radius_field:
            QMessageBox.warning(
                self,
                "Campi coincidenti",
                "L'incertezza GBIF e l'incertezza R55–S70 devono essere scritte in due colonne diverse.",
            )
            return
        self.accept()

    def values(self):
        dem_text = self.txtDem.text().strip()
        dem_value = None
        if dem_text:
            try:
                dem_value = float(dem_text)
            except Exception:
                dem_value = dem_text

        return {
            "x": self.txtX.text().strip(),
            "y": self.txtY.text().strip(),
            "dem": dem_value,
            "uncertainty": (
                float(self.spinUncertainty.value())
                if self.spinUncertainty.value() > 0 else None
            ),
            "model_radius": (
                float(self.uncertainty_info.get("model_radius_m"))
                if self.uncertainty_info.get("model_radius_m") is not None else None
            ),
            "x_field": self.cmbXField.currentText().strip(),
            "y_field": self.cmbYField.currentText().strip(),
            "dem_field": self.cmbDemField.currentText().strip(),
            "uncertainty_field": self.cmbUncertaintyField.currentText().strip(),
            "model_radius_field": self.cmbModelRadiusField.currentText().strip(),
        }
