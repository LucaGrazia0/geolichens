"""Writable per-profile storage, separate from installed plugin source."""

from pathlib import Path

from qgis.core import QgsApplication


def profile_data_path(filename):
    directory = Path(QgsApplication.qgisSettingsDirPath()) / "geolichen"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / filename)
