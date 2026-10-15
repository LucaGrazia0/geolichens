# Dependencies and external services

GeoLichen source code is released under GPL-2.0-or-later (see LICENSE).
The source imports Python's standard library, QGIS/PyQt, NumPy and GDAL/OGR.
These dependencies are supplied by QGIS and retain their own licenses; no
third-party library or compiled extension is vendored in this repository.

## ITALIC

[ITALIC — The information system on Italian lichens](https://italic.units.it/)
is an external resource from the University of Trieste. The plugin queries
its v2 API and taxon pages at runtime. Responses retain their original rights.
No ITALIC dataset, local taxon index, cached response or image is distributed.
The developer tool `tools/build_italic_index.py` can optionally build a private
local index; it is not run during installation or startup. Its generated data
are ignored by Git and excluded by the release builder. Verify the applicable
terms before using or redistributing external data.

## Other services and user data

- [OpenStreetMap contributors](https://www.openstreetmap.org/copyright): data
  accessed through Overpass; observe ODbL and attribution requirements when
  distributing derived datasets. No downloaded OSM dataset is bundled.
- [MapTiler](https://www.maptiler.com/): automatic geocoding requires the user's
  key/account and is subject to the provider's terms and quotas. No key or
  downloaded MapTiler dataset is included.
- Specimen records, regional dictionaries, environmental layers and DEMs are
  supplied privately by the user and retain their own licenses. They are not
  included in the public source repository or release ZIP.

The repository contains plugin source, documentation, license and developer
scripts only. Test scripts generate disposable artificial input at runtime.
