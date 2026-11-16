# QGIS 3 / QGIS 4 compatibility - GeoLichen 15.6.31

Version 15.6.19 introduced the port of the plugin to the Qt 6 APIs used by QGIS 4 while keeping
QGIS 3.22+ compatibility. Metadata permits installation on QGIS 4.x
(`qgisMaximumVersion=4.99`). The release remains experimental.

## Changes

- Import QAction from QtGui on Qt 6 and QtWidgets on Qt 5.
- Use scoped Qt enums and `exec()` for dialogs and event loops, including test mocks.
- Create QgsField values with QMetaType.Type on QGIS 3.38+; retain QVariant.Type
  for the older QgsField API. This applies to candidate, confirmed and trail
  layers and automatically created output columns.
- Prefer modern Qgis enums for geometry, layers, DEM identification, raster
  resampling, shader interpolation and provider capabilities, with older-QGIS fallbacks.
- Convert enum `.value` explicitly where a numeric code is needed. This prevents
  geometry classification and network errors from relying on `int(Enum)`.

Ecological weights, score formulas, uncertainty formulas, rank ordering,
analysis workflows, field names and data formats are unchanged.

## Verification and limits

See the final results in docs/VERIFICATION.md. A standalone PyQt6 check exercises
actual Qt 6 widgets and API names. It aliases only the `qgis.PyQt` import namespace
and does not implement or validate QGIS geometry, providers or GIS rendering.
It is **not** an end-to-end test in QGIS 4.

This workstation has QGIS 3.44.9 / Qt 5.15.18. A full QGIS 4 installation was not
available for this port. QGIS 4, older QGIS 3 releases, Windows and Linux need
runtime acceptance tests before a stable public compatibility claim.

## Running the tests

Run with the Python supplied by each actual QGIS version, not the system Python:

```sh
python -B tests/smoke_qgis.py
python -B tests/regression_interface.py
python -B tests/regression_scoring.py
```

For headless Linux, set `QT_QPA_PLATFORM=offscreen`. On Windows run from the
OSGeo4W Shell for the selected QGIS installation. The tests create disposable
synthetic fixtures and a temporary profile, and use localhost for network checks.

Separately, with PyQt6 in an isolated Python environment:

```sh
QT_QPA_PLATFORM=offscreen python -B tests/qt6_widgets.py
```

PyQt6 is a **test dependency only**. Do not install it into a QGIS 3 / Qt 5 Python
installation. End users need only the Python/Qt libraries bundled with QGIS.

## Interactive QGIS 4 acceptance

Install dist/geolichen-15.6.31.zip in a separate QGIS 4 profile. Use a copy of your
own records and layers; do not overwrite the original dataset during evaluation.

1. Open the dock, expand configuration, map input fields and select one record.
2. Search and select a locality; also try manual point and manual line buffers.
3. Check DEM sampling, grid spacing, candidate rendering and Suitability Surface
   at different zoom levels, with and without optional environmental layers.
4. Complete the guided candidate flow: Avanti, map selection, Riprova, Sì,
   candidate editor; also verify Cancel, Esci, Escape and right-click.
5. Save a centroid; check coordinates, elevation and source CRS handling.
6. On a disposable table, create missing output columns and complete automatic
   analysis. Check rank 1 visibility and saved attributes.
7. Copy a confirmed point to multiple explicitly selected rows. Check that
   filtered-out rows and unselected records are unchanged.
8. Export confirmed points to GeoPackage, save/reopen the project, then verify
   field mappings and output data. Try report export and plugin unload/reload.

## Official migration references

- https://plugins.qgis.org/docs/migrate-qgis4
- https://github.com/qgis/QGIS/wiki/Plugin-migration-to-be-compatible-with-Qt5-and-Qt6

The current repository uses the declared QGIS version range. The historical
`supportsQt6` flag is obsolete and is not used.


## Release 15.6.31 status — 16 November 2026

| Environment | Evidence | Status |
| --- | --- | --- |
| macOS, QGIS 3.44.9 / Qt 5 | Local full regression report, see VERIFICATION.md | Local runtime verification |
| Linux, QGIS 3.40.15 / Qt 5 | Pinned official image and full CI job prepared | Not yet executed |
| Linux, QGIS 4.2.3 / Qt 6 | Pinned official image and full CI job prepared | Not yet executed |
| Windows, QGIS 3.40 | Suite runner available from OSGeo4W Shell | Current release not yet tested |
| Windows/macOS, QGIS 4 | Same suite runner plus interactive checklist above | Not yet tested |
| Other declared QGIS 3 versions | Metadata allows installation | Not verified for this release |

No Docker runtime or complete QGIS 4 installation is available on this workstation.
Prepared CI jobs are not compatibility evidence until they have actually passed.
No platform claim is upgraded based on the template alone. Metadata retains the
existing experimental range; stability and publication still require acceptance.
Use `tools/run_checks.py --expect-qgis MAJOR.MINOR` for a recorded check in each
runtime. See DEVELOPMENT.md for Windows commands and distribution procedure.


## 15.6.32 — first successful public CI (16 November 2026)

The complete GitHub workflow passed after two corrections: the candidate dialog
uses Qt.TextFormat.RichText, and the snap test accepts the spatial index's
documented equidistant neighbors instead of assuming an absolute eight-ID cap.
Production snapping, ecological scoring and uncertainty formulas are unchanged.

| Environment | Evidence | Status |
| --- | --- | --- |
| macOS, QGIS 3.44.9 / Qt 5 | dist/checks-15.6.32.json, all eight suites | Passed locally |
| Linux, QGIS 3.40.15 / Qt 5 | Official pinned image, full workflow | Passed online |
| Linux, QGIS 4.2.3 / Qt 6 | Official pinned image, full workflow | Passed online |
| Package preparation | Source checks plus both QGIS jobs | Passed online |
| Windows, QGIS 3.40 or 4 | Full runner and interactive checklist available | Pending |
| Interactive desktop acceptance on QGIS 4 | Checklist above | Pending |

[Successful workflow for commit 587caf2](https://github.com/LucaGrazia0/geolichens/actions/runs/43898848525).
These headless runtime checks do not replace Windows or interactive acceptance,
nor do they validate public server availability or scientific accuracy.
