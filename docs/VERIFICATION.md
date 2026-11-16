# Release verification - 12 November 2026

## GeoLichen 15.6.30: Photon timeout and cached recovery

- Clean-export QGIS 3.44.9/macOS: 38 OSM/geocoding, 35 locality-search and 100
  interface regressions passed (173). Checks cover bounded request waiting,
  shared deadline, valid cache use after town failure, cached deeper variants,
  request counts and endpoint/bbox/TTL isolation.
- The exact 15.6.28/15.6.29 release ZIP comparison found identical geocoder,
  name helper, endpoint configuration and transport except User-Agent version.
- Live 15.6.29 QGIS lookup of Ponte di Legno timed out in 12.04 s; a direct
  HTTP request returned 200 in 29.576 s. Corrected QGIS lookup returned ten
  candidates in 30.4 s. Public service availability/latency remain external.
- Full local-HTTP import/lifecycle/transport smoke passed with zero outstanding
  release-readiness checks. The first attempt could not run because automatic
  authorization review hit an account usage limit; after authorization became
  available again, the retry completed successfully.
- A fresh municipality-plus-locality live test exhausted the intermediate
  45-second shared budget in 45.02 s. The final shared budget is 80 seconds,
  allowing two slow 35-second requests while preserving per-request bounds.
- With the final 80-second budget, the fresh Vione/Monte Pornina full lookup
  still failed after 68.71 s: the town lookup completed, but the locality reply
  exceeded the 35-second per-request bound. Therefore public online lookup is
  NOT claimed restored reliably. The client recovery and limits are tested;
  server availability remains unresolved. No further live retries were issued.
- Name filters, ecological scores, buffers and archive data remain unchanged.
  Full QGIS4 and Windows runtime validation remain pending.

## GeoLichen 15.6.29: hover preview, empty results and data study

- Clean-export QGIS 3.44.9/macOS: **100/100 interface**, **32/32 analysis** and
  **23/23 scoring** regressions passed (155). New checks compare the selected
  hover radius against candidate confirmation, verify immediate coordinates,
  debounce/cached model-only calculation, cancellation/deselection cleanup,
  explicit empty-result alerts and removal of stale analysis outputs.
- Full QGIS import/lifecycle/local HTTP smoke passed with zero release-readiness
  findings. No live geocoder or Overpass was needed for these checks.
- Model radius remains R55-S65, not Darwin Core coordinate uncertainty. Scores,
  sample grids and uncertainty formulas are unchanged. Widget preview rendered
  at 420 px; full QGIS4 and Windows runtime acceptance remain pending.
- Lossless data study compared every DEM pixel and all forest features/fields/
  WKB geometries. One 100,440,858-byte Float32 DEM became 55,595,918 bytes;
  315,720 forest features became a 392,577,024-byte indexed GeoPackage from
  556,231,715 bytes of Shapefile components. DEFLATE stream sizes: 55,605,701
  and 213,529,166 bytes respectively (not a full regional starter package).
- Data copies/benchmarks stay under output/ and are excluded from plugin release
  and Git. The user chose whole-Lombardy coverage; the four available 10 m DEM
  tiles do not cover the region completely. Document inventory/licensing/preset
  work required before assembling and distributing the regional starter.

## GeoLichen 15.6.28: targeted locality exploration

- QGIS 3.44.9/macOS clean export: **35/35 locality-search**, **33/33
  OSM/geocoding** and **95/95 interface** regressions passed. Standalone real
  Qt6 widgets: **8/8 passed**. Total for this change: 171 checks.
- New tests cover continued quick lookup after a partial name, exact-name
  early stopping, shared parser/record work, conservative search-only variants,
  lexical coverage preceding context, structured municipal conflicts, strict
  map-area intersection and filtering, no broadening after empty map results,
  preservation of earlier choices and capture of the extent before previews.
- Map CRS errors hide the optional map action without blocking normal locality
  selection. Qt5/Qt6 checks exercise the new button and retry state.
