"""Short prompts between ecological ranking, map picking and data entry."""

from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)


class EcologicalPointChoiceDialog(QDialog):
    def __init__(self, candidate_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Scelta del punto ecologico')
        self.resize(460, 180)
        layout = QVBoxLayout(self)
        label = QLabel(
            f'La griglia è pronta: {candidate_count} punti candidati.\n\n'
            'Premi Avanti e scegli un punto sulla mappa. '
            'Il cursore si aggancerà al candidato più vicino.')
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip('Attiva la scelta manuale di un candidato sulla mappa.')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip('Annulla questo passaggio senza confermare i dati.')
        self.next_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.next_button.setText('Avanti')
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button.setText('Cancel')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CandidateUseDialog(QDialog):
    def __init__(self, rank, score, distance_m, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Scelta del punto ecologico')
        self.resize(460, 180)
        self.decision = 'exit'
        layout = QVBoxLayout(self)
        label = QLabel(f'Vuoi usare questo punto di rank {rank}?\n\n'
                       f'GSS: {score:.2f} · Distanza dal clic: {distance_m:.1f} m')
        label.setWordWrap(True)
        layout.addWidget(label)
        # Explicit layout keeps use/retry together on every Qt platform.
        buttons = QHBoxLayout()
        self.use_button = QPushButton('Sì')
        self.use_button.setToolTip('Apri la finestra candidato per controllare e confermare i dati di questo punto.')
        self.retry_button = QPushButton('Riprova')
        self.retry_button.setToolTip('Scegli un altro candidato sulla stessa griglia, senza ripetere l’analisi.')
        self.exit_button = QPushButton('Esci')
        self.exit_button.setToolTip('Termina la scelta del punto senza scrivere i dati del candidato.')
        buttons.addWidget(self.exit_button)
        buttons.addStretch(1)
        buttons.addWidget(self.retry_button)
        buttons.addWidget(self.use_button)
        self.use_button.setDefault(True)
        self.use_button.clicked.connect(lambda: self._choose('use'))
        self.retry_button.clicked.connect(lambda: self._choose('retry'))
        self.exit_button.clicked.connect(self.reject)
        layout.addLayout(buttons)

    def _choose(self, decision):
        self.decision = decision
        self.accept()
