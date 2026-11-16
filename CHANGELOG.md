# Changelog

## 15.6.33 - Overpass outage recovery and phase timings

- Preserve the 24-hour fresh trail cache. After download failure, recover only an identical-query, complete archive no older than 30 days; label its age and failure, clip it again to the current buffer and preserve its original modification time.
- Suppress repeated failed requests for the identical cache key for 60 seconds across service instances; preserve fresh-cache precedence, existing refusal handling and retry after expiry. No server bypass or extra endpoint is added.
- Record separate download_sentieri_osm and calcolo_ecologico phase timings, including failed runs, in the existing performance dialog. Propagate archive warnings into the ecological result notice.
- Leave scoring, uncertainty and altitude filters unchanged. New downloads still depend on Overpass availability; no partial response becomes a trail dataset.

## 15.6.32 - First public CI compatibility corrections

- Activate source-only GitHub CI after synchronizing the public repository.
- Replace integer text format in the candidate dialog with Qt.TextFormat.RichText; Qt 6 rejected the integer and prevented candidate confirmation.
- Correct the indexed-snap regression: QgsSpatialIndex may return more than eight IDs when neighbors tie. Assert the actual shortlist is measured and still excludes the full grid, preserving production selection behavior.
- Preserve scoring, uncertainty, request policies and all datasets.

## 15.6.31 - Verified development and distribution workflow

- Preserve the 15.6.30 baseline in local commit ba40402.
- Add a cross-platform QGIS suite runner, fail-closed release preparation, source checks, focused Ruff checks and optional pre-commit hooks.
- Prepare read-only GitHub Actions checks for pinned official QGIS 3.40 and 4.2 images; package only after successful checks. No automatic publication.
- Centralize sanitized QGIS diagnostics and expose an opt-in detail setting in the performance dialog. Preserve TLS validation, service failure behavior, ecological formulas and candidate workflows.
- Update the user manual for Photon/OSM, circular buffers, current uncertainty labels, previews and cache/error behavior. Document actual compatibility evidence separately from pending acceptance tests.

## 15.6.30 - Slow geocoder responses and offline cache recovery

- Increase Photon request waiting from 12 to 35 seconds, with a shared 80-second network budget per initial/deeper search and the existing six-request cap/rate spacing. Reject an expired budget before rate waiting.
- If a municipality request fails, check valid cached locality variants without new network attempts. Preserve endpoint, bbox, proximity and TTL cache isolation; label cache results and retain the online error instead of presenting it as a missing place.
- Keep name ranking/filtering, circular buffers and ecological scoring unchanged. Update the status before lookup to explain bounded waiting.

## 15.6.29 - Candidate preview and empty-analysis alerts

- Show WGS84 latitude/longitude and the selected candidate’s GeoLichen R55-S65 model radius below the ecological action buttons. Debounce model calculation by 150 ms and cache up to 32 candidates per result; do not run ecological ranking or full GBIF/MCI/SSI analysis on mouse movement.
- Clear pending previews on capture cancellation, invalidation and stale source selection. Preserve existing uncertainty formulas and verify model radius against candidate confirmation.
- Explain zero compatible candidates with actionable locality/buffer/altitude/DEM/environment checks, retain original filter diagnostics, reject empty service results and invalidate previous results after analysis failure to prevent stale confirmation.
- Document a measured lossless data-packaging study and the choice of whole-Lombardy coverage, including incomplete local DEM coverage and the need for a portable project/configuration preset. No dataset is included in the plugin ZIP.

## 15.6.28 - Targeted locality exploration

