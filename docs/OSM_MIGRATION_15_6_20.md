# GeoLichen 15.6.20: ricerca e sentieri OpenStreetMap

La ricerca località ora usa **Photon**, un servizio di geocodifica basato su
OpenStreetMap. Non serve più un account o una chiave MapTiler. La cartografia
visibile sotto il progetto può essere quella che preferisci: non alimenta
l'analisi di accessibilità.

## Aggiornamento 15.6.22: scelta della località

Dopo **Ricerca della località**, verifica sempre la finestra **Seleziona località**:
compare anche se Photon ha trovato un solo candidato. Seleziona la riga corretta
per visualizzarne l'anteprima sulla mappa, poi premi **Crea buffer** o fai doppio
clic sulla riga. Il buffer viene costruito soltanto dopo la conferma, usando
la località che hai scelto. **Annulla** chiude il passaggio senza creare un buffer;
puoi quindi usare gli strumenti manuali. Anche l'analisi ecologica automatica
mantiene questa scelta iniziale della località. Questo aggiornamento ripristina
la verifica; non amplia il numero di risultati ottenuti dal servizio.

## Aggiornamento 15.6.21: sentieri nel buffer

Il layer temporaneo **GeoLichen – Sentieri OSM nel buffer** ora contiene solo
le porzioni lineari dentro la forma effettiva del buffer, comprese aree con
buchi e corridoi manuali. Il rettangolo usato per la richiesta può essere più
ampio: i dati vengono ritagliati dopo il download e nuovamente quando si usa
la cache. ID OSM e attributi restano associati ai tratti risultanti.

Quando cambi area/record il vecchio layer temporaneo viene rimosso. I tuoi
layer di sentieri restano nel progetto. Se disattivi i download OSM, un vecchio
layer temporaneo spuntato nella lista non viene riutilizzato nell'analisi.
Il download avviene all'avvio dell'analisi ecologica sul buffer corrente, con
**Usa dati sentieristici OpenStreetMap** attivo; **Mostra layer OSM scaricato**
controlla la sua visualizzazione. Le prove locali sono passate, ma il download
dai server pubblici continua a restituire timeout nell'ambiente di prova.

## Configurazione e uso

1. Installa lo ZIP 15.6.22 in QGIS e riavvia QGIS per caricare i nuovi moduli.
2. Apri **Configurazione layer e campi tabella record**. **Servizio Photon**
   contiene già `https://photon.komoot.io/api/`. Non inserire qui una chiave API,
   uno stile cartografico, un URL di tile o un servizio Nominatim.
3. Scegli l'area di ricerca, configura i campi e seleziona una riga della tua
   tabella. **Ricerca della località** cerca prima il comune, poi i toponimi
   con il contesto geografico del comune. In caso di ambiguità scegli la località
   corretta dalla finestra dei candidati. Se **Espandi automaticamente** è attivo,
   una risposta vuota nell’area permette un secondo tentativo più ampio: verifica
   il comune e la distanza dei candidati prima di confermare. Disattivalo per
   mantenere il vincolo geografico.
4. Controlla il buffer. Le funzioni di centroide, punto e linea manuali restano
   disponibili, anche se il servizio non trova il nome o non risponde.
5. In **Accessibilità**, lascia attivo **Usa dati sentieristici OpenStreetMap**
   per scaricare geometrie OSM via Overpass. Puoi usare anche tuoi layer lineari
   locali: vengono utilizzati per misurare le distanze e non richiedono MapTiler.
   I Vector Tile e le tabelle senza geometria non compaiono più in questa lista,
   perché non fornivano distanze utilizzabili dal motore.
6. Esegui **Analisi ecologica step by step** oppure **Analisi ecologica automatica**.
   La griglia, gli score, la Suitability Surface e la scrittura nelle colonne
   mantengono il flusso precedente. Un'area diversa trovata da Photon può
   naturalmente cambiare i punti e i risultati: non sono cambiati i pesi ecologici.

## Servizi, cache e limiti

