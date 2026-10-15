# GeoLichen

GeoLichen is a QGIS plugin for ecologically assisted georeferencing of historical
lichen records. It interprets locality descriptions, ranks candidate points
using ecological and environmental information, and supports expert review,
manual refinement, uncertainty estimates and provenance reporting.

The interface is in Italian. Locality interpretation and ITALIC profiles target
Italy; the default search area is Lombardy. Optional local dictionaries and taxon
indexes are not bundled. Other regions are selectable, but performance outside the intended
geographical and linguistic scope has not been established.

This release is experimental. Candidate scores, confidence indicators and
uncertainty radii are model estimates and require expert validation before use
as published occurrence coordinates.

## Requirements

- QGIS 3.22–3.99 with its Python environment, NumPy and GDAL/OGR (`osgeo`).
  These libraries normally ship with QGIS desktop installers. No additional
  pip packages or other QGIS plugins are required. If an import is missing,
  repair the QGIS installation (on Windows, use the QGIS/OSGeo4W installer).
- Internet access for live ITALIC profiles and OpenStreetMap/Overpass requests.
- A personal MapTiler API key for automatic geocoding. Create a key in your
  [MapTiler account](https://cloud.maptiler.com/), enter it in the configuration
  panel and observe the service's usage limits and terms.
- Environmental vector layers and DEM rasters for the corresponding ecological
  and terrain analyses. These are supplied by the user, with suitable coverage,
  coordinate reference systems and attributes; they are not included.

QGIS 4/Qt 6 compatibility is not declared. Windows and Linux still require
interactive release testing; see [publication notes](docs/PUBLISHING.md).

## Installation

1. Download or build a GeoLichen release ZIP, with a single `geolichen/` folder
   containing `metadata.txt` and `__init__.py`.
2. In QGIS open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the ZIP, install and enable **GeoLichen**.
4. Open **Vector → GeoLichen**. A toolbar action is also available.

For development, open **Settings → User Profiles → Open Active Profile Folder**
and place this source folder at `python/plugins/geolichen`, then restart QGIS.
This avoids relying on platform-specific profile paths.

## Quick start

1. Load your own records as a vector layer or a table. CSV input can be loaded
   using **Layer → Add Layer → Add Delimited Text Layer**, choosing **No geometry**
   for a table without coordinates. No dataset is included in this release.
2. Make that layer active and open GeoLichen. Click **Configura campi input**.
   Map `scientific_name` and at least one of `municipality` or `locality`.
   Record ID, substrate, rock, tree, elevation and notes are optional.
3. Enter your MapTiler key and select the appropriate search area. Load and select relevant geology, soil, vegetation and DEM layers
   when available, and associate the relevant attribute fields in the panel.
4. Select one record and click **Analizza record selezionato**. Review the
   interpreted locality, search geometry, ITALIC information and candidates.
   Missing data or unavailable services can limit results; inspect diagnostics.
5. Inspect candidate locations on the map and use the manual point/buffer or
   line tools when documentary evidence needs correction. Confirm only after
   reviewing the available evidence using **Conferma punto ecologico**.
6. Review coordinate, uncertainty and provenance fields in the confirmation
   dialog before writing results. Save your QGIS project and output layers.
   Use a copy of your input data during evaluation.

Validation, benchmark, performance and release checks are available in the
**Vector → GeoLichen** menu. Benchmarks consume user-provided reference
coordinates; no reference dataset is distributed.

## Network requests and local storage

ITALIC receives queried taxon names. MapTiler receives locality search strings,
the search bounding box/proximity and your API key. Overpass receives geometry
queries for the selected area. Requests occur during the corresponding analyses;
ensure the data can be sent to those services. The plugin uses QGIS networking
for runtime requests and therefore uses QGIS proxy and TLS settings.

ITALIC caches and snapshots are written to `geolichen/` inside the active QGIS
profile folder. They are local working data and are excluded from source
distribution. Existing `italic_cache.json` and `italic_snapshots.json` from older
installations are left untouched; copy them to the new profile subfolder manually
if you need them, with QGIS closed. Keep a backup of reproducibility snapshots.

## Source, issues and release building

Source code is hosted at [LucaGrazia0/geolichens](https://github.com/LucaGrazia0/geolichens).
Report problems through [GitHub Issues](https://github.com/LucaGrazia0/geolichens/issues).

```sh
python3 tools/build_release.py --preview
python3 tools/build_release.py
```

Preview packages are for local testing and may contain incomplete metadata.
The normal build rejects missing repository links and writes an upload ZIP
under `dist/`, with a SHA-256 manifest. It excludes caches, bytecode, hidden files,
compiled libraries, all datasets and old development notes. Do not commit ZIPs to the source
repository. Publish release artifacts separately after the provenance checks in
[PUBLISHING.md](docs/PUBLISHING.md) are resolved.

## License and attribution

The source-code release license is **GNU GPL version 2 or later**;
the full text is in [LICENSE](LICENSE). Datasets, regional dictionaries, taxon
indexes, cached responses and user snapshots are excluded from both the public
repository and release ZIP. The plugin uses built-in rules and live services
when optional local dictionaries are absent; region-specific aliases, dictionary
classifications and the local taxon index are then unavailable. The GPL declaration
does not relicense third-party data. See [THIRD_PARTY.md](THIRD_PARTY.md) for
sources, external services and the unresolved provenance details.