- Full QGIS import/lifecycle/local HTTP smoke passed with 112 runtime modules
  and zero outstanding release-readiness checks. Existing circular buffer and
  trail clipping regressions passed. Ecological scoring formulas are unchanged.
- Live Photon: Foppe di Braone with Braone collected 12 partial-name candidates
  using four network requests in 16.128 s. A test rectangle
  (10.38,45.95,10.43,45.99) yielded Malga Foppe di Sotto only, in 13.166 s with
  a reduced three-request budget; reaching that budget was reported explicitly.
  The exact requested name remains unresolved and no substitute was endorsed.
  This is one availability/coverage example, not an accuracy or speed guarantee.
  Local QA report: `output/locality_search_15_6_28/foppe-live.json`.
- No additional geocoder or Overpass requests were introduced for ecological
  ranking. Cache and public-service request spacing/caps are retained. Full
  QGIS4 and Windows runtime validation remain pending.

## GeoLichen 15.6.27: generic locality-name matching

- QGIS 3.44.9/macOS: **25/25 locality-search**, **33/33 OSM/geocoding**
  and **93/93 interface** checks passed from the clean export. Real standalone
  PyQt6/Qt 6.12 widgets: **7/7 passed**. Total rerun for this correction: 158.
- New regressions cover municipality-only false matches for Foppe di Braone,
  retained partial/typo alternatives, exact-name warnings, empty raw results
  after filtering, no silent municipality fallback for a distinct locality,
  supported municipality-only searches, visible warnings before confirmation
  and omission of the recommendation mark on partial names.
- Full QGIS import/lifecycle/local-HTTP smoke passed with 112 runtime modules
  and zero release-readiness findings. No ecological formula or trail transport
  change is introduced; their existing wider test results are recorded below.
- Live Photon on 29 October: Foppe di Braone with municipality Braone used two
  requests in 2.230 s. It returned Foppe (Cerveno), Malga Foppe di Sotto (Ceto)
  and Foppe di Palot (Pisogne). Municipio di Braone and unrelated local names
  were excluded. None is an exact full-name match; all require geographic
  review, and no equivalence to the requested locality is asserted. Report:
  `output/locality_search_15_6_27/foppe-live.json` (local QA, not in the ZIP).
- Existing explicitly confirmed aliases are preserved. Exact spelling still
  does not prove correct geography. Windows and full QGIS4 runtime acceptance
  remain pending; no claim of exhaustive OSM toponym coverage is made.

## GeoLichen 15.6.26: deeper locality lookup and confirmed anchors

- QGIS 3.44.9/macOS: **18/18 locality-search**, **33/33 OSM/geocoding**,
  **92/92 interface**, **32/32 analysis**, **23/23 scoring** checks passed.
  Standalone real PyQt6/Qt 6.12 widgets: **7/7 passed**. Total: 205.
- Fixtures verify continued lookup after a successful variant, network request
  caps, deduplication, unrelated fuzzy-name filtering, conservative abbreviations
  shared with semantic parsing and preservation of old results on network failure.
- Municipal checks distinguish polygon holes/edges from rectangle membership,
  transform CRS, observe edited geometries, keep external alternatives and prefer
  actual membership over proximity to a distant town center. The source is a
  user-selected polygon/name-field layer; no administrative dataset is bundled.
- Archive checks reopen anchors offline, scope names/aliases to municipality
  and search area, preserve unreadable files, update/remove selected entries,
  exclude ecological outputs and retain moved OSM source positions separately.
  Controller tests confirm that explicit selection precedes buffer creation,
  recovery works after an empty lookup and cancellation does not save an anchor.
- Main dock remains usable at 420 px without horizontal scrolling. New dialogs
  were rendered and inspected. An obsolete failure-path test was updated to
  cancel the newly available retry dialog instead of waiting in its modal loop.
- Full import/lifecycle/HTTP smoke passed with 112 runtime modules and isolated
  profile, real local POST/delayed reply/error/cancellation/download/cache checks,
  and zero release-readiness findings. No live services are needed for that suite.
