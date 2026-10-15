from qgis.PyQt.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout
from ..models.input_mapping_model import InputMappingModel
from ..services.field_mapper_service import FieldMapperService


class FieldMappingDialog(QDialog):
    def __init__(self, field_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configura campi input")
        self.field_names = list(field_names)
        self.mapper = FieldMapperService()
        self.suggested = self.mapper.suggest_mapping(self.field_names)
        self.combos = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addWidget(QLabel("Seleziona i campi da usare. Record ID è facoltativo."))

        specs = [
            ("record_id", "Record ID (facoltativo)"),
            ("municipality", "Comune"),
            ("locality", "Località"),
            ("scientific_name", "Specie / Taxon"),
            ("substrate", "Tipo di substrato (facoltativo)"),
            ("rock_type", "Tipo di roccia (facoltativo)"),
            ("tree_type", "Tipo di albero (facoltativo)"),
            ("elevation", "Quota (facoltativo)"),
            ("notes", "Note (facoltativo)"),
        ]

        for key, label in specs:
            combo = QComboBox()
            combo.addItem("", "")
            for f in self.field_names:
                combo.addItem(f, f)
            suggested = getattr(self.suggested, key)
            if suggested:
                idx = combo.findData(suggested)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self.combos[key] = combo
            form.addRow(label, combo)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_mapping(self):
        model = InputMappingModel()
        for key, combo in self.combos.items():
            setattr(model, key, combo.currentData() or None)
        return model
