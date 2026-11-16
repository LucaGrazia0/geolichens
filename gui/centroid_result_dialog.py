"""Confirm a locality centroid without ecological scores or candidate ranking."""

from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QMessageBox, QVBoxLayout,
)


class CentroidResultDialog(QDialog):
    def __init__(self, fields, longitude, latitude, elevation, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Centroide della località')
        self.resize(450, 280)
        self.longitude = longitude
        self.latitude = latitude
        self.elevation = elevation
        layout = QVBoxLayout(self)
        intro = QLabel('Posizione ricavata dal centroide dell’area di ricerca.\n'
                       'Non sono stati usati punteggi o candidati ecologici.\n'
                       'Il punto sarà aggiunto al layer dei punti confermati.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.addRow('Longitudine (WGS84)', QLabel(f'{longitude:.8f}'))
        form.addRow('Latitudine (WGS84)', QLabel(f'{latitude:.8f}'))
        form.addRow('Quota DEM', QLabel('Non disponibile' if elevation is None else f'{elevation:.2f} m'))
        self.field_combos = {}
        for key, title, aliases in [
            ('x_field', 'Campo longitudine (facoltativo)', ['longitude', 'decimallongitude', 'lon', 'longitudine']),
            ('y_field', 'Campo latitudine (facoltativo)', ['latitude', 'decimallatitude', 'lat', 'latitudine']),
            ('dem_field', 'Campo quota DEM (facoltativo)', ['quota_dem', 'altitude_dem', 'dem', 'elevation_dem']),
        ]:
            combo = QComboBox()
            combo.addItem('Non scrivere nella tabella', '')
            for name in fields:
                combo.addItem(name, name)
            for alias in aliases:
                match = next((n for n in fields if n.lower() == alias), None)
                if match:
                    combo.setCurrentIndex(combo.findData(match))
                    break
            self.field_combos[key] = combo
            form.addRow(title, combo)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip('Annulla questo passaggio senza confermare i dati.')
        buttons.button(QDialogButtonBox.StandardButton.Save).setToolTip('Salva il centroide e la quota DEM nei campi scelti e nei punti confermati.')
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Salva centroide')
        buttons.accepted.connect(self._accept_fields)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_fields(self):
        selected = [c.currentData() for c in self.field_combos.values() if c.currentData()]
        if len(set(selected)) != len(selected):
            QMessageBox.warning(self, 'Campi distinti', 'Seleziona campi diversi per longitudine, latitudine e quota.')
            return
        self.accept()

    def values(self):
        values = {key: combo.currentData() for key, combo in self.field_combos.items()}
        values.update(x=self.longitude, y=self.latitude, dem=self.elevation,
                      uncertainty=None, model_radius=None)
        return values