- Live Photon: `M.te Pornina` returns five related-name alternatives, topped by
  Monte Pornina. The deeper action with Vione retained five alternatives, used
  four network requests (a deliberately reduced test budget) and reported reaching
  its cap; total initial plus deeper test 5.038 s. The final name filter excludes
  earlier irrelevant fuzzy hits such as Palazzo Te. This is a functional example,
  not an accuracy study or a guaranteed response time/result count.
- Existing circular buffers and ecological formulas are retained; locality
  ordering/type interpretation can change the selected geography and hence the
  resulting ecological candidates. No new Overpass transport behavior is added.
- ZIP contains code/docs/tests only. Windows and complete QGIS4 runtime testing
  remain pending. See [user workflow and limits](LOCALITY_SEARCH_15_6_26.md).

## GeoLichen 15.6.25: circular locality buffers and network waiting

- QGIS 3.44.9/macOS: **33/33 OSM/geocoding**, **89/89 interface** regressions
  passed from the clean export. Existing analysis **32/32**, scoring **23/23**
  and standalone real-PyQt6 widgets **6/6** also passed (183 total).
- Circle tests cover lakes, forests, valleys, passes, summits, mountains,
  rivers, municipalities, refuges, trails and generic localities. Verify every
  vertex's metric distance, selected center, independent documentary geometry
  and skipped unused OSM geometry lookup. Recognize laghetto/laghetti explicitly.
- Smoke passed: 108 runtime imports, plugin/dialog lifecycle, HTTP POST and
  refusal handling, bounded cancellation, a delayed local response arriving
  beyond the previous cutoff, actual download/clip/cache and release readiness.
- Preserve a 25 s server execution budget; trail network wait is now 60 s per
  endpoint, maximum two endpoints. Give the inactivity abort a 1 s margin
  after the total watchdog and inspect the underlying reply's network error.
- The 15.6.19 ZIP and current trail `build_query` have identical ASTs. Both use
  Overpass POST; MapTiler provided geocoding. The current exact-buffer clipping
  and categorized rendering are later changes, not a new trail data provider.
- Live test on the Laghetto d'Avio circle still failed: HTTP 502 on the primary,
  60 s timeout on the secondary (61.236 s overall). This is not a successful
  fresh trail download. Historical local OSM data clipped to the circle retains
  one path segment to the east and four track segments; rendering inspected.
  Historical data were not silently substituted for a fresh production download.
- ZIP excludes datasets/cache. No permanent area archive is added. Full Windows
  and QGIS4 validation remain pending. See [buffer and network notes](CIRCULAR_BUFFERS_15_6_25.md).

## GeoLichen 15.6.24: OSM route types and persistent diagnostics

- macOS/QGIS 3.44.9: **26/26 OSM/geocoding**, **89/89 interface**, **32/32 analysis**,
  **23/23 scoring** regressions passed from a clean export; real-PyQt6 widgets
  **6/6 passed**. Total: 176 checks in these suites.
- Smoke passed: 108 runtime modules, local HTTP transport, POST identification,
  refusal cooldowns, actual fixture download/clip/cache, lifecycle and release
  readiness (zero outstanding checks). A stalled local Overpass POST is canceled
  at the total deadline rather than waiting for the global network timeout.
- Categories/colors and summary counts distinguish paths, tracks and access
  roads. Notices persist through candidate hover/status changes and clear with
  the buffer. Partial/malformed cached responses are rejected.
- Live exact-name Photon lookup for Monte Pornina returned one candidate.
  Existing local OSM response, clipped to a 1 km reference buffer, contains
  seven path segments and two track segments; rendering was visually checked.
- Fresh live Overpass remains unavailable in these probes: GET on the primary
  returned HTTP 502/capacity exhaustion; the secondary timed out. One bounded
  QGIS POST run ended after 10.016 s with two 5 s deadline cancellations and
  no payload. Local/cache success does not establish live-server availability.
