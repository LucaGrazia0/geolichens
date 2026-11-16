# Contributing to GeoLichen

Read [development and release checks](docs/DEVELOPMENT.md).
Run the existing regressions before changing candidate selection, ecological
scores, uncertainty, geometry or table writes. Include a synthetic reproduction
for a bug; do not commit specimen tables, environmental layers, caches, API keys,
ZIP archives or generated files. Development dependencies are separate from QGIS
runtime requirements. Use the Python supplied with QGIS for GIS tests.

Keep changes small. Preserve formulas and existing field compatibility unless a
model change is explicitly justified and documented. Report actual test runtimes;
prepared CI configuration is not a successful compatibility test.
