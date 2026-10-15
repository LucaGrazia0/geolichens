# Release verification — 15 October 2026

Environment: macOS; QGIS 3.44.9-Solothurn; QGIS Python 3.12.11.

Automated smoke test: `tests/smoke_qgis.py`, run using the installed QGIS
Python with the offscreen Qt platform, temporary local data/settings and a
localhost HTTP fixture. No real API key or external data service was used.

Passed:

- Import all 96 runtime modules under core, controllers, models, gui and services.
- Initialize five Vector menu actions and the toolbar action.
- Open the main dock and instantiate its controller.
- Open validation, benchmark, performance and release-readiness dialogs.
- Unload and remove registered menu/toolbar actions.
- Create ITALIC cache/snapshots in writable per-profile storage.
- Perform a QGIS HTTP request and parse ITALIC JSON using a local response.
- Propagate HTTP 403 without including secret query parameters in the error.
- Cancel a delayed response at the per-request timeout.
- Build MapTiler requests and handle HTTP errors without an external account.
- Generate a disposable artificial CSV at runtime, load it through QGIS and
  suggest valid field mapping. No test dataset is published.
- Verify fallback loading when optional dictionaries and the taxon index are absent.

The release builder compiles Python in memory, parses JSON, limits compressed
and uncompressed size to 25 MB, verifies ZIP CRC and compares SHA-256 hashes of
every archived file with the source payload. It uses a fixed allowlist, a single
`geolichen/` ZIP root, fixed timestamps and file permissions. Exact package size
and hashes are recorded beside the ZIP in `dist/*.manifest.json`.

Not established: Windows/Linux compatibility; all older QGIS versions down to
3.22; QGIS 4/Qt 6; external proxy/SSL configurations; authenticated live MapTiler
requests; live ITALIC/Overpass availability; end-to-end confirmation and saving on
real specimen/environmental layers; scientific accuracy or calibration of
uncertainty estimates. These need interactive/user-data testing.

Dataset files and old local history are excluded from publication. The public
release is tested from its clean source export, without optional dictionaries
or a local taxon index.
