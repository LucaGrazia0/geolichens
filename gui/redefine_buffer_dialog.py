from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
)


class RedefineBufferDialog(QDialog):
    """Dialog per scegliere come ridefinire il buffer corrente."""

    def __init__(self, current_radius_m=250.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ridefinisci buffer")

        layout = QVBoxLayout(self)

        info = QLabel(
            "Scegli come ridefinire il buffer. Il buffer corrente verrà sostituito "
            "solo dopo il click sulla mappa e la conferma finale."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.rbMove = QRadioButton("Sposta buffer: nuovo centro, stesso raggio")
        self.rbNew = QRadioButton("Nuovo buffer: nuovo centro e nuovo raggio")
        self.rbMove.setToolTip('Cambia il centro del buffer mantenendo il raggio attuale.')
        self.rbNew.setToolTip('Scegli un nuovo centro e usa il raggio indicato qui sotto.')
        self.rbMove.setChecked(True)
        layout.addWidget(self.rbMove)
        layout.addWidget(self.rbNew)

        form = QFormLayout()
        self.spinRadius = QDoubleSpinBox()
        self.spinRadius.setRange(1, 100000)
        self.spinRadius.setDecimals(1)
        self.spinRadius.setSuffix(" m")
        self.spinRadius.setValue(float(current_radius_m or 250.0))
        form.addRow("Raggio buffer", self.spinRadius)
        layout.addLayout(form)

        self.rbMove.toggled.connect(self._sync_radius_enabled)
        self._sync_radius_enabled()

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip('Passa alla mappa per scegliere il nuovo centro del buffer.')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip('Annulla questo passaggio senza confermare i dati.')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _sync_radius_enabled(self):
        self.spinRadius.setEnabled(self.rbNew.isChecked())

    def values(self):
        return {
            "mode": "move" if self.rbMove.isChecked() else "new",
            "radius_m": float(self.spinRadius.value()),
        }