- Continue the initial lookup after partial matches using up to three unique search-only variants per reference: original/expanded name, simplified connectors and a complete municipality suffix removed. Keep the original record text and semantic interpretation intact; share repeated work across parser and record queries. Exact-name hits retain the short path.
- Prioritize full own-name and distinctive-token coverage before context scores. Compare the municipality with structured source city/municipality fields, not a substring in the locality name; explain conflicts without excluding border alternatives.
- Add a search inside the map extent captured before candidate previews. Transform the project CRS to WGS84, intersect with configured search bounds, keep this action strictly bounded and preserve old choices on empty/error responses. The action neither changes project search settings nor creates a buffer.
- Retain cache, serialized requests, six-request cap, archive review, circular buffers and ecological scoring. Partial matches remain unverified and unmarked as recommendations.

## 15.6.27 - Distinguish locality names from municipality context

- Apply own-name plausibility checks to generic localities too. A known municipality token alone cannot justify a distinct locality match (for example, Foppe di Braone must not recommend Municipio di Braone).
- Warn explicitly when only partial names are available, both initially and after deeper lookup. Preserve explicitly confirmed historical aliases.
- If only the municipality was found for a distinct locality, open the retry/manual path with no municipality candidate substituted silently. Town-only lookups remain supported.
- Preserve circular buffers, ecological formulas and bounded network usage.

## 15.6.26 - Stronger locality search and confirmed anchors

- Add an editable name and bounded "Cerca altre località" action in the locality selector, including empty initial results. Explore variants beyond first success, merge by OSM identity and retain previous candidates on network failure.
- Share conservative abbreviation/accent/apostrophe normalization across geocoding and semantic parsers, preserving original record text. Filter unrelated fuzzy natural-feature hits while tolerating spelling variants.
- Use OSM tags for type-aware ranking and readable types; explain source, query variants, municipal evidence and saved confirmations. Keep distant alternatives available and rerank against the current edited query.
- Add optional project polygon/name-field controls for municipal boundaries. Check actual geometry, holes and borders, use metric boundary distances and load geometries only for matched municipalities. Fall back to explicitly labelled town-center proximity without a polygon.
- Add a persistent per-profile archive of explicitly confirmed locality anchors, scoped by name and municipality and checked against the search area. Reuse offline with explicit review, inspect/remove entries, disable use/saving, write atomically and preserve unreadable archives. Ecological outputs are excluded; moved source anchors remain separate choices.
- Preserve circular operational buffers, ecological scoring and manual capture workflows. Add local regression, controller integration and real Qt6 dialog coverage.

## 15.6.25 - Circular locality search and Overpass waiting

- Always use a metric circle on the selected geocoder point for every searched locality, rather than an OSM polygon or expanded provider rectangle. Retain centralized type-specific point radii and existing explicit-accuracy adjustments.
- Recognize `laghetto`/`laghetti` as lakes, using their 300 m base radius. Skip the unused Overpass locality-geometry lookup. Preserve independent documentary geometry and uncertainty formulas; changed search candidates may change ecological results.
- Separate the trail query execution budget (25 s) from network waiting (60 s per endpoint, at most two endpoints), allowing queuing/transfer beyond the previous 27 s total cutoff. Keep bounded cancellation, refusal cooldowns, existing endpoints and the same trail query/cache keys.
- Check underlying QGIS reply errors even when the blocking call returns NoError; keep the inactivity abort just after the total watchdog to prevent competing timeout diagnostics.
- Add circle/center/documentary-separation across locality types, network-budget and delayed-response regressions. Public server availability remains external to the plugin.

## 15.6.24 - Distinguish OSM paths, tracks and access roads

- Categorize the downloaded layer by its original OSM highway tag: walking/equestrian paths in purple, tracks in brown, access roads in grey; show only present categories in the legend.
- Show persistent counts of clipped segments by group, including an explicit notice if only roads/tracks were returned; keep network errors visible during candidate selection and clear the summary on buffer changes.
- Enforce a total QGIS POST deadline in addition to inactivity timeout. Report busy HTTP 502/503/504 responses clearly; preserve refusal cooldowns and existing endpoints.
- Reject malformed/partial cached Overpass payloads while retaining valid cache and exact-buffer clipping.
- Verify exact-name single-candidate Photon behavior and existing local path data; document unresolved public-server availability. No geocoder expansion, score or uncertainty formula changes.