- No score/geocoding/uncertainty formula changes from 15.6.23. ZIP and source
  integrity checked; no datasets/cache included. Full Windows/QGIS4 validation
  remains pending. See [OSM and uncertainty notes](OSM_TRAILS_15_6_24.md).

## GeoLichen 15.6.23: score corrections and exact optimizations

- macOS 26.6 / QGIS 3.44.9 / Python 3.12.11: **32/32 analysis**, **23/23 scoring**,
  **89/89 interface**, **21/21 OSM/geocoding** regressions passed. Standalone
  real-PyQt6 widget checks: **6/6 passed** (171 checks in these suites).
- Loading/network/lifecycle smoke passed: 108 runtime modules imported, temporary
  profile, local HTTP success/error/timeout, Photon request shape, Overpass POST,
  actual fixture download/clipping/cache and clean unload. Release readiness
  reports zero outstanding checks; this is not approval from the QGIS catalog.
- Added coverage for locality context propagation/reset, canonical summit types,
  independent geographic/accessibility effects, measured low accessibility,
  zero-distance and explicit non-legacy ties, gradual single/range altitude,
  flat DEM aspect, chemistry versus support and forest-host mismatch provenance.
- Exact optimization comparisons cover scores, ranks, evidence, uncertainty,
  generated point attributes and raster pixels; 60 additional deterministic SSI
  cases include compact/dispersed/multiple clusters. Verify 5 instead of 9 samples
  for one DEM, multi-DEM fallback, early altitude filtering, per-grid invariants,
  forest cache invalidation after edits and uncertainty only on the final grid.
- Synthetic benchmark: 300 candidates plus point/surface creation 1.330 s full
  versus 0.476 s optimized. SSI with 800 compact candidates 9.261 s versus 0.00263 s;
  dispersed case 9.406 s versus 1.576 s. Compared outputs identical. These fixtures
  exclude network/canvas rendering and do not measure Windows project performance.
- Correct the smoke test's hard-coded old version by checking against package
  metadata. ZIP/source syntax, CRC and SHA256 correspondence validated.
- Model corrections intentionally may change GSS/rank/selected point relative to
  15.6.22. Macro weights stay 25% each; future ecological calibration needs
  independent known-coordinate records. See [full revision](SCORING_15_6_23.md).
- Full QGIS 4 and Windows 3.40 remain unverified. Public Overpass live availability
  was not retested; the previously recorded live failures remain unresolved.

## GeoLichen 15.6.22: locality confirmation before buffer creation

- macOS/QGIS 3.44.9 interface regressions: **89/89 passed** from a clean release
  export. Added single-result confirmation, cancelling that result, selection of
  a non-first result and accepted-without-selection rejection. In each case the
  boundary builder remains uncalled until the dialog supplies a valid selection.
- Standalone Qt6 widget checks: **6/6 passed**, including actual modal event-loop
  tests which click "Crea buffer" for one/multiple candidates and "Annulla".
- Runtime smoke checks passed: imports (108 modules), plugin/dialog lifecycle,
  local HTTP/error/timeout handling, Photon requests and downloaded trail clipping.
- Map previews clear when the selection dialog closes. The automatic ecological
  workflow retains the initial locality review; ecological formulas unchanged.
- No live service behavior was changed or retested. The previously recorded
  Overpass live failures and Windows/full-QGIS4 validation limits remain open.
- Release syntax, ZIP integrity and source hashes validated; no datasets bundled.

## GeoLichen 15.6.21: trails clipped to the current buffer

- QGIS 3.44.9 / Qt5, macOS: **85/85 interface**, **21/21 OSM/geocoding**,
  and **23/23 scoring** regressions passed from a clean source export.
- Standalone Qt6 widget checks: **5/5 passed**; full QGIS4 and Windows remain
  unverified.
- The real local HTTP fixture downloads a way with QGIS networking, clips it to
  the buffer, creates the line layer and reuses the cached raw response.
