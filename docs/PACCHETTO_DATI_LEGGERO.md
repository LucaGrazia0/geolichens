# Distribuzione leggera dei dati GeoLichen

Studio locale dell’11 novembre 2026. Questa proposta non modifica i dataset originali e non autorizza né esegue la loro pubblicazione.

## Misure reali senza perdita

| Dato provato | Originale | File ottimizzato | Download compresso |
| --- | ---: | ---: | ---: |
| Un DEM 5010 × 5010 Float32 | 100,44 MB | 55,60 MB GeoTIFF | circa 55,61 MB |
| Carta forestale, 315.720 elementi | 556,23 MB Shapefile e accessori | 392,58 MB GeoPackage | circa 213,53 MB |

I MB sono decimali. Per il DEM sono stati confrontati **tutti i pixel**, il valore NoData, il geotrasformato e la proiezione; per la carta forestale **tutti gli attributi e le geometrie WKB** di ogni elemento. Nessun ricampionamento, arrotondamento delle quote o semplificazione geometrica. Il GeoPackage include l’indice spaziale. Le dimensioni di download sono misure del flusso DEFLATE, cui uno ZIP aggiunge un piccolo overhead. Il test non è un pacchetto completo: include un solo DEM dei quattro individuati e una sola carta vettoriale.

I risultati e le copie di prova sono in `output/data_package_study/benchmark.json` e nella stessa cartella, esclusa dal pacchetto del plugin e dal repository pubblico.

## Copertura scelta: tutta la Lombardia

L’utente ha scelto **tutta la Lombardia**: nessun ritaglio per Val Camonica.
Si propone un solo progetto iniziale regionale, con eventuali moduli di download
che mantengano nel complesso la copertura regionale. I quattro DEM locali sono
10 m, ma **non coprono tutta la Lombardia**: gli inviluppi complessivi individuati
vanno circa da 9,64 a 10,96 E e da 45,59 a 46,50 N; mancano almeno aree occidentali
e meridionali. Gli inviluppi non equivalgono alla copertura di pixel validi.
Occorre completare l’inventario dei DEM, controllare NoData e licenze e misurare
il pacchetto completo prima di distribuirlo. Vedi il controllo locale
`output/data_package_study/dem_coverage.json`. Il pacchetto regionale definitivo
non è stato ancora confezionato; le prove presenti sono copie tecniche.

## Pacchetto proposto

- **Plugin**: solo codice e documentazione, circa 1,3 MB; installazione indipendente dai dati.
- **Starter per area**: progetto `GeoLichen.qgz`, GeoPackage dei layer vettoriali, GeoTIFF dei DEM e istruzioni/fonti/licenze. Percorsi relativi alla cartella del progetto, senza percorsi Desktop o unità Windows fissi.
- **Estensioni geografiche**: ulteriori DEM e layer per aree distinte, da scaricare solo se servono. Non includere tutti i DEM in ogni pacchetto.
- **Sentieri**: download OSM nel buffer già disponibile; pacchetto ufficiale offline opzionale, utile dove i dati OSM sono incompleti o la rete non è disponibile. Evitare di includere la stessa rete in più formati nello starter.
- **Tabella record**: un modello vuoto con le colonne raccomandate; i dati personali e i record di lavoro dell’utente rimangono separati.

Aprire il QGZ consente di avere i layer già caricati. Per garantire anche tutte le associazioni campi/ruoli del plugin su un altro PC serve un preset portabile: oggi alcune impostazioni sono locali o legate alla sessione e ai layer del progetto. Questa parte va realizzata e verificata nel confezionamento del pacchetto; non basta trasferire le preferenze del Mac.

Struttura suggerita:

```
GeoLichen_area/
  GeoLichen.qgz
  dati/ambiente.gpkg
  dati/dem_01.tif
  modello_record.csv
  FONTI_E_LICENZE.md
  LEGGIMI.md
```

## Come ridurre ulteriormente il peso

1. Concordare la copertura: Val Camonica, Lombardia o moduli per area. Ritagliare i dati sull’area concordata con un margine sufficiente per buffer e campionamenti del terreno; segnalare chiaramente le zone prive di copertura. Non usare il solo limite comunale se il buffer può uscirne.
2. Conservare i poligoni e le quote originali. Per i DEM usare compressione lossless DEFLATE con predictor 3 per Float32 e tasselli; per i vettori GeoPackage con indice spaziale. Il GeoPackage non garantisce da solo un file più piccolo: il risultato va misurato. [GeoTIFF GDAL](https://gdal.org/en/stable/drivers/raster/gtiff.html), [GeoPackage GDAL](https://gdal.org/en/stable/drivers/vector/gpkg.html).
3. Solo dopo avere definito i ruoli, mantenere le colonne usate dal plugin e quelle necessarie a interpretazione, provenienza e controlli. Esempi locali: `LITOLOGIA`/gruppo litologico verificato, `PH_1M`/`DESCR_PH`, `CATEGORIA`/`LEGENDA_1`; la scelta definitiva dipende dalla configurazione effettiva. Non eliminare campi alla cieca.
4. Eliminare soltanto duplicati del pacchetto: copie di backup, ZIP già estratti, cache, risultati temporanei. Non distribuire contemporaneamente Shapefile e la sua conversione GeoPackage.
5. Misurare il peso dopo il ritaglio. Una previsione affidabile del pacchetto completo richiede la copertura scelta; non si può estrapolare il rapporto di un DEM a tutti gli altri.

Ridurre la risoluzione dei DEM, convertirli a interi o semplificare i poligoni riduce ancora lo spazio, ma può cambiare pendenza, esposizione, intersezioni, score e posizione scelta: non è il percorso predefinito.

## Verifiche prima della distribuzione

Controllare per ciascun dataset fonte, versione, condizioni di redistribuzione e attribuzioni. Il fatto che una copia sia già sul PC non dimostra che si possa ripubblicare. Il repository GitHub del plugin continuerà a contenere soltanto codice/documentazione, senza dataset.

Provare il pacchetto da una nuova cartella e un profilo QGIS pulito, anche su Windows: assenza di layer mancanti, CRS corretti, copertura DEM/NoData, associazione dei campi, stessa analisi su record di riferimento. Salvare un inventario dei dati e checksum; il pacchetto non deve dipendere dai percorsi del PC di sviluppo.