Photon restituisce nomi, coordinate, eventuali estensioni e identificativi OSM.
Il plugin converte questi risultati nel formato interno già usato per buffer,
selezione e provenienza. Le coordinate della risposta sono longitudine/latitudine
WGS84. Una strada intitolata a un passo o una cima viene esclusa dalla ricerca
quando si sta cercando quel riferimento naturale.

Il [demo Photon](https://photon.komoot.io/) ammette un uso moderato e non garantisce
continuità. Il plugin distanzia le richieste di almeno 1,1 secondi, le esegue in
sequenza, limita ogni ricerca interattiva a sei chiamate di rete e conserva le
risposte per 30 giorni nel profilo QGIS, in `geolichen/photon_cache/`.
Un risultato già in cache non richiede una nuova chiamata. La cache distingue
URL, testo, area di ricerca e posizione di riferimento. Per uso intensivo o
istituzionale configura un'istanza Photon adeguata, privata o autogestita.
Il servizio pubblico Nominatim non è usato come ripiego.

I sentieri e le geometrie di località vengono richiesti separatamente a
Overpass: endpoint principale `https://overpass-api.de/api/interpreter`,
alternativa `https://overpass.private.coffee/api/interpreter`. Le geometrie
hanno una cache locale di 24 ore sotto `geolichen_cache/` nel profilo QGIS.
Le richieste dichiarano il nome dell'applicazione anche quando QGIS sostituisce
l’intestazione HTTP; il plugin non modifica le impostazioni di rete globali. Un rifiuto HTTP 406 o 429
interrompe i tentativi e sospende temporaneamente le nuove chiamate allo stesso
endpoint; risposte parziali con errore non sono salvate come dati validi.

Se Overpass non risponde, il plugin rimuove il precedente layer temporaneo OSM
ed espone un avviso nel risultato/stato. L'analisi può continuare con i layer
lineari locali disponibili; senza dati utilizzabili l'accessibilità resta una
componente priva di evidenza, secondo le regole esistenti. Non interpretare
l'assenza di dati come assenza reale di sentieri. Un download completato con
zero geometrie viene segnalato distintamente da un errore di rete.

I sentieri sono oggetti mappati dai contributori OSM, non una certificazione
aggiornata della percorribilità, apertura al pubblico o sicurezza sul terreno.
Conserva attribuzione e licenza quando esporti i dati OSM.

## Verifiche del 22 ottobre 2026

- Ricerca online effettiva con il sistema di rete QGIS: **Edolo** e
  **Passo di Crocedomini, Breno**, senza chiavi API. La seconda richiesta di
  Edolo riusa la cache senza chiamate di rete. La ricerca del passo restituisce
  il passo naturale e non la strada omonima.
- Prove automatiche locali: ricerca Photon → griglia ecologica; generazione e
  cache dei layer di sentieri; uso effettivo della geometria nel calcolo delle
  distanze; risoluzione di una località poligonale; errori, rifiuti e fallback.
  Le risposte di questi casi sono sintetiche: non dimostrano disponibilità dei
  server pubblici né accuratezza scientifica.
- **Download online Overpass non verificato con successo**: le prove su una
  piccola area del Passo di Crocedomini hanno restituito timeout/risposte vuote
  dai due endpoint. Anche una richiesta indipendente non ha ricevuto dati.
  Non è quindi possibile dichiarare completato il flusso live dei sentieri.
- Ambiente verificato: macOS, QGIS 3.44.9/Qt 5.15.18; controlli separati dei
  widget con Qt 6. Le prove su Windows/QGIS 3.40 e nel runtime completo QGIS 4
  restano da eseguire. Non è stato misurato un miglioramento dei 3–5 minuti
  di analisi ecologica segnalati su Windows.

Il manuale/PDF 15.6.18 resta una descrizione storica; per la configurazione della
ricerca sostituisci le istruzioni MapTiler con questa pagina. Nessun dataset
privato è incluso nel codice o nello ZIP.

Fonti: [Photon](https://github.com/komoot/photon),
[Private.coffee Overpass](https://overpass.private.coffee/),
[attribuzione OSM](https://www.openstreetmap.org/copyright).