## 15.6.23 - Independent evidence and exact analysis optimizations

- Use the current locality context and canonical summit aliases; reserve locality coherence for Geography and route proximity for Accessibility, preserving the four 25% macro weights.
- Preserve low measured Accessibility values instead of accidentally clipping them to the missing-data neutral value of 50.
- Make altitude compatibility gradual for single elevations and consistent for intervals; keep existing hard tolerances and avoid midpoint preference. Do not assign south-facing aspect to flat DEM cells.
- Treat zero distances as real measurements. Replace legacy tie breakers with explicit elevation/locality/trail/center/id ordering.
- Keep soil chemistry separate from observed ground support; distinguish uncertain forest-host proxies from specific host incompatibility.
- Reuse WGS84 distance measurement, share DEM neighbours, skip expensive sampling for altitude-rejected points, reuse record invariants and transformed forest geometries, aggregate official environment once and calculate uncertainty only on the final refined grid.
- Add an exact compact-cluster SSI shortcut with full-algorithm equivalence checks, not an approximate or changed stability index.
- Align candidate labels and new field aliases with the existing R55-S65 method while preserving legacy S70 column recognition. Fix the empty-candidate uncertainty fallback.
- Add synthetic regressions, a reproducible local benchmark and documentation of model changes, measured performance and validation limits.

## 15.6.22 - Restore locality review before buffer creation

- Always show the locality-selection dialog for a successful geocoder result, including when only one candidate is returned.
- Label the confirmation action "Crea buffer" and explain single/multiple-result review; preserve double-click confirmation and cancellation.
- Preview each selected locality on the map, then clear the preview on acceptance, cancellation or errors.
- Build the buffer only from an explicitly selected candidate; abort if an accepted dialog supplies no valid selection.
- Retain automatic ecological analysis after locality selection and all existing ecological formulas and trail behavior.

## 15.6.21 - OSM trails inside the current buffer

- Clip downloaded line geometries to the exact search buffer rather than using every way returned for its bounding rectangle; support polygon holes, separate fragments and manual corridors.
- Keep OSM IDs and trail attributes on clipped fragments. Reject corrupt coordinate sequences without joining across missing segments.
- Reclip cached raw responses to each current geometry, including different buffer shapes sharing an envelope.
- Remove managed temporary OSM trails when the record/buffer changes, and before a new download; preserve user-supplied line layers. Do not reuse a checked old OSM layer after disabling downloads or after a download failure.
- Add circle, hole, cache-shape, corridor and stale-layer regressions. Live Overpass availability is still unverified; timeouts remain distinct from an empty successful result.

## 15.6.20 - OSM locality search

- Replace MapTiler geocoding with Photon/OpenStreetMap, without an API key; expose the Photon URL in configuration and retain search-area controls.
- Wire the optional wider search after an empty area-constrained response; mark expanded candidates for review.
- Cache lookups for 30 days, serialize/throttle requests and cap network variants at six per interactive lookup; stop on network failures and preserve manual workflows.
- Prefer bare toponyms and exclude roads/railways when searching natural passes/peaks/valleys, avoiding roads named after a pass.
- Preserve the existing Overpass geometry/trail workflow and ecological score formulas. Identify requests, preserve application identification after QGIS rewrites headers, update the fallback endpoint and share handling of refusals, cooldowns and incomplete responses.
- Limit accessibility selection to usable vector line layers; fix checked-state comparison for Qt 6. Retain OSM failure notices after ranking and remove outdated trail layers.
- Add local integration/regression coverage and document the difference between verified Photon live search and unresolved Overpass live availability.

## 15.6.19 - QGIS 4 / Qt 6 compatibility

