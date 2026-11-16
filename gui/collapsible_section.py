"""Compact disclosure sections using the QGIS-provided Qt widgets."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    def __init__(self, title, parent=None, expanded=False, full_width=False):
        super().__init__(parent)
        self.header = QToolButton(self)
        self.header.setText(title)
        self.header.setAccessibleName(title.replace("\n", " "))
        self.header.setToolTip('Mostra o nasconde: ' + title.replace("\n", " ") + '.')
        self.header.setCheckable(True)
        if full_width:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setStyleSheet("QToolButton { text-align: left; padding: 6px; font-weight: bold; }")
        self.content = QWidget(self)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(6, 4, 6, 6)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.header)
        layout.addWidget(self.content)
        self.header.toggled.connect(self.setExpanded)
        self.setExpanded(expanded)

    def setExpanded(self, expanded):
        self.header.setChecked(bool(expanded))
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(bool(expanded))
