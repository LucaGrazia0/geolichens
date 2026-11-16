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
- [Photon](https://github.com/komoot/photon) is queried as an external OSM-based
  geocoding service; no Photon server code or dataset is bundled. Its public
  [demo](https://photon.komoot.io/) is for moderate use without availability
  guarantees. The URL is configurable for an appropriate private/self-hosted service.
  [Overpass](https://overpass-api.de/) and [Private.coffee Overpass](https://overpass.private.coffee/)
  provide OSM geometries, subject to availability and fair-use policies.
  Requests identify GeoLichen. The public Nominatim endpoint is not used.
- Specimen records, regional dictionaries, environmental layers and DEMs are
  supplied privately by the user and retain their own licenses. They are not
  included in the public source repository or release ZIP.

## Interface image

`gui/icons/locality_centroid.png` is the image supplied by the project owner for
the locality-centroid action. The original PNG is embedded unchanged as a UI
asset. It is not an environmental or specimen dataset. The original creator
and asset license have not been independently documented; the project owner
must confirm distribution rights before QGIS catalogue submission.

The repository contains plugin source, documentation, the interface image,
license and developer scripts. Test scripts generate disposable artificial
input at runtime.