- Retain QGIS 3.22+ while allowing the experimental package on QGIS 4.x.
- Use scoped Qt enums, `exec()` and the correct QAction module for each Qt generation.
- Use QMetaType field types on QGIS 3.38+, with QVariant fallback on older releases.
- Prefer current QGIS enums and explicitly decode Python enum values for geometry and network errors.
- Add real-PyQt6 widget/API checks and instructions for the remaining full QGIS 4 acceptance test.
- Preserve ecological weights, formulas, ranking and data formats.


## 15.6.18

- Restore "Suitability Surface" in the visualization menu and explain in its hover descriptions that it displays an ecological-suitability heatmap.
- Preserve the heatmap selection when updating from 15.6.17.

## 15.6.17

- Rename the visualization option from "Suitability Surface" to "Heatmap", preserving its rendering and the selected mode across updates.

## 15.6.16

- Add concise Italian hover descriptions to main-panel buttons, disclosure headers, dialog actions, exports and diagnostic tools.
- Explain the difference between opening the next step, saving data, retrying and cancelling; use native Qt tooltips that disappear automatically.

## 15.6.15

- Keep long layer and field names from forcing horizontal scrolling in the dock; show complete selected names in tooltips.
- Let form fields move beneath labels when needed, keep diagnostic text wrapped and allow the configuration header to shrink with the panel.
- Verify collapsed and expanded sections at 420, 520 and 800 pixels with long names, scientific names and URLs, without hiding the horizontal scrollbar.

## 15.6.14

- Display the full configuration title on a single line.
- Rename guided and automatic ecological actions to "Analisi ecologica step by step" and "Analisi ecologica automatica".
- Place both actions side by side in one ecological-analysis box, with full-width record copying below; preserve controller bindings and analysis behavior.

## 15.6.13

- Keep retry and use adjacent on the right of the candidate prompt, with exit on the left, independent of native dialog button ordering.
- Expand the configuration disclosure header to the full plugin-panel width.
- Place locality search and centroid completion in a single 4:1 row; replace the centroid text with the user-supplied target/add icon, retaining its tooltip, accessible name and existing behavior.
- Include only the explicitly allowlisted PNG interface asset in release packages; keep datasets and compiled binaries excluded.

## 15.6.12

- Guide manual ecological placement directly from the analysis button: ready-grid prompt, map picking, rank preview with use/retry/exit, then the existing candidate editor.
- Remove the separate ecological confirmation button and the duplicate final confirmation after the candidate editor; its acceptance saves through the existing writer.
- Reuse the ranked grid on retry and build a local metric spatial index for snapping; show pickable candidates alongside heatmaps when needed.
- Restore the previous map tool on exit/Escape/right-click; disconnect capture on tool changes, invalidation and plugin unload. Stop stale-record/result confirmations and keep automatic rank-one processing separate.
- Preserve the 15.6.11 scoring, grid policy, heatmap calculations and uncertainty methods.

## 15.6.11

- Keep missing pH, slope and tree observations distinct from evaluated compatibility; use fixed neutral missing weights for every ecological group.
- Pass structured substrate, lithology and habitat evidence from the ecological engine to the official scoring model instead of parsing diagnostic text.
- Remove generic tree bonuses for ground/rock/moss records and soil-pH scoring on rock/bark; compare soil reaction with the species preference.
- Downweight forest context proxies, preserve isolated-tree/deadwood possibilities and avoid confirming habitat from missing substrate, slope or a universal altitude threshold.
- Export environmental evidence coverage, quality-adjusted coverage and the neutral contribution; update MCI completeness to use observations instead of preferences.
- Keep the four macro weights at 25% each and retain existing locality, altitude-filter, heatmap and confirmation workflows. Scientific accuracy and weight calibration still require independent benchmark records.

## 15.6.10

- Enclose manual ecological analysis, automatic processing and copying in one ecological-analysis box, retaining a separate inner frame around manual analysis and confirmation.

## 15.6.9

- Separate locality georeferencing and ecological analysis into sibling boxes, with automatic processing and copying below both sections.

## 15.6.8

