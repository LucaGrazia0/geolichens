from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtCore import Qt

from .gui.main_dock import MainDock
from .controllers.plugin_controller import PluginController


class GeoLichenPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.validation_action = None
        self.validation_dialog = None
        self.benchmark_action = None
        self.benchmark_dialog = None
        self.performance_action = None
        self.performance_dialog = None
        self.release_action = None
        self.release_dialog = None
        self.performance_service = None
        self.dock = None
        self.controller = None

    def initGui(self):
        self.action = QAction("GeoLichen", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu("GeoLichen", self.action)
        self.iface.addToolBarIcon(self.action)

        self.validation_action = QAction("GeoLichen — Validazione scientifica", self.iface.mainWindow())
        self.validation_action.triggered.connect(self.open_validation)
        self.iface.addPluginToVectorMenu("GeoLichen", self.validation_action)

        self.benchmark_action = QAction("GeoLichen — Benchmark scientifico", self.iface.mainWindow())
        self.benchmark_action.triggered.connect(self.open_benchmark)
        self.iface.addPluginToVectorMenu("GeoLichen", self.benchmark_action)

        from .services.performance_service import PerformanceService
        self.performance_service = PerformanceService()
        self.performance_action = QAction("GeoLichen — Performance e robustezza", self.iface.mainWindow())
        self.performance_action.triggered.connect(self.open_performance)
        self.iface.addPluginToVectorMenu("GeoLichen", self.performance_action)

        self.release_action = QAction("GeoLichen — Controllo Release Candidate", self.iface.mainWindow())
        self.release_action.triggered.connect(self.open_release_readiness)
        self.iface.addPluginToVectorMenu("GeoLichen", self.release_action)

    def unload(self):
        if self.controller:
            try:
                self.controller.cleanup()
            except Exception:
                pass
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.validation_dialog:
            try:
                self.validation_dialog.close()
                self.validation_dialog.deleteLater()
            except Exception:
                pass
            self.validation_dialog = None
        if self.validation_action:
            self.iface.removePluginVectorMenu("GeoLichen", self.validation_action)
            self.validation_action.deleteLater()
            self.validation_action = None
        if self.benchmark_dialog:
            try:
                self.benchmark_dialog.close()
                self.benchmark_dialog.deleteLater()
            except Exception:
                pass
            self.benchmark_dialog = None
        if self.benchmark_action:
            self.iface.removePluginVectorMenu("GeoLichen", self.benchmark_action)
            self.benchmark_action.deleteLater()
            self.benchmark_action = None
        if self.performance_dialog:
            try:
                self.performance_dialog.close()
                self.performance_dialog.deleteLater()
            except Exception:
                pass
            self.performance_dialog = None
        if self.performance_action:
            self.iface.removePluginVectorMenu("GeoLichen", self.performance_action)
            self.performance_action.deleteLater()
            self.performance_action = None
        if self.release_dialog:
            try:
                self.release_dialog.close()
                self.release_dialog.deleteLater()
            except Exception:
                pass
            self.release_dialog = None
        if self.release_action:
            self.iface.removePluginVectorMenu("GeoLichen", self.release_action)
            self.release_action.deleteLater()
            self.release_action = None
        if self.action:
            self.iface.removePluginVectorMenu("GeoLichen", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        self.controller = None

    def run(self):
        if self.dock is None:
            self.dock = MainDock(self.iface)
            self.controller = PluginController(self.iface, self.dock, performance_service=self.performance_service)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()

    def open_validation(self):
        from .gui.validation_dialog import ValidationDialog
        if self.validation_dialog is None:
            self.validation_dialog = ValidationDialog(self.iface.mainWindow())
            self.validation_dialog.finished.connect(self._validation_closed)
        self.validation_dialog.show()
        self.validation_dialog.raise_()
        self.validation_dialog.activateWindow()

    def _validation_closed(self, *args):
        if self.validation_dialog is not None:
            try:
                self.validation_dialog.deleteLater()
            except Exception:
                pass
        self.validation_dialog = None

    def open_benchmark(self):
        from .gui.benchmark_dialog import BenchmarkDialog
        if self.benchmark_dialog is None:
            self.benchmark_dialog = BenchmarkDialog(self.iface.mainWindow())
            self.benchmark_dialog.finished.connect(self._benchmark_closed)
        self.benchmark_dialog.show()
        self.benchmark_dialog.raise_()
        self.benchmark_dialog.activateWindow()

    def _benchmark_closed(self, *args):
        if self.benchmark_dialog is not None:
            try:
                self.benchmark_dialog.deleteLater()
            except Exception:
                pass
        self.benchmark_dialog = None

    def open_performance(self):
        from .gui.performance_dialog import PerformanceDialog
        if self.performance_dialog is None:
            self.performance_dialog = PerformanceDialog(self.iface, self.performance_service, self.iface.mainWindow())
            self.performance_dialog.finished.connect(self._performance_closed)
        self.performance_dialog.show()
        self.performance_dialog.raise_()
        self.performance_dialog.activateWindow()

    def _performance_closed(self, *args):
        if self.performance_dialog is not None:
            try:
                self.performance_dialog.deleteLater()
            except Exception:
                pass
        self.performance_dialog = None

    def open_release_readiness(self):
        import os
        from .services.release_readiness_service import ReleaseReadinessService
        from .gui.release_readiness_dialog import ReleaseReadinessDialog
        if self.release_dialog is None:
            service = ReleaseReadinessService(os.path.dirname(__file__))
            self.release_dialog = ReleaseReadinessDialog(service, self.iface.mainWindow())
            self.release_dialog.finished.connect(self._release_closed)
        self.release_dialog.show()
        self.release_dialog.raise_()
        self.release_dialog.activateWindow()

    def _release_closed(self, *args):
        if self.release_dialog is not None:
            try:
                self.release_dialog.deleteLater()
            except Exception:
                pass
        self.release_dialog = None