- Added coverage for a circle versus its bounding rectangle, polygon holes and
  split segments with retained OSM IDs, same-envelope/different-shape cached
  responses, corrupt coordinates, current manual corridors, temporary-layer
  invalidation and disabling OSM with a previously checked temporary layer.
- The remaining lifecycle/smoke checks passed, including import of 108 modules
  and HTTP identification, error handling and timeouts.
- An additional small live Overpass request using HTTP/1.1 still timed out without
  receiving a response. **Live public-server trail download remains unverified**;
  local fixture success does not establish public service availability.
- Score formulas unchanged. Source/ZIP integrity checked; no user data bundled.

## GeoLichen 15.6.20: Photon / OpenStreetMap migration

- Environment: macOS, QGIS 3.44.9 / Qt 5.15.18 / Python 3.12.11.
- Interface regression: **82/82 passed**, including Photon-to-grid integration,
  usable/checked accessibility layers, OSM trail use by the actual distance
  engine, stale-layer removal on failure, and preservation of the existing
  selection, confirmation, centroid, manual, automatic, copying and heatmap flows.
- OSM/geocoding regression: **17/17 passed**. Covers response normalization,
  bbox/proximity, explicit area expansion, natural-feature/road discrimination,
  persistent cache, request budget/throttle, malformed data/timeouts, polygon
  resolution, line attributes, Overpass error remarks and shared cooldowns.
- Scoring regression: **23/23 passed**. Ecological formulas and weights unchanged.
- Smoke test passed: **108 runtime modules**, dock/dialog lifecycle, clean-profile
  storage, CSV mapping, local HTTP success/error/timeout, Photon without an API
  key, and actual QGIS POST transport against a local Overpass fixture (including
  HTTP 429). Real local requests verify that the application User-Agent survives
  QGIS's header replacement and that later unrelated requests are unaffected.
- Standalone PyQt6 / Qt6 widget checks: **5/5 passed**; not a full QGIS 4 test.
- Live QGIS network search passed for Edolo (46.1806346, 10.3332567) and
  Passo di Crocedomini, Breno (45.9075303, 10.4095085). Repeating Edolo used zero
  network requests. These are illustrative searches, not an accuracy benchmark.
- **Live Overpass trail download did not succeed**: both public endpoints
  returned empty responses/timeouts for a small test area. An independent GET
  also timed out. This remains an external integration limitation; passing
  synthetic/local tests does not establish live service availability.
- Source/ZIP syntax, CRC, per-file hashes and size validated. No private datasets
  or response caches are distributed. See OSM_MIGRATION_15_6_20.md.

Windows/QGIS 3.40, Linux and full QGIS 4 acceptance remain unverified. No claim
is made that the reported Windows ecological-analysis runtime has improved.

## GeoLichen 15.6.19: QGIS 3 / Qt 6 port

- QGIS runtime: macOS, QGIS 3.44.9-Solothurn, Qt 5.15.18, Python 3.12.11.
- Smoke test passed: 105 runtime modules, five Plugin menu actions, main dock,
  four auxiliary dialogs, unload, temporary CSV mapping, per-profile cache,
  missing-dictionary fallback, local HTTP success/403/timeout and MapTiler
  request/error handling. Release-readiness report: zero blocking checks.
- Interface regression: **78/78 passed** using the clean release source export,
  without user datasets or optional dictionaries. Covers source-row selection,
  record switching, guided/manual/automatic analysis, centroid, DEM fallback,
  grid policy, display resampling, column creation, GeoPackage persistence,
  multiple destination copying, CRS transforms, cancellation and reloads.
- Scoring regression: **23/23 passed** on synthetic evidence fixtures.
- Standalone Qt 6: **5/5 passed** with real PyQt 6.11.0 / Qt 6.11.2 in an isolated
  temporary Python environment. Exercises the dock/disclosures, guided dialogs,
  cancel/use/retry, five other independent dialogs, scoped-enum spelling audit,
  and numeric decoding of Python enums. This bridges the qgis.PyQt namespace only;
  it is not a QGIS 4 runtime or GIS-provider test.