- Rename the main actions to "Ricerca della località", "Copia su altri record" and "Analisi ecologica del punto più probabile".
- Group ecological analysis and point confirmation in one box; keep automatic processing and copying below it.

## 15.6.7

- Add "Punto più probabile automatico" below the existing ecological search button.
- Resolve the locality using the existing chooser, rank the grid, then write rank 1 coordinates, DEM elevation and uncertainties directly to the selected row.
- Reuse the manual confirmation calculations, create missing output columns automatically and show the saved point even in heatmap-only mode.
- Stop on locality cancellation, analysis failure or source-selection changes; preserve pending table edits and prevent overlapping automatic runs.

## 15.6.6

- Label point-confirmation uncertainties as "Incertezza località" and "Incertezza GeoLichen", preserving GBIF and R55–S70 calculations and existing columns.
- Add a button to create missing numeric confirmation columns, with short portable names and without committing unrelated pending edits.
- Copy confirmed points to explicitly chosen rows using a separate multi-selection dialog with locality/municipality and text filters.
- Exclude hidden rows, confirm destination counts and reject destinations changed after preview; roll back source-row edits together on write failure.
- Fix ambiguous coordinate-field detection and transform copied X/Y values to the destination CRS.

## 15.6.5

- Resample heatmap colors when zooming in or out, including existing GeoLichen heatmaps.
- Keep source raster values, analysis grid, ecological scores, candidate ranking and uncertainty unchanged.

## 15.6.4

- Follow selection events from all record tables, including detached attribute windows, instead of prioritizing a cached unselected source.
- Show the source table selector with layer IDs so duplicate names remain distinguishable.
- Restore mappings independently per source and keep source-selection observers correct across reloads and layer removal.
- Reject ranking and confirmation when results belong to another source/row, including a selection change while confirmation is open.
- Cancel pending manual capture when the source record changes and report the exact table/selection count in selection errors.
- Retain API key, layer choices, DEM priority and manual settings in process memory during plugin reloads.

## 15.6.3

- Keep the computed R55–S70 radius visible above its destination field, even with candidate details collapsed.
- Display unavailable model radius explicitly and verify numeric output to the source table and confirmed-points layer.

## 15.6.2

- Keep listening to the configured source table when result layers become active.
- Store input field mapping on the source layer in the QGIS project and restore it after plugin reload.
- Recover a uniquely selected source table and offer field configuration on first analysis.
- Require exactly one current selection; never reuse a stale row or collapse multiple selected rows.

## 15.6.1

- Show current buffer surface area, radius/line offset and base grid spacing.
- Collapse candidate diagnostics while keeping editable values and destination fields visible.

## 15.6.0

- Restore all GeoLichen commands to the Plugins menu.

- Group layer/record configuration, manual geometry tools and ITALIC in collapsible sections.
- Hide legacy result/input summaries and the grid-step input; keep operational status visible.
- Select the base grid step from buffer radius/line offset (10, 30, 50 or 100 m).
- Recompute the grid and discard stale candidates when the search geometry changes.
- Scale and clip the global suitability raster to the new search area and grid step.
- Add centroid completion with WGS84 coordinates, multi-DEM sampling and optional table output,
  without ecological scoring or invented confidence/uncertainty values.
- Extend built-in English lithology and soil terms and automatic field detection.
- Retain adaptive local refinement, manual-line analysis and ecological candidate confirmation.

## 15.5.18

- Prepare English public documentation, dependency/service requirements and
  geographical restrictions, a GPL license text and attribution inventory.
- Use the Vector menu and QGIS networking for ITALIC and MapTiler requests.
- Store ITALIC caches/snapshots inside the QGIS user profile.
- Add package validation and a reproducible ZIP builder; exclude all datasets
  from public source and release archives.
- Limit compatibility metadata to QGIS 3 and mark this release experimental.

## 15.5.17

- Simplify the controller interface, reuse confirmed points and support a
  manually defined line corridor.

Earlier development notes are retained locally in `readme and change/`.
