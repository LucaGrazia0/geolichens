"""Run real PyQt6 widget checks without pretending to be a QGIS 4 runtime.

Use a separate Python with PyQt6 installed, never inside the Qt5 QGIS process.
Only the qgis.PyQt namespace is bridged; no GIS classes or providers are faked.
QGIS-dependent dialogs remain covered by regression_interface.py in QGIS.
"""

import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from enum import Enum

from PyQt6 import QtCore, QtGui, QtWidgets, QtNetwork, QtPrintSupport, sip

ROOT = Path(__file__).resolve().parents[1]
qt_modules = dict(QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets,
                  QtNetwork=QtNetwork, QtPrintSupport=QtPrintSupport)
qgis = types.ModuleType('qgis')
qgis.__path__ = []
pyqt = types.ModuleType('qgis.PyQt')
pyqt.__path__ = []
pyqt.sip = sip
qgis.PyQt = pyqt
sys.modules.update({'qgis': qgis, 'qgis.PyQt': pyqt, 'qgis.PyQt.sip': sip})
for name, module in qt_modules.items():
    sys.modules[f'qgis.PyQt.{name}'] = module
spec = importlib.util.spec_from_file_location('geolichen', ROOT / '__init__.py',
                                             submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules['geolichen'] = package
spec.loader.exec_module(package)
# core/__init__.py exports GIS engines; load only the pure helper modules here.
core_package = types.ModuleType('geolichen.core')
core_package.__path__ = [str(ROOT / 'core')]
sys.modules['geolichen.core'] = core_package

from geolichen.gui.main_dock import MainDock
from geolichen.gui.collapsible_section import CollapsibleSection
from geolichen.gui.candidate_selector_dialog import CandidateSelectorDialog
from geolichen.gui.ecological_point_choice_dialog import EcologicalPointChoiceDialog, CandidateUseDialog
from geolichen.gui.centroid_result_dialog import CentroidResultDialog
from geolichen.gui.reuse_confirmed_point_dialog import ReuseConfirmedPointDialog
from geolichen.gui.field_mapping_dialog import FieldMappingDialog
from geolichen.gui.redefine_buffer_dialog import RedefineBufferDialog
from geolichen.core.enum_utils import enum_value
from geolichen.core.geometry_validation import actual_geometry_type

APP = QtWidgets.QApplication([])


class Qt6Widgets(unittest.TestCase):
    def test_dock_and_disclosure(self):
        window = QtWidgets.QMainWindow()
        iface = types.SimpleNamespace(mainWindow=lambda: window)
        dock = MainDock(iface)
        window.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)
        window.resize(600, 900)
        window.show()
        APP.processEvents()
        dock.configurationSection.setExpanded(True)
        APP.processEvents()
        self.assertTrue(dock.configurationSection.content.isVisible())
        dock.configurationSection.setExpanded(False)
        window.close()

    def test_guided_decisions_and_exec(self):
        for decision in ('use', 'retry'):
            dialog = CandidateUseDialog(1, 80.5, 1.0)
            QtCore.QTimer.singleShot(0, lambda d=dialog, c=decision: d._choose(c))
            self.assertEqual(dialog.exec(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.decision, decision)
        dialog = CandidateUseDialog(1, 80.5, 1.0)
        QtCore.QTimer.singleShot(0, dialog.reject)
        self.assertEqual(dialog.exec(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertEqual(dialog.decision, 'exit')
        dialog = EcologicalPointChoiceDialog(12)
        self.assertEqual(dialog.next_button.text(), 'Avanti')
        dialog.close()

    def test_map_area_lookup_can_retry_without_losing_old_choices(self):
        from types import SimpleNamespace
        candidate = {'text': 'Foppe', 'center': [10.2,46.05]}
        result = SimpleNamespace(candidates=[], error='Nessun risultato nella zona', warning=None)
        dialog = CandidateSelectorDialog([candidate], query='Foppe', area_search_callback=lambda *a: result)
        dialog.show(); APP.processEvents()
        self.assertTrue(dialog.area_search_button.isVisible())
        dialog.area_search_button.click()
        self.assertEqual(dialog.candidates, [candidate])
        self.assertIn('precedenti conservate', dialog.search_status.text())
        self.assertTrue(dialog.area_search_button.isEnabled())
        dialog.close()

    def test_other_independent_dialogs(self):
        dialogs = [
            CandidateSelectorDialog([{'place_name': 'Test locality', 'center': [10.2, 46.0]}]),
            CentroidResultDialog(['longitude', 'latitude', 'quota_dem'], 10.2, 46.0, 1800),
            ReuseConfirmedPointDialog([{'locality': 'Test', 'longitude': 10.2,
                                       'latitude': 46.0, 'altitude_m': 1800.0}]),
            FieldMappingDialog(['scientific_name', 'municipality', 'locality']),
            RedefineBufferDialog(),
        ]
        for dialog in dialogs:
            dialog.show()
            APP.processEvents()
            dialog.close()

    def test_locality_choice_buttons_confirm_selected_row_or_cancel(self):
        for count in (1, 2):
            candidates = [{'place_name': f'Test locality {i}', 'center': [10.2 + i * .01, 46]}
                          for i in range(count)]
            dialog = CandidateSelectorDialog(candidates)
            buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
            confirm = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
            self.assertEqual(confirm.text(), 'Crea buffer')
            def choose(d=dialog, b=confirm, row=count - 1):
                d.table.selectRow(row)
                b.click()
            QtCore.QTimer.singleShot(0, choose)
            self.assertEqual(dialog.exec(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertIs(dialog.selected(), candidates[-1])
        dialog = CandidateSelectorDialog(candidates)
        buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
        QtCore.QTimer.singleShot(0, buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).click)
        self.assertEqual(dialog.exec(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertIsNone(dialog.selected())

    def test_deeper_locality_search_updates_real_qt6_table(self):
        selected = {'text': 'Monte di prova', 'center': [10.2, 46.0]}
        result = types.SimpleNamespace(candidates=[selected], error=None)
        dialog = CandidateSelectorDialog([], query='M.te di prova', search_callback=lambda *a: result)
        confirm = dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(confirm.isEnabled())
        dialog.search_button.click()
        self.assertTrue(confirm.isEnabled())
        self.assertEqual(dialog.table.rowCount(), 1)
        confirm.click()
        self.assertIs(dialog.selected(), selected)
        dialog.close()

    def test_enum_values_and_geometry_types(self):
        class Kind(Enum):
            Point = 0
            Line = 1
            Polygon = 2
        for kind in Kind:
            geom = types.SimpleNamespace(isEmpty=lambda: False, type=lambda: kind)
            self.assertEqual(actual_geometry_type(geom), kind.name.upper())
            self.assertEqual(enum_value(kind), kind.value)
        self.assertEqual(enum_value(QtNetwork.QNetworkReply.NetworkError.ConnectionRefusedError), 1)
        self.assertEqual(enum_value(2), 2)

    def test_all_qt_attribute_spellings(self):
        paths = [ROOT / 'plugin.py']
        paths += [p for folder in ('gui', 'controllers', 'services', 'models', 'core', 'tests')
                  for p in (ROOT / folder).rglob('*.py') if p.name != 'qgis_compat.py']
        checked = set()
        for path in paths:
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                names = []
                value = node
                while isinstance(value, ast.Attribute):
                    names.insert(0, value.attr)
                    value = value.value
                if not isinstance(value, ast.Name):
                    continue
                cls = next((getattr(m, value.id) for m in qt_modules.values()
                            if hasattr(m, value.id)), None)
                if cls is None:
                    continue
                key = (value.id, *names)
                if key in checked:
                    continue
                checked.add(key)
                for name in names:
                    self.assertTrue(hasattr(cls, name), f'{path.name}:{node.lineno}: {key}')
                    cls = getattr(cls, name)
        self.assertGreater(len(checked), 80)


if __name__ == '__main__':
    unittest.main(verbosity=2)