- Generated test screenshots now use disposable temporary directories, avoiding
  overwriting earlier previews. Python tests were run with a temporary
  PYTHONPYCACHEPREFIX to avoid stale cloud-only bytecode files.
- The release builder validates source syntax, ZIP CRC, package size and every
  archived file hash. Datasets and binaries remain excluded.

**Outstanding:** run all three QGIS test scripts and the interactive acceptance
flow in a real QGIS 4 installation. Windows/Linux and older QGIS 3 versions also
remain unverified. Metadata permits QGIS 4 installation as an experimental port;
this is not a stable/certified compatibility claim. See QGIS4_COMPATIBILITY.md.

The ecological score formulas/weights and uncertainty calculations were not
changed by this compatibility port. Existing scientific-validation limitations
continue to apply.

## Historical checks - 15 October 2026


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


## 15.6.31 — development workflow and diagnostics (16 November 2026)

Baseline saved in local commit ba40402 (15.6.30). Full verification via
`tools/prepare_release.py` passed on macOS 26.6 arm64, QGIS 3.44.9-Solothurn,
Qt 5.15.18, Python 3.12.11. Reports and individual logs are in
`dist/checks-15.6.31.json` and adjacent files (local artifacts, not public datasets).

- Release artifact safety: 3 tests (data/cache exclusion, reproducibility,
  symlink rejection and failure preventing packaging).
- Scoring: 23; spatial/ecological analysis: 32; OSM geocoding: 38;
  locality search: 35; interface/selection/confirmation/copy: 100;
  diagnostics/cache/TLS failure handling: 6. Total: 237 regression tests.
- QGIS smoke: all module imports, plugin lifecycle, isolated profile storage,
  local HTTP success/errors/deadlines and Overpass behavior passed.
- Focused Ruff correctness scan passed; pre-commit configuration validated;
  workflow YAML parsed. No formatting rewrite was performed.
- Ruff found an undefined `radius_m` in an unreachable manual-corridor block
  inside automatic locality analysis (`is_manual_line` is always false there).
  Remove that residual block; active manual corridor handling remains covered
  by interface regressions. No scoring or uncertainty service file changed.
- ITALIC diagnostics now use the scoped QGIS logger, without raw profile dumps.
  TLS failures still raise and never call ignoreSslErrors. Fresh and expired
  cache recovery is verified; public server availability is not tested here.
- Prepared Linux CI jobs use official QGIS 3.40.15 and 4.2.3 images pinned by
  digest. They have not run. No Docker, Windows or complete QGIS 4 runtime is
  available locally. Windows/Linux/QGIS 4 acceptance remains pending.

The initial smoke attempt was prevented by local server socket permissions;
repeating the complete preparation with the required permission passed.
No TLS exceptions, datasets, user project attributes or cache contents changed.
The manual now documents 15.6.31; older PDFs have not been regenerated.


## 15.6.32 — public CI enabled and validated (16 November 2026)

Public source was synchronized without importing local Git history or datasets.
All 161 public files matched the expected Git blob hashes before updating main.
The first run exposed a real Qt 6 integer text-format error in the candidate
editor and an incorrect test assumption about equidistant spatial-index IDs.
Both were corrected, retaining the full test coverage and selection behavior.

Local full preparation passed on macOS/QGIS 3.44.9 (237 regressions plus smoke).
The complete public run then passed source checks, QGIS 3.40.15 / Qt 5,
QGIS 4.2.3 / Qt 6 and gated packaging on Linux:
https://github.com/LucaGrazia0/geolichens/actions/runs/43898848525

The runtime correction is limited to Qt.TextFormat.RichText. No ecological
formula or uncertainty threshold changed. Windows and full interactive QGIS 4
acceptance remain pending; no external API availability guarantee is implied.
