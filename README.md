# GeoLichen

**15.6.34:** scansione offline Bandit/detect-secrets prima della distribuzione,
controllo degli URL e redirect dello strumento opzionale per l’indice ITALIC,
e documentazione allineata alle verifiche effettive. Vedi il
[resoconto di sicurezza](docs/SECURITY_REVIEW.md).

**15.6.33:** in caso di errore Overpass, recupero della risposta completa della
stessa richiesta dall’archivio locale fino a 30 giorni, con età e avviso visibili.
La cache ordinaria resta valida 24 ore; le richieste fallite per la stessa area
non sono ripetute per 60 secondi. La finestra Performance separa download OSM
e calcolo ecologico. Questo non ripristina i server pubblici indisponibili.

**15.6.32:** controlli GitHub attivati; corretta la finestra candidato per Qt 6.
I risultati delle prove automatiche sono consultabili in
[GitHub Actions](https://github.com/LucaGrazia0/geolichens/actions/workflows/checks.yml).

**15.6.31:** controlli automatici e preparazione verificata dello ZIP, diagnostica
nel registro QGIS e [manuale corrente](docs/MANUALE_UTENTE.md).
Vedi [sviluppo e distribuzione](docs/DEVELOPMENT.md) per i comandi e lo stato
delle verifiche su ciascun sistema. Nessuna modifica a score o incertezze.

**Aggiornamento 15.6.30:** l’attesa Photon passa da 12 a 35 secondi per richiesta,
con un budget di rete complessivo di 80 secondi per ricerca. Se il comune non
risponde, vengono comunque cercate le varianti della località già disponibili
nella cache valida, senza altre richieste dopo l’errore. L’avviso distingue
un problema online dall’assenza di corrispondenze. Il servizio pubblico può
comunque rimanere indisponibile; i filtri sui nomi e gli score non cambiano.

**Aggiornamento 15.6.29:** durante la scelta sulla mappa compare sotto i pulsanti
una preview copiabile con rank, latitudine, longitudine WGS84 e incertezza
GeoLichen R55–S65. Il raggio è quello del candidato agganciato, distinto
dall’incertezza della località, e viene calcolato dopo una pausa del cursore.
La preview non scrive dati; sparisce annullando o cambiando record.
Se i filtri non lasciano candidati, compare un avviso con i controlli suggeriti;
i risultati precedenti non restano disponibili per una conferma sbagliata.
Vedi anche lo [studio sul pacchetto dati Lombardia](docs/PACCHETTO_DATI_LEGGERO.md).

**Aggiornamento 15.6.28:** ricerca di ulteriori varianti dopo risultati parziali,
priorità al nome proprio e confronto con il comune riportato dalla fonte.
La finestra consente anche di cercare nella zona della mappa inquadrata prima
dell’anteprima. Vedi [ricerca delle località](docs/LOCALITY_SEARCH_15_6_26.md).

**Aggiornamento 15.6.27:** i nomi generici vengono confrontati separatamente
dal comune. Le corrispondenze parziali sono segnalate e non consigliate;
un comune trovato da solo non sostituisce una località distinta non trovata.

GeoLichen is a QGIS plugin for ecologically assisted georeferencing of historical
lichen records. It interprets locality descriptions, ranks candidate points
using ecological and environmental information, and supports expert review,
manual refinement, uncertainty estimates and provenance reporting.

Il [manuale utente in italiano](docs/MANUALE_UTENTE.md) descrive installazione,
configurazione, analisi, interpretazione dei risultati e salvataggio per la 15.6.34.
Per la nuova ricerca OSM senza API key, leggi anche [migrazione 15.6.20](docs/OSM_MIGRATION_15_6_20.md).
Per i buffer circolari delle località e l'attesa del download sentieri, vedi
[aggiornamento 15.6.25](docs/CIRCULAR_BUFFERS_15_6_25.md).
La [ricerca località 15.6.26](docs/LOCALITY_SEARCH_15_6_26.md) aggiunge ricerca
approfondita, nomi abbreviati, confini comunali facoltativi e un archivio delle
località confermate disponibile anche senza rete.

The interface is in Italian. Locality interpretation and ITALIC profiles target
Italy; the default search area is Lombardy. Optional local dictionaries and taxon
indexes are not bundled. Other regions are selectable, but performance outside the intended
geographical and linguistic scope has not been established.

This release is experimental. Candidate scores, confidence indicators and
uncertainty radii are model estimates and require expert validation before use
as published occurrence coordinates.

## Requirements

- QGIS 3.40 through QGIS 4.2 with its Python environment, NumPy and GDAL/OGR (`osgeo`).
  These libraries normally ship with QGIS desktop installers. No additional
  pip packages or other QGIS plugins are required. If an import is missing,
  repair the QGIS installation (on Windows, use the QGIS/OSGeo4W installer).
- Internet access for live ITALIC profiles and OpenStreetMap/Overpass requests.
- Locality lookup uses [Photon](https://photon.komoot.io/), based on OpenStreetMap,
  without an API key. The public demo permits moderate interactive use and has no
  availability guarantee. Configure a compatible private/self-hosted Photon URL
  in the panel for intensive or shared institutional use. No Nominatim public
  fallback is used. Respect each service's terms and resources.
- Environmental vector layers and DEM rasters for the corresponding ecological
  and terrain analyses. These are supplied by the user, with suitable coverage,
  coordinate reference systems and attributes; they are not included.

The release remains experimental. Automated suites passed in real Linux QGIS
3.40.15 / Qt 5 and QGIS 4.2.3 / Qt 6 runtimes, with local macOS/QGIS 3.44.9
verification. Windows and complete interactive QGIS 4 acceptance remain pending.
Metadata is restricted to 3.40–4.2; older and future minor versions are not
claimed by this release. This does not establish scientific accuracy or public
service availability. See [compatibility](docs/QGIS4_COMPATIBILITY.md),
[security review](docs/SECURITY_REVIEW.md) and [publication](docs/PUBLISHING.md).

## Installation

1. Download or build a GeoLichen release ZIP, with a single `geolichen/` folder
   containing `metadata.txt` and `__init__.py`.
2. In QGIS open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the ZIP, install and enable **GeoLichen**.
4. Open **Plugins → GeoLichen**. A toolbar action is also available.

For development, open **Settings → User Profiles → Open Active Profile Folder**
and place this source folder at `python/plugins/geolichen`, then restart QGIS.
This avoids relying on platform-specific profile paths.

## Quick start

1. Load your own records as a vector layer or a table. CSV input can be loaded
   using **Layer → Add Layer → Add Delimited Text Layer**, choosing **No geometry**
   for a table without coordinates. No dataset is included in this release.
2. Make that layer active and open GeoLichen. Expand **Configurazione layer e campi
   tabella record** and click **Configura campi input**.
   Map `scientific_name` and at least one of `municipality` or `locality`.
   Record ID, substrate, rock, tree, elevation and notes are optional.
   Input mapping is retained in the current QGIS project across plugin reloads;
   save the project to retain it after closing QGIS. The source table remains
   bound even while a result layer is active. Exactly one source row must be selected.
   The **Tabella record** selector shows which source is used. Selecting a row in
   another record table switches that source, including in detached table windows.
   You can choose a source explicitly when multiple tables have selected rows.
   Results from a different source or record cannot be confirmed for the new selection.
3. Select the appropriate search area; the Photon service URL is prefilled and no
   MapTiler key is needed. Load and select relevant geology, soil, vegetation and DEM layers
   when available, and associate the relevant attribute fields in the panel.
4. Select one record and click **Ricerca della località**. Review the locality
   candidates and their map preview, then click **Crea buffer**. Since 15.6.22
   this review also appears for a single result; **Annulla** creates no buffer.
   Expand **Profilo ITALIC** to inspect the taxon information.
   Missing data or unavailable services can limit results; inspect diagnostics.
5. Expand **Punto e linea manuali** for manual geometry tools. To finish with the
   search area's centroid, click **Sono a posto così**. Review the WGS84 longitude,
   latitude and DEM elevation, optionally select destination fields and save the
   centroid. It is added to the confirmed-points layer without ecological scores.
   Missing DEM elevation remains empty. Since 15.6.13 the centroid action is the
   target/add icon next to **Ricerca della località**, with the same function and
   the **Sono a posto così** tooltip.
6. For ecological placement, click **Analisi ecologica step by step**.
   Once ranking finishes, **Scelta del punto ecologico → Avanti** enables map
   picking. Click a candidate, then choose **Sì** to open its existing confirmation
   dialog, **Riprova** to pick another point on the same grid or **Esci** to stop.
   **Cancel**, Escape and right-click leave records unchanged. The separate
   **Conferma punto ecologico** button is replaced by this guided flow.
   **Analisi ecologica automatica** sits beside it in the same box and writes the
   rank-1 candidate directly after locality selection. **Copia su altri record**
   spans the row below both actions. The configuration title is on a single line.
7. Review coordinate, uncertainty and provenance fields in the confirmation
   dialog before writing results. Save your QGIS project and output layers.
   Use a copy of your input data during evaluation.

Validation, benchmark, performance and release checks are available in the
**Plugins → GeoLichen** menu. Benchmarks consume user-provided reference
coordinates; no reference dataset is distributed.

Since 15.6.11, missing evidence keeps a neutral contribution without increasing
other components' weights. Candidate details show environmental evidence coverage;
forest and soil-pH evidence is restricted to relevant ecological groups. The four
macro weights remain at 25% each. See the [scoring revision](docs/SCORING_15_6_11.md)
for rules, proxy assumptions and validation limits.

Since 15.6.23, locality coherence contributes only to Geography and route distance
only to Accessibility. Altitude, flat aspect, zero-distance ties, soil chemistry
and forest-host proxies have been corrected. The four macro weights remain at
25%; point rankings may change as a result of these corrections. Exact SSI/DEM
optimizations reduce repeated work without changing the corrected model's output.
See [score changes and reproducible performance checks](docs/SCORING_15_6_23.md).

Since 15.6.21, the temporary **Sentieri OSM nel buffer** layer contains only the
line fragments inside the exact current search buffer, including manual corridors.
It refreshes when the area changes, while user-supplied trail layers are preserved.
The raw OSM response may cover a larger rectangular envelope, but it is clipped
again even when read from cache. Public Overpass availability still needs live
verification; unavailable data are reported explicitly.

Since 15.6.24 the OSM layer distinguishes walking paths, tracks and access roads
with separate styles and persistent segment counts. A single locality in the
geocoder dialog is separate from the ecological candidate grid. See
[OSM paths, availability checks and uncertainty clarification](docs/OSM_TRAILS_15_6_24.md).

## Automatic grid and substrate interpretation

The base candidate grid uses the current search radius (manual-line half-width
for a corridor): 10 m up to 250 m, 30 m above 250 m up to 1000 m, 50 m above
1000 m up to 3000 m, and 100 m above 3000 m. For irregular automatic polygons the
radius is half the longest side of their bounding box in a local metric CRS.
The panel shows the current search area in hectares or square kilometres, its radius
(or line offset) and the base grid spacing. Candidate confirmation opens with
diagnostics collapsed and data-entry fields visible.
Changing the search geometry discards previous candidate outputs. Existing
adaptive refinement may sample promising areas more finely; the global surface
uses the base grid and is clipped to the full search area.

Lithology descriptions are interpreted automatically using built-in Italian and
English rules. Creating a `GRUPPO_LITO` field remains optional. Soil sampling
supports numeric pH and acidic/neutral/basic text classes, with automatic field
suggestions. The ecological categories `calcareo`, `siliceo` and `misto` describe
substrate compatibility; they do not implement a petrological classification
of igneous rocks or a measurement of soil pH from lithology.

See [interface and regression notes](docs/INTERFACE_15_6.md) for details.

Hover over buttons or disclosure headers for a short Italian description of
the action. These native tooltips disappear when the pointer moves away.

The dock adapts layer/field menus and form rows to its available width. Long
selected names remain available in tooltips and selection menus. Expanded
configuration sections use vertical scrolling when necessary.

## Network requests and local storage

ITALIC receives queried taxon names. The configured Photon service receives locality
search strings and the search bounding box/proximity. Overpass receives geometry
queries for the selected area. Requests occur during the corresponding analyses;
ensure the data can be sent to those services. The plugin uses QGIS networking
for runtime requests and therefore uses QGIS proxy and TLS settings.

Photon results are cached for 30 days in `geolichen/photon_cache/` inside the active
QGIS profile; the URL and search area are part of the cache key. Locality requests
are serialized, spaced by at least 1.1 seconds, and limited to six network calls
per interactive lookup. OSM trails/geometries have a separate 24-hour cache under
`geolichen_cache/`. Overpass refusals/rate limits pause retries; incomplete error
responses are never treated as valid trail data. Only usable vector line layers
appear in the accessibility selector; a basemap is not required. Mapped OSM paths
do not certify real-world access or passability.

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
repository. Publish release artifacts separately; see
[PUBLISHING.md](docs/PUBLISHING.md).

## License and attribution

The source-code release license is **GNU GPL version 2 or later**;
the full text is in [LICENSE](LICENSE). Datasets, regional dictionaries, taxon
indexes, cached responses and user snapshots are excluded from both the public
repository and release ZIP. The plugin uses built-in rules and live services
when optional local dictionaries are absent; region-specific aliases, dictionary
classifications and the local taxon index are then unavailable. The GPL declaration
does not relicense third-party data. See [THIRD_PARTY.md](THIRD_PARTY.md) for
dependencies and external services.
