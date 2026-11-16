# GeoLichen - Manuale utente

**Versione del plugin:** 15.6.33  
**Edizione del manuale:** 2.0 - 16 novembre 2026  
**Autore del plugin:** Luca Grazia

Guida operativa alla versione attuale: ricerca Photon/OpenStreetMap senza API key,
sentieri Overpass, buffer circolari, analisi guidata o automatica e anteprima del
candidato. I precedenti PDF della 15.6.18 restano documenti storici.

GeoLichen è sperimentale: punteggi, indicatori e raggi del modello richiedono
valutazione specialistica prima dell'uso come dati di presenza pubblicati.

Percorso rapido: [installazione](#2-installazione-e-trasferimento-su-windows),
[configurazione](#3-photonopenstreetmap-area-di-ricerca-e-configurazione),
[ricerca località](#9-ricerca-della-località-e-centroide),
[esempi di elaborazione](#17-esempio-a-elaborare-una-riga-passo-per-passo).
Per lo sviluppo e le prove automatiche: [procedura verificata](DEVELOPMENT.md).

## 1. Scopo, requisiti e compatibilità
GeoLichen parte dalla descrizione di una località, definisce un'area di ricerca e valuta punti candidati usando informazioni del cartellino, profili ecologici ITALIC e layer ambientali forniti dall'utente. Il risultato è una proposta di georeferenziazione, accompagnata da indicatori e diagnostica.

Sono disponibili tre percorsi:

| Percorso | Quando usarlo | Risultato |
| --- | --- | --- |
| Centroide della località | Vuoi concludere usando soltanto l'area di ricerca | Centroide e quota DEM, senza ranking ecologico |
| Analisi ecologica step by step | Vuoi esaminare e scegliere il candidato sulla mappa | Punto confermato dall'utente e relativi indicatori |
| Analisi ecologica automatica | Vuoi scegliere la località e affidare al ranking la scelta del punto | Candidato di rank 1 scritto direttamente nel record |

### Cosa occorre

- QGIS 3 con Python, NumPy e GDAL/OGR, normalmente inclusi nell'installazione desktop.
- Una tabella di record con specie e informazioni di località.
- Nessuna API key: la ricerca usa Photon, basato su OpenStreetMap.
- Connessione Internet per Photon, ITALIC e richieste OpenStreetMap/Overpass; le cache valide possono evitare alcune richieste.
- Layer ambientali e DEM con copertura adeguata, per le componenti che vuoi valutare.

I metadati consentono QGIS 3.22–3.99 e QGIS 4.x. Questo intervallo non equivale
alla verifica completa di ogni sistema. Le prove locali della 15.6.32 usano
QGIS 3.44.9 su macOS. Le suite automatiche su Linux/QGIS 3.40.15 e 4.2.3 sono
passate su GitHub. Restano da eseguire le prove su Windows e la verifica
interattiva completa di QGIS 4: consulta [compatibilità e stato](QGIS4_COMPATIBILITY.md).

L'interfaccia è in italiano. Descrizioni di località, regole e profili sono pensati principalmente per l'Italia; la ricerca parte dalla Lombardia. Non sono inclusi dataset, DEM, dizionari locali opzionali o un indice locale dei taxa.

## 2. Installazione e trasferimento su Windows
### Installare da ZIP

1. Procurati il pacchetto `geolichen-15.6.33.zip` della distribuzione.
2. Apri QGIS e scegli **Plugins > Gestisci ed Installa Plugin > Installa da ZIP**. Nelle interfacce inglesi: **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Seleziona lo ZIP senza decomprimerlo e premi **Installa plugin**.
4. Verifica che GeoLichen sia abilitato nella scheda dei plugin installati.
5. Apri **Plugins > GeoLichen > GeoLichen**. Puoi usare anche l'azione GeoLichen nella barra degli strumenti.

Il pacchetto deve contenere una sola cartella principale `geolichen`, con `metadata.txt` e `__init__.py`. Usa lo ZIP di distribuzione, che esclude i dati di lavoro.

### Passare da macOS a Windows

Trasferisci lo stesso ZIP sul PC e ripeti la procedura nella versione QGIS da verificare. Per il plugin non sono previsti pacchetti Python aggiuntivi da installare con pip. Se mancano NumPy o GDAL, verifica l'installazione QGIS.

Trasferisci separatamente tabella dei record, layer ambientali, DEM e progetto QGIS. Un progetto che punta a percorsi del Mac può richiedere la riconnessione alle sorgenti sul PC. Controlla il servizio Photon configurato, le associazioni dei campi, i layer selezionati e la priorità dei DEM. Salva le associazioni dei campi nel progetto QGIS; le cache e le località archiviate appartengono al profilo del computer e non viaggiano nello ZIP.

### Aggiornare

Conserva una copia dei dati e installa il nuovo ZIP dalla stessa scheda. Il plugin mantiene alcune impostazioni in memoria durante il ricaricamento; non equivale a salvare una sessione completa di analisi. Salva il progetto per conservare le associazioni dei campi; ricontrolla layer e configurazione alla riapertura.

**Prima verifica:** apri il pannello, seleziona una sola riga e prova l'intero flusso su una copia modificabile dei dati. L'installazione riuscita, da sola, non verifica tutte le funzioni su Windows.

## 3. Photon/OpenStreetMap, area di ricerca e configurazione
Apri **Configurazione layer e campi tabella record** con un clic sulla freccia.
Un altro clic richiude la sezione. Le descrizioni brevi compaiono lasciando il
mouse sul pulsante e scompaiono spostandolo.

### Servizi utilizzati: nessuna chiave MapTiler

- **Photon/OpenStreetMap** cerca i nomi delle località e propone i riferimenti.
  Il servizio predefinito è `https://photon.komoot.io/api/`; non serve un account.
- **Overpass/OpenStreetMap** scarica i percorsi nell'area del buffer. La mappa di
  sfondo è separata: vedere un sentiero sullo sfondo non prova che il download
  vettoriale sia riuscito. I percorsi possono mancare o essere incompleti in OSM.
- **ITALIC** fornisce i profili dei taxa. Non è un servizio di ricerca località.

Nel campo del servizio Photon puoi configurare un endpoint compatibile privato
per un uso intensivo. Il servizio pubblico non garantisce disponibilità; non
rilanciare ripetutamente la stessa analisi quando segnala problemi.
GeoLichen non usa MapTiler per queste operazioni: eventuali mappe MapTiler già
presenti nel progetto restano layer indipendenti scelti dall'utente.

### A cosa serve l'area di ricerca

Seleziona l'area geografica appropriata. L'area iniziale è **Lombardia**; sono disponibili altre regioni, macroaree e un'area personalizzata.

- **Limita la ricerca all'area selezionata** restringe la ricerca geografica.
- **Espandi automaticamente se nessun risultato plausibile** permette di allargare la ricerca quando necessario.
- **Personalizzata** abilita una BBox in WGS84 nell'ordine `xmin,ymin,xmax,ymax`: longitudine minima, latitudine minima, longitudine massima, latitudine massima. Usa il punto decimale e la virgola come separatore dei quattro valori.

L'area geografica della configurazione orienta la ricerca del toponimo; non è il buffer specifico del singolo record. Restringere l'area aiuta a distinguere località omonime e a non cercare inutilmente lontano dal contesto noto.

L'espansione serve quando un toponimo storico, una località di confine o una risposta incompleta del geocoder non rientrano nella ricerca iniziale. Può proporre risultati più lontani: non rende automaticamente corretta la località trovata e non autorizza a ignorare il comune del cartellino. Se il risultato resta incoerente, passa alla definizione manuale anziché accettarlo solo perché compare nella lista.

### Disposizione

Il pannello contiene **Georeferenziazione Località**, **Analisi ecologica** e la sezione richiudibile **Profilo ITALIC**. Le vecchie sezioni di riepilogo non sono mostrate come blocchi separati: resta il messaggio operativo.

Il pannello si adatta alla larghezza disponibile; i nomi lunghi sono leggibili nei suggerimenti e le sezioni aperte possono richiedere scorrimento verticale. Puoi allargarlo o sganciarlo con i comandi QGIS.

## 4. Importare i dati in QGIS
### Importare un CSV senza coordinate

1. Prepara un file con una sola riga di intestazioni, un record per riga e nomi di colonne univoci. Usa UTF-8 per conservare accenti e nomi scientifici. Salva gli identificativi come testo se contengono zeri iniziali.
2. In QGIS apri **Layer > Aggiungi layer > Aggiungi layer testo delimitato** oppure la relativa scheda nel Gestore delle sorgenti dati.
3. Seleziona il file e imposta il separatore realmente usato, per esempio punto e virgola. Verifica l'anteprima e il separatore decimale.
4. In **Definizione geometria** scegli **Nessuna geometria / solo tabella attributi** se il record non è ancora georeferenziato. Non creare punti usando coordinate zero o altri segnaposto.
5. Aggiungi la tabella; controlla quantità di righe, colonne e caratteri. Esporta una copia modificabile in GeoPackage prima di usarla per il salvataggio.

### Se esistono già coordinate

Seleziona X=longitudine e Y=latitudine solo quando le colonne contengono realmente coordinate geografiche. Per WGS84 decimale scegli EPSG:4326. Se contengono Est/Nord UTM, indica il CRS originale corretto. Un numero come 500000 non è una longitudine in gradi. Non sovrascrivere coordinate storiche senza conservarne una copia.

### Excel e altri formati

Puoi preparare i dati in Excel e salvare il foglio utile come CSV UTF-8. Prima di esportare, risolvi celle unite, titoli su più righe, formule non calcolate e colonne miste testo/numero. Aprendo un foglio supportato direttamente in QGIS, controlla comunque che il provider permetta la modifica; per il lavoro usa la copia GeoPackage.

### Importare layer e DEM

- **GeoPackage:** dal Browser di QGIS espandi il file e aggiungi i layer necessari; un file può contenere più tabelle.
- **Shapefile:** estrai tutto il pacchetto, mantenendo insieme almeno .shp, .shx, .dbf e il riferimento .prj quando fornito. Aggiungi il .shp.
- **GeoTIFF/DEM:** usa **Aggiungi layer raster** o trascina il file nel progetto. Controlla il valore di quota con gli strumenti QGIS.
- **Servizi web:** WFS può fornire elementi vettoriali; WMS/WMTS forniscono immagini per la consultazione e non sostituiscono un vettore con attributi o un raster di quote utilizzabile dal motore.

Una volta aggiunti i dati, controlla **Proprietà layer > Informazioni/Sorgente**: formato, CRS, estensione, numero degli elementi e nomi dei campi. Se la mappa è fuori posizione, risolvi il CRS prima dell'analisi. I capitoli su fonti dei layer e CRS forniscono i criteri di scelta.

## 5. Tabella record e campi input
### Colonne da preparare prima del caricamento

I seguenti nomi sono una convenzione consigliata, non un obbligo. La colonna quota del cartellino va tenuta distinta dalla quota DEM prodotta dal plugin.

| Nome suggerito | Tipo | Contenuto |
| --- | --- | --- |
| record_id | Testo | ID stabile e univoco, per esempio DEMO-001 |
| scientific_name | Testo | Nome scientifico verificato |
| municipality | Testo | Comune del record |
| locality | Testo | Descrizione della località, mantenendo l'originale |
| substrate | Testo | Roccia, suolo, corteccia, legno morto, muschio, se documentati |
| rock_type / tree_type | Testo | Litologia e/o forofita indicate dal cartellino |
| quota_cartellino | Decimale | Quota originale in metri, se disponibile |
| notes | Testo | Altre informazioni e interpretazioni separate dall'originale |

Specie e almeno comune o località sono necessari per il percorso normale. Avere entrambi comune e località riduce le ambiguità. Non riempire i dati mancanti con valori arbitrari.

Mantieni il testo originale e le interpretazioni separati; verifica nomi dei taxa e unità della quota.

### Colonne di uscita facoltative da predisporre

Puoi predisporre i campi decimali **longitude**, **latitude**, **quota_dem**, **inc_loc_m** e **inc_geo_m**, lasciandoli NULL. Non usare campi testo o interi. Prevedi almeno sei decimali per le coordinate geografiche, senza confonderli con una garanzia di accuratezza.

Puoi anche usare **Crea le colonne mancanti** nella conferma; il percorso automatico può crearle. Verifica il CRS della sorgente prima di interpretare X/Y come gradi WGS84.

### Configura campi input

Premi **Configura campi input**, associa ogni voce alla colonna giusta e verifica le proposte automatiche. Per **Quota** usa quota_cartellino, non quota_dem. Lascia vuote le associazioni non disponibili. Conferma con **OK** e salva il progetto: il mapping viene conservato per sorgente.

### Selezionare la riga corretta

1. Scegli la sorgente nel menu **Tabella record**.
2. Apri la tabella attributi e seleziona **una sola riga** con la selezione degli elementi QGIS; il semplice cursore in una cella può non costituire una selezione.
3. Controlla il messaggio operativo del pannello: deve riportare la tabella giusta e una riga selezionata.

Se più tabelle hanno righe selezionate, scegli esplicitamente la sorgente nel menu. Il plugin segue anche le selezioni nelle finestre attributi separate. Per l'analisi serve una sola riga; la selezione multipla è prevista invece nel flusso di copia.

## 6. Dove trovare i layer e quali campi usare
### Dove trovare dati utilizzabili

Per un progetto in Lombardia parti dal **Geoportale della Lombardia**, sezione catalogo/download. Cerca il titolo del dataset, apri i metadati, controlla estensione, scala, data e CRS, poi scarica il formato disponibile. Per altre regioni usa il corrispondente geoportale regionale; verifica anche i prodotti del Servizio Geologico ISPRA. I nomi dei campi cambiano tra enti ed edizioni.

| Dato | Fonte e termini di ricerca | Campo da verificare |
| --- | --- | --- |
| Geologia | Geoportale: Carta geologica 1:250.000 o fogli CARG; ISPRA CARG-GATE per disponibilità e copertura | Descrizione litologica; esempi riconosciuti: LITOLOGIA, DESCRIZIONE, LITHOLOGY, GRUPPO_LITO |
| Suolo | ERSAF e Geoportale: Basi Informative dei Suoli, carte 1:50.000/1:250.000 secondo copertura | pH misurato/classe di reazione; esempi: ph, ph_h2o, reazione. Un ID di unità non è un pH |
| Alberi/bosco | Regione Lombardia: Carta forestale (perimetro del bosco) e tipi forestali | Descrizione del tipo forestale o specie; esempi generici: tipo, nome, descrizione |
| Accessibilità | Geoportale: Catasto sentieri della Rete Escursionistica Lombarda (REL); altre reti ufficiali disponibili; OSM tramite il plugin | Geometrie di percorsi pertinenti; nel box Accessibilità si selezionano i layer, senza una scelta obbligatoria del campo |
| Quote | Geoportale: DTM 5 m/20 m o altro DTM/DEM documentato per l'area | Raster con banda altimetrica; non una ortofoto o una tavola a colori |
| Fasce vegetazionali | Cartografia vegetazionale documentata; la Carta fitoclimatica d'Italia nel catalogo RNDT è una fonte da valutare, non una conversione automatica in fasce | Campo con significato della fascia, per esempio vegetation_belt o una descrizione decodificata |

### Collegamenti di partenza

- [Geoportale Lombardia: catalogo](https://www.geoportale.regione.lombardia.it/home/-/wiki/Main/FrontPage) e [servizi di download/OGC](https://www.geoportale.regione.lombardia.it/servizi).
- [ERSAF: cartografia dei suoli](https://www.ersaf.lombardia.it/territorio/cartografia-dei-suoli/).
- [Regione Lombardia: cartografia forestale](https://www.regione.lombardia.it/agricoltura/boschi-e-foreste/gestione-del-bosco-pianificazione-forestale/la-cartografia-forestale-regionale).
- [Regione Lombardia: Rete Escursionistica Lombarda](https://www.regione.lombardia.it/ambiente-e-territorio/montagna/la-rete-escursionistica-della-lombardia-e-le-strade-di-montagna-di-interesse-storico).
- [ISPRA: CARG-GATE](https://www.isprambiente.gov.it/Media/carg/index.html).


La [scheda RNDT della Carta fitoclimatica d’Italia](https://geodati.gov.it/resource/id/m_amte%3A299FN3%3A2b8ed8fd-6ae1-4594-cd25-405c36569685) consente di risalire al produttore e ai servizi dichiarati. Verifica disponibilità attuale, legenda e corrispondenza con le fasce richieste.
## 7. Configurare i layer nel plugin
Carica prima i tuoi dati nel progetto, poi scegli layer e campi nei box di configurazione. Un nome di layer non garantisce che il campo selezionato contenga l'informazione richiesta: controlla la tabella attributi e la legenda della fonte.

### Collegare i dati

1. Carica il layer e controlla CRS, copertura e legenda.
2. Nel box corrispondente scegli il layer appena controllato.
3. Scegli il campo descrittivo o numerico pertinente, usando i criteri del capitolo 6.
4. Per Accessibilità seleziona i layer utili; per i DEM spunta e ordina i raster.
5. Esegui una prova e leggi la diagnostica: la presenza nella lista non garantisce un confronto valido.

### Litologia e acidità

Il riconoscimento litologico usa regole integrate per descrizioni italiane e inglesi. **Crea / aggiorna GRUPPO_LITO** scrive una classificazione nel layer geologico ed è facoltativo: l'interpretazione durante l'analisi non richiede sempre la creazione di quel campo.

Le categorie ecologiche calcareo, siliceo e misto non equivalgono a una classificazione petrologica completa delle rocce acide e basiche. La litologia non costituisce una misura diretta del pH del suolo.

Per il suolo sono gestiti valori pH e classi testuali riconosciute, anche in inglese, come acidic, neutral e alkaline. Le regole non possono attribuire significato a qualsiasi codice di una carta: scegli un campo interpretabile e controlla la diagnostica.

### DEM e sentieri

Ordina i DEM dall'alto in base alla priorità desiderata. In mancanza di un campione valido il sistema può cercare nei DEM successivi; se nessuno fornisce un valore, la quota resta non disponibile.

**Usa dati sentieristici OpenStreetMap** integra dati richiesti tramite Overpass, fra cui path, track e footway. Non sono automaticamente dati ufficiali di un ente sentieristico. **Mostra layer OSM scaricato** ne controlla la visualizzazione. Layer locali e OSM possono avere coperture e qualità diverse.


### Decodifica e qualità dei campi



Apri la tabella attributi e leggi alcuni valori. Se trovi solo codici, usa la legenda o la tabella di decodifica della stessa fonte e prepara un campo descrittivo conservando il codice originale. L'eventuale join va controllato per chiave, duplicati e NULL; non assegnare la stessa litologia o reazione a tutte le unità per far funzionare il menu.

Una carta dei suoli può non esporre un pH puntuale né coprire l'intera area: non va sostituito con il numero dell'unità pedologica. Per il pH documenta metodo analitico e orizzonte del suolo quando noti. Un tipo forestale non identifica necessariamente la forofita del campione.

**DUSAF** descrive uso/copertura del suolo: non è di per sé una carta di pH o di fasce altitudinali. Il pannello non presenta un ingresso universale DUSAF/habitat. Non selezionarlo al posto di una fascia vegetazionale senza una trasformazione documentata e coerente con il campo richiesto.

La scala della fonte limita il dettaglio informativo: una griglia da 10 m non rende una carta 1:250.000 precisa a 10 m. I layer devono contenere dati interrogabili e CRS corretti, non solo essere visibili sulla mappa.

## 8. Sistemi di riferimento e codici EPSG
### Tre CRS da distinguere

Il **CRS del progetto** riguarda visualizzazione e strumenti QGIS. Il **CRS della sorgente** descrive le coordinate effettive del layer. Il **CRS di esportazione** riguarda il file che produci. Cambiare il CRS del progetto non converte automaticamente le colonne numeriche già esistenti.

| EPSG | Sistema / unità | Impiego e cautela |
| --- | --- | --- |
| 4326 | WGS84, gradi | Longitudine/latitudine geografiche e layer cumulativo dei punti confermati; nel caricamento XY usa X=longitudine, Y=latitudine |
| 32632 | WGS84 / UTM 32N, metri | Lavoro metrico per aree comprese nel fuso 32, da 6 a 12 gradi Est, inclusa la Lombardia |
| 32633 | WGS84 / UTM 33N, metri | Lavoro metrico nel fuso adiacente, da 12 a 18 gradi Est; per aree oltre tale intervallo scegli il fuso pertinente |
| 25832 | ETRS89 / UTM 32N, metri | Dati dichiarati in questo riferimento europeo; non rinominare come WGS84 senza trasformazione |
| 3003 | Monte Mario / Italy zone 1, metri | Dati italiani storici/territoriali che lo dichiarano; richiede la trasformazione geodetica appropriata |
| 3857 | WGS84 / Pseudo-Mercator | Comodo per sfondi web; non è il riferimento da usare come se garantisse distanze e superfici locali esatte |

### Impostazione pratica per un progetto in Lombardia

Puoi visualizzare e lavorare nel progetto in **EPSG:32632**, mantenendo i layer nei loro CRS documentati. QGIS esegue le trasformazioni a video e GeoLichen usa trasformazioni metriche locali per i propri calcoli. Per un risultato geografico da condividere, esporta i punti in **EPSG:4326**.

Se vuoi che i campi longitude/latitude della sorgente puntuale ricevano gradi WGS84 durante l'analisi ecologica, prepara e usa una copia del layer in EPSG:4326. Puoi tenere contemporaneamente il progetto in EPSG:32632: progetto e sorgente non devono avere necessariamente lo stesso CRS.

### Assegnare non significa riproiettare

**Assegna/Imposta CRS** dichiara il significato delle coordinate esistenti; non ne cambia i numeri. Usalo per correggere un'informazione mancante solo se conosci il CRS reale. Per trasformare le geometrie usa **Esporta > Salva elementi come...**, scegli il CRS di destinazione, oppure l'algoritmo **Riproietta layer**.

La riproiezione delle geometrie non aggiorna necessariamente vecchi attributi X/Y. Ricalcola o esporta nuove coordinate dalla geometria trasformata, oppure usa i campi WGS84 del layer confermato. Non etichettare come longitude/latitude numeri UTM.

Per un DEM preserva il CRS e il riferimento altimetrico documentati. La quota verticale non è stabilita dal solo EPSG orizzontale: verifica metri, datum verticale, NoData e differenza fra terreno e superficie. Non è necessario ricampionare tutti i raster solo per uniformarli al progetto.

## 9. Ricerca della località e centroide
1. Seleziona una sola riga nella **Tabella record** corretta.
2. Premi **Ricerca della località**.
3. La finestra **Seleziona località** si apre anche con un solo candidato. Confronta nome, tipo, centro, distanza dal comune e motivo; scegli la località e premi **Crea buffer**, oppure usa il doppio clic. **Annulla** consente di passare agli strumenti manuali.
   Puoi correggere il nome e usare **Cerca altre località**. La ricerca nella zona iniziale della mappa usa l'inquadratura precedente all'anteprima, entro l'area configurata. Un risultato parziale non è una conferma del toponimo.
   L'archivio delle località confermate conserva soltanto riferimenti accettati esplicitamente: consulta [ricerca e archivio](LOCALITY_SEARCH_15_6_26.md).
4. Osserva sulla mappa l'area di ricerca ottenuta e confrontala con cartellino e cartografia.
5. Controlla il riepilogo di superficie del buffer, raggio di riferimento e passo della griglia.

Tutte le località ricercate usano un buffer circolare metrico sul punto scelto, anche laghi e aree: il contorno o il rettangolo del geocoder non diventano l’area di ricerca. Il raggio dipende dal tipo di località; per laghi e laghetti è 300 m.

La posizione proposta dal geocoder identifica un elemento geografico; non dimostra da sola la posizione di raccolta. Il punteggio della scelta della località non è il GSS ecologico dei candidati.

### Se l'area non è adatta

Rivedi area geografica e contenuto del record oppure usa **Punto e linea manuali** per definire un'area più coerente. Cambiare geometria invalida i candidati e la superficie dell'analisi precedente; i punti già confermati sono mantenuti.

Cambiando riga, i risultati della riga precedente non diventano utilizzabili sul nuovo record. Ripeti il percorso per il record corrente.

### Concludere al centroide

Il pulsante con **mirino e badge verde**, accanto a **Ricerca della località**, corrisponde a **Sono a posto così**. Calcola il centroide dell'area e ne campiona la quota DEM, senza eseguire il ranking ecologico per questa azione.

Nella finestra **Centroide della località** controlla longitudine, latitudine e quota. Puoi scegliere colonne di destinazione facoltative e premere **Salva centroide**, oppure annullare. Il punto viene aggiunto al layer dei punti confermati anche se non scegli colonne della tabella.

Il centroide è una rappresentazione geometrica dell'area, non il punto ecologicamente migliore. Per aree concave o composte controlla la sua posizione effettiva sulla mappa. Le incertezze ecologiche e il GSS non vengono calcolati da questo percorso.

## 10. Geometrie manuali, griglia e heatmap
### Punto manuale

Apri **Punto e linea manuali**, inserisci il raggio in metri e premi **Punto manuale + buffer**. Clicca sulla mappa per il nuovo centro e segui le eventuali conferme proposte. Per annullare il disegno usa il comando di annullamento mostrato dal pulsante o i messaggi operativi.

### Linea manuale

Inserisci l'**Offset (m)** e premi **Linea manuale + offset**. Aggiungi almeno due vertici con clic sinistro; termina con clic destro. L'offset è la distanza **per lato** della linea: non è la larghezza totale del corridoio. Terminare senza almeno due vertici annulla il disegno.

Il corridoio segue il percorso tracciato; non equivale a un buffer circolare sul suo punto medio. Alcuni passaggi della procedura manuale possono già avviare elaborazioni: leggi lo stato nel pannello prima di lanciare un'altra azione.

### Passo automatico

Il passo non è un parametro modificabile nel pannello. La scelta usa il raggio corrente, l'offset per una linea o un raggio di riferimento per geometrie automatiche irregolari.

| Raggio / offset di riferimento | Passo base |
| --- | --- |
| Fino a 250 m | 10 m |
| Oltre 250 m e fino a 1.000 m | 30 m |
| Oltre 1.000 m e fino a 3.000 m | 50 m |
| Oltre 3.000 m | 100 m |

Le soglie valgono anche per distanze decimali. Le località ricercate usano cerchi; per altre geometrie ammesse il riferimento può essere ricavato dalla loro estensione metrica. Possono esistere raffinamenti locali più fini del passo base. Il limite di dimensione del raster può influire sulla risoluzione effettiva della superficie in aree estese.

### Visualizzazione

- **Punti candidati:** mostra i campioni valutati.
- **Suitability Surface:** visualizza una heatmap dell'idoneità ecologica nell'area di ricerca.
- **Entrambi:** mostra punti e superficie.

La superficie è derivata dai campioni validi ed è limitata all'area di ricerca. Non è una probabilità di presenza della specie. Lo zoom adatta la resa dei colori con ricampionamento; non ricalcola griglia, ranking o incertezze e non aggiunge nuova informazione.

## 11. Analisi ecologica guidata e automatica
### Che cosa esegue il calcolo

Il motore usa l'area del record corrente e le evidenze già disponibili. Definisce la griglia, campiona i dati pertinenti (fra cui il DEM), confronta i candidati con vincoli del cartellino e requisiti ecologici riconosciuti e applica i filtri previsti dal percorso. Combina Geografia, Terreno, Ambiente e Accessibilità nel GSS, ordina i candidati e prepara i layer di visualizzazione. Raffinamenti locali possono aggiungere campioni nelle zone promettenti.

La scelta guidata prevede quindi un controllo umano della località, dell'area e del punto. Le finestre successive permettono di leggere diagnostica, incertezze e colonne di destinazione prima della scrittura. Nessuna fase garantisce la posizione reale in assenza di un riferimento indipendente.

### Percorso step by step

1. Parti da un'area di ricerca valida per la riga corrente e premi **Analisi ecologica step by step**.
2. Attendi la generazione e la valutazione della griglia.
3. Nella finestra **Scelta del punto ecologico**, premi **Avanti** per scegliere sulla mappa oppure **Cancel** per interrompere senza confermare un punto.
4. Clicca vicino al candidato desiderato. Il cursore si aggancia a un punto già calcolato; non crea un campione arbitrario nel punto del clic. Per consentire la scelta, i candidati sono mostrati anche se avevi selezionato solo la superficie.
5. Leggi **Vuoi usare questo punto di rank ...?**, con GSS e distanza dal clic.
6. Scegli **Sì** per aprire **Usa questo candidato**, **Riprova** per scegliere un altro punto sulla stessa griglia o **Esci** per terminare la scelta.
7. Controlla e conferma i valori nella finestra candidato, come descritto nel capitolo 12.

**Sì nel riepilogo del rank non salva ancora il punto:** apre la finestra candidato. È **Usa questo candidato** nella finestra successiva a confermare la scrittura.

Riprova non ripete il ranking. Durante la scelta del candidato, **Esc** e **clic destro** interrompono la cattura senza scrivere dati; questa funzione del clic destro è diversa dal termine del disegno di una linea manuale.

### Percorso automatico

**Analisi ecologica automatica** avvia una nuova ricerca per l'unica riga selezionata. Scegli la località corretta quando richiesto; poi il plugin calcola la griglia, seleziona il rank 1 e scrive direttamente coordinate, quota e incertezze. Le colonne mancanti vengono create se il formato lo consente.

Non occorre cliccare un candidato o accettare la finestra candidato. L'automatismo riguarda la scelta del punto, non un'elaborazione in serie di tutte le righe. Il risultato salvato viene reso visibile sulla mappa anche in modalità superficie.

Annullamento della località, errore di analisi, assenza di un rank 1 univoco o cambio della riga interrompono il salvataggio. Controlla sempre il messaggio finale e i valori nella tabella.

## 12. Confermare il candidato e creare le colonne
La finestra **Usa questo candidato** lascia visibili i dati da scrivere. La sezione **Dettagli del risultato, GBIF e incertezza** è inizialmente chiusa e si apre con la freccia.

### Campi da controllare

| Valore | Significato |
| --- | --- |
| Coordinate X / Y | Coordinate proposte e relative colonne di destinazione |
| Quota DEM | Campione altimetrico disponibile per il candidato |
| Incertezza località | Misura geografica della località, con metodo point-radius |
| Incertezza GeoLichen | Raggio descrittivo della distribuzione dei candidati del modello |

Scegli una colonna diversa per ogni valore. Se mancano i campi, **Crea le colonne mancanti** aggiunge quelli necessari e li propone nella finestra. I nomi predefiniti sono `longitude`, `latitude`, `quota_dem`, `inc_loc_m` e `inc_geo_m`; eventuali campi esistenti riconosciuti vengono riutilizzati.

**La creazione delle colonne modifica la struttura della tabella anche se annulli successivamente la conferma del punto.** Se la tabella era già in modifica, l'aggiunta resta fra le modifiche da salvare in QGIS. Un formato non modificabile richiede una copia GeoPackage.

### Coordinate e sistema di riferimento

Nella conferma ecologica e nella copia, X/Y seguono il CRS valido della sorgente/destinazione; il punto cumulativo e le sue coordinate geografiche sono conservati in WGS84. Il percorso del centroide mostra e propone longitudine/latitudine WGS84.

Il nome di una colonna, da solo, non ne certifica il sistema di riferimento. Su un layer proiettato, campi chiamati `longitude` e `latitude` possono ricevere X/Y proiettate nel percorso ecologico: verifica CRS, unità e destinazione prima di esportare coordinate geografiche. Non usare automaticamente i valori visualizzati nella barra di stato di QGIS.

### Scrittura

Premi **Usa questo candidato** per validare i valori e salvare. Il plugin aggiorna anche la geometria della sorgente quando si tratta di un layer puntuale. Se la tabella era già in modifica, salva poi le modifiche del layer con QGIS.

Annullare chiude la conferma senza scrivere i valori del candidato. La quota non disponibile resta vuota/NULL; non deve essere interpretata come quota zero.

## 13. Leggere il profilo ITALIC
Apri la sezione **Profilo ITALIC** dopo la ricerca/lettura del record. Il plugin consulta ITALIC per associare al taxon informazioni ecologiche e diagnostica. Non devi creare un'altra API key ITALIC nel pannello.

### Che cosa leggere

| Voce | Uso |
| --- | --- |
| Taxon ITALIC | Nome della specie restituito dal servizio |
| Substrata | Supporti ecologici riportati per la specie |
| Roccia / Albero | Preferenze riconosciute dal profilo, quando disponibili |
| Note ecologiche | Testo ecologico e informazioni diagnostiche sull'associazione del nome |
| Fonte | Riferimento alla scheda del taxon |

Nel testo possono comparire nome di input, nome normalizzato, corrispondenza trovata, nome accettato, stato nomenclaturale e ID del taxon. Servono a capire se un sinonimo o una grafia diversa sono stati associati alla specie attesa. Non correggere automaticamente la determinazione del campione solo perché il servizio propone un nome.

### Indicatori e limiti

ITALIC pubblica intervalli ecologici su scale ordinali per fattori come reazione del substrato, luce, aridità ed eutrofizzazione. Un valore ordinale 1-5 non è una misura di pH in laboratorio. La disponibilità e la conoscenza dei profili variano fra taxa; un campo vuoto non dimostra assenza di una preferenza.

Il profilo è una fonte di requisiti/fallback per il motore. Non è un macroscore autonomo, non prova la presenza della specie nel candidato e non sostituisce le osservazioni del cartellino. Le indicazioni originali esplicite del record hanno priorità nel percorso previsto dal plugin.

Caricare un profilo con un'indicazione di umidità o luce non significa che QGIS abbia misurato umidità o luce in ogni punto. Per contribuire come confronto serve anche l'evidenza pertinente disponibile dal motore/layer; guarda spiegazione e dati mancanti.

### Se il profilo non arriva

Controlla il nome scientifico e la connessione, poi esamina la diagnostica e la [scheda ITALIC](https://italic.units.it/). In assenza di un profilo valido non inventare preferenze per aumentare il punteggio. Il plugin può usare le altre evidenze disponibili, ma occorre interpretare i risultati alla luce dell'informazione mancante.

Per il significato generale degli indicatori consulta la [guida ITALIC](https://italic.units.it/key-maker/info). Questa guida descrive le scale ecologiche; non prescrive i pesi di GeoLichen.

## 14. Come viene composto il GSS
Il punteggio ufficiale è la media pesata di quattro macroscore, ciascuno con peso del 25%. ITALIC fornisce preferenze e contesto ecologico; non è un quinto macroscore autonomo.

| Macroscore | Informazione principale | Peso nel GSS |
| --- | --- | --- |
| Geografia | Coerenza con località, contesto e toponimo | 25% |
| Terreno | Confronto altitudinale, esposizione e pendenza | 25% |
| Ambiente | Substrato, litologia, reazione del suolo, habitat, supporto arboreo pertinente | 25% |
| Accessibilità | Distanze dai percorsi, con dato mancante neutro (dalla 15.6.23) | 25% |

Nel Terrain i rapporti interni sono 20:5:5 per quota, esposizione e pendenza: circa 66,67%, 16,67% e 16,67% del macroscore. Non sono percentuali aggiuntive da sommare ai quattro pesi principali.

### Un esempio numerico di aggregazione

Se i quattro macroscore fossero rispettivamente 90, 80, 70 e 60, il GSS sarebbe (90 + 80 + 70 + 60) / 4 = 75. È solo un esempio aritmetico: non un risultato misurato. Lo score geografico del ranking ecologico non coincide necessariamente con il punteggio mostrato nella scelta iniziale del geocoder.

Dalla 15.6.23 l'accessibilità usa le distanze dai percorsi; la coerenza con la località rimane solo nel macroscore geografico. Un punto lontano da un percorso può restare candidato. La rete odierna non prova quale sentiero esistesse alla data storica di raccolta.

### Ambiente: pesi interni per gruppo

| Gruppo | Substrato | Litologia | pH | Habitat | Alberi/bosco |
| --- | --- | --- | --- | --- | --- |
| Sassicolo | 37,50 | 37,50 | 0 | 25,00 | 0 |
| Terricolo | 31,58 | 15,79 | 26,32 | 26,32 | 0 |
| Muscicolo | 38,89 | 11,11 | 16,67 | 33,33 | 0 |
| Epifita | 0 | 0 | 0 | 25,00 | 75,00 |
| Lignicolo | 0 | 0 | 0 | 35,00 | 65,00 |
| Sconosciuto | 42,86 | 28,57 | 0 | 28,57 | 0 |

I valori sono percentuali del solo macroscore Ambiente, arrotondate per la lettura. La qualità dell'evidenza riduce il peso effettivo; la parte non supportata resta neutra a 50. Un dato mancante non aumenta i pesi degli altri indizi. La copertura e il contributo neutro sono disponibili nella spiegazione del risultato.

### Che cosa significa habitat

È un confronto fra requisiti riconosciuti e osservazioni pertinenti disponibili. Può usare copertura forestale o umidità effettivamente ricavate dal motore; il solo caricamento di un layer non dimostra un confronto riuscito. Bosco, litologia e quota non sono misure dirette di luce, microclima, legno morto o presenza di muschi.

I gruppi non legnosi non ricevono un bonus arboreo fisso. Il pH del suolo non misura il pH della corteccia o della superficie rocciosa. I pesi e i coefficienti di qualità sono regole del modello da validare con coordinate indipendenti, non valori prescritti da ITALIC o GBIF.

## 15. Leggere indicatori e incertezze
Apri i dettagli del candidato per leggere rank, GSS, diagnostica e incertezze. Sono misure diverse: non vanno sostituite l'una con l'altra.

| Indicatore | Cosa descrive | Cosa non dimostra |
| --- | --- | --- |
| Rank | Ordine dei candidati nell'analisi corrente | Posizione esatta di raccolta |
| GSS (0-100) | Compatibilità del candidato con le evidenze usate | Probabilità percentuale che il record sia nel punto |
| MCI | Distinzione del punto dalle alternative e informazione disponibile | Probabilità calibrata di correttezza |
| SSI | Concentrazione in cluster delle soluzioni ecologicamente simili | Accuratezza rispetto a una posizione reale nota |

### MCI e SSI insieme

MCI combina distacco di punteggio, concentrazione spaziale, completezza dei dati, precisione della località, confidenza di classificazione e unicità ecologica. Un confronto mancante non diventa un'osservazione solo perché esiste una preferenza ITALIC.

SSI considera le soluzioni simili al punto scelto e il cluster che lo contiene: compattezza, quota di soluzioni raccolte nello stesso nucleo e separazione da altri nuclei. È una descrizione della struttura dei risultati, non un test ottenuto ripetendo l'analisi con dati o parametri perturbati.

**Esempio interpretativo:** molti candidati vicini con GSS quasi uguale possono dare SSI alto e MCI basso. La zona è coerente, ma i dati distinguono poco il singolo punto migliore. Non trasformare la percentuale SSI in un raggio di errore.

### Due incertezze distinte

**Incertezza località** deriva dalla geometria e dalle informazioni geografiche della località secondo l'implementazione point-radius del plugin. Controlla centro corretto, estensione e componenti disponibili nella diagnostica. La dicitura GBIF indica il riferimento metodologico, non una certificazione o validazione del singolo risultato da parte di GBIF.

**Incertezza GeoLichen** descrive la dispersione locale dei candidati compatibili, con pesi di punteggio e distanza. Non sostituisce `coordinateUncertaintyInMeters` e non va esportata automaticamente in quel campo.

L’incertezza GeoLichen è indicata **R55–S65**: il servizio usa una soglia di compatibilità del **65%** del punteggio scelto e una copertura del **55% del peso**. Il raggio dipende anche dalla risoluzione della griglia e dalla distribuzione delle distanze. Le colonne storiche R55/S70 restano riconosciute senza rinomina automatica.

## 16. Copiare un punto su altri record
Il flusso riutilizza coordinate, quota e incertezze di un punto già confermato. Non ricalcola il GSS né l'idoneità ecologica delle righe destinatarie.

1. Nel pannello scegli la **Tabella record** che deve ricevere i dati.
2. Premi **Copia su altri record**.
3. Nella prima finestra cerca e seleziona il punto sorgente. Premi **Copia questo punto** per proseguire: non è ancora la scrittura sulle righe finali.
4. Nella finestra di destinazione seleziona manualmente una o più righe. Usa **Ctrl** su Windows o **Cmd** su macOS per righe non contigue; usa **Maiusc** per un intervallo.
5. Controlla il numero di righe selezionate e i campi disponibili. Se necessario premi **Crea le colonne mancanti**.
6. Premi **Continua**, leggi il riepilogo finale e conferma la copia.
7. Verifica tabella e layer dei punti confermati; salva le eventuali modifiche pendenti.

### Filtri e selezioni

**Mostra solo righe con la stessa località e lo stesso comune** è un filtro della lista: ignora maiuscole e spazi ripetuti, ma non riconosce necessariamente sinonimi o tutte le varianti del toponimo. Puoi disattivarlo e usare la ricerca per record, taxon, località o comune.

Il filtro non seleziona da solo le righe simili. Eventuali righe già selezionate nella tabella possono essere riportate se visibili; controlla il conteggio. Le righe nascoste dai filtri sono escluse dalla selezione di copia. La selezione originale della tabella QGIS non viene modificata dal dialogo.

Se compare una sola riga, può essere l'unica corrispondenza rimasta dopo il filtro, escluso il record sorgente. Disattiva il filtro o cambia la ricerca per vedere altre destinazioni.

### Quando è appropriato

Riusa il punto solo quando hai motivi documentati per attribuire ai record la stessa georeferenziazione. La coincidenza testuale della località non dimostra identità del punto di raccolta, e una specie diversa può avere requisiti ecologici diversi. Il riepilogo segnala le differenze rilevate di taxon e località/comune.

## 17. Esempio A: elaborare una riga passo per passo
**Esempio didattico, non una raccolta documentata.** Usiamo una riga con ID DEMO-001, specie Cladonia rangiferina, comune Breno, località dintorni del Passo di Crocedomini, substrato suolo e quota_cartellino 1900 m. La combinazione serve a illustrare i comandi: non attesta che quel taxon sia stato raccolto lì.

### A. Prepara e importa

1. Inserisci i dati del record nelle colonne descritte nel capitolo sulla tabella. Lascia vuoti longitude, latitude, quota_dem e incertezze se non conosci i risultati.
2. Importa il CSV senza geometria, oppure usa la tua tabella/layer esistente. Esporta la copia modificabile **record_lavoro** in un GeoPackage. Controlla che la copia contenga la riga DEMO-001.
3. Carica DEM e layer ambientali pertinenti. Nel progetto lombardo puoi usare EPSG:32632 per la visualizzazione. Se la sorgente è puntuale e vuoi X/Y geografiche, usa una sua copia correttamente riproiettata in EPSG:4326.
4. In **Tabella record** scegli record_lavoro. Configura scientific_name, municipality, locality, substrate e quota_cartellino nei rispettivi input. Controlla che la quota non sia associata al campo di uscita quota_dem.

### B. Definisci l'area

5. Scegli Lombardia, verifica il servizio Photon e seleziona soltanto DEMO-001.
6. Premi **Ricerca della località**. Se compaiono più proposte, confrontale con il cartellino e conferma quella pertinente; non scegliere in base al solo ordine della lista.
7. Osserva il buffer. Se l'area automatica è poco adatta e hai un riferimento migliore, usa il punto manuale con raggio 250 m. Per un cerchio di tale raggio il riepilogo sarà circa 19,6 ha e il passo base 10 m; eventuali filtri e raffinamenti influenzano poi i candidati validi.

### C. Analizza e salva

8. Scegli **Entrambi** per confrontare punti e Suitability Surface. Premi **Analisi ecologica step by step**, attendi la griglia e premi **Avanti**.
9. Clicca il candidato desiderato. Leggi rank, GSS e distanza dal clic; usa **Riprova** per confrontare un altro campione senza ricalcolo.
10. Premi **Sì**, controlla la finestra candidato, crea o scegli le colonne e premi **Usa questo candidato**. Non premere il comando automatico per completare questo percorso: sarebbe un'altra analisi.
11. Riapri DEMO-001 nella tabella: verifica coordinate, quota DEM e le due incertezze. Se manca la quota non trasformare il NULL in zero. Salva le modifiche del layer e il layer dei punti confermati su file.

### Come leggere un possibile risultato

Se in una tua prova compaiono, per esempio, GSS 80, MCI basso e SSI alto, non hai una probabilità di correttezza dell'80%. Il candidato è compatibile con le evidenze e appartiene a un nucleo coerente, ma può essere poco distinguibile dai vicini. I numeri di questa frase sono illustrativi: i valori reali dipendono da area, layer, profilo e versione del modello.

## 18. Esempi B e C: manuale, automatico e copia
### Esempio B: il toponimo non viene trovato

Considera una riga DEMO-002 con un nome storico leggibile sul cartellino ma assente dal geocoder. Non scegliere un'altra località omonima distante solo per ottenere un buffer.

1. Verifica grafia, comune, area geografica e chiave API. Se il toponimo è di confine, valuta l'espansione e controlla i nuovi risultati.
2. Se non risolvi, usa una fonte cartografica documentata per individuare il riferimento sulla mappa. Tieni traccia dell'interpretazione e della fonte; non inventare un centro senza evidenze.
3. Scegli **Punto manuale + buffer** e un raggio giustificato, per esempio 500 m nell'esempio. Il passo base sarà 30 m. In alternativa traccia un percorso con **Linea manuale + offset**: un offset di 100 m significa 100 m per lato e determina un passo base di 10 m.
4. Se vuoi solo una rappresentazione dell'area, premi l'icona del centroide, controlla i dati e **Salva centroide**. Non avrai un GSS né un'incertezza ecologica da questo percorso.
5. Se vuoi confrontare le evidenze ecologiche nell'area manuale, usa invece il percorso step by step. Cambiare dal vecchio buffer a quello manuale invalida i precedenti candidati.

Se non hai nemmeno una base geografica per localizzare il riferimento, lascia il record da approfondire: il disegno manuale non risolve la mancanza di documentazione.

### Esempio C: scelta automatica e successiva copia

1. Scegli e seleziona una sola riga, per esempio DEMO-003, e verifica campi, chiave e layer.
2. Premi **Analisi ecologica automatica** e scegli la località corretta quando richiesto. Il plugin svolge ricerca, griglia, scoring, scelta del rank 1 e scrittura; non richiede la finestra candidato.
3. Controlla i cinque valori nella tabella e il punto visibile. Le colonne mancanti possono essere create automaticamente. Salva le modifiche pendenti.
4. Per un altro record che documenti lo stesso punto, premi **Copia su altri record**, scegli il punto confermato di DEMO-003 e poi le destinazioni. Usa Ctrl/Cmd e verifica il conteggio.
5. Premi **Continua**, leggi il riepilogo e conferma. La copia non è un nuovo calcolo dell'ecologia dei destinatari, nemmeno quando hanno un taxon diverso.

Prima di copiare, documenta perché i record condividono la stessa posizione. Se condividono solo un toponimo esteso, la stessa coordinata può non essere appropriata.

## 19. Esportare i dati che servono
### Esportare i soli dati che servono

Per i punti confermati: clic destro sul layer **GeoLichen - Punti confermati > Esporta > Salva elementi come...**. Scegli **GeoPackage**, percorso e nome del layer. Se vuoi solo alcuni risultati, selezionali e attiva l'opzione di esportare soltanto gli elementi selezionati. Non attivarla se intendi salvare tutto il lavoro.

Nel dialogo di esportazione puoi scegliere i campi da mantenere. Conserva almeno ID del record, taxon, località/comune, coordinate, quota, due incertezze e metodo di selezione quando disponibili. Mantieni altrove una copia completa con provenienza e diagnostica: un CSV essenziale non sostituisce l'archivio di lavoro.

### Produrre un CSV per Excel o per uno scambio

1. Parti dal layer confermato salvato e scegli **Esporta > Salva elementi come...**, formato **CSV**, codifica **UTF-8**.
2. Per coordinate geografiche esporta in EPSG:4326. Puoi mantenere i campi WGS84 longitude/latitude del layer confermato; se generi X/Y dalla geometria usa l'opzione geometria **AS_XY** prevista dal formato.
3. Controlla in anteprima o riaprendo il file quali colonne sono state esportate, separatore e numeri decimali. Se compaiono sia attributi longitude/latitude sia colonne XY generate, evita di confonderle o duplicarle senza una descrizione.
4. Per una tabella senza geometria esporta i campi già controllati e documenta il loro CRS. La scelta di un CRS nel dialogo non converte, da sola, qualsiasi attributo numerico.
5. Apri il CSV in un importatore di testo/Excel impostando separatore, UTF-8 e tipo testo per gli ID; controlla che le coordinate non siano diventate date o numeri interi.

**Quota e incertezze:** quota_dem, inc_loc_m e inc_geo_m sono campi diversi. Non rinominare inc_geo_m in coordinateUncertaintyInMeters: il raggio del modello non è l'incertezza geografica della località. La quota DEM non garantisce da sola che i requisiti di un'esportazione Darwin Core siano soddisfatti.

Per condividere il progetto trasferisci anche i file delle sorgenti. Per una mappa illustrata puoi esportare un layout QGIS in PDF/immagine; quel prodotto grafico non sostituisce i dati vettoriali o tabellari.

## 20. Salvare e documentare il lavoro
### Chiudere una sessione senza perdere i risultati

1. Controlla nella tabella i valori scritti e il record corrispondente.
2. Salva le modifiche del layer sorgente se è ancora in modalità modifica.
3. Salva su file il layer **GeoLichen - Punti confermati** tramite i comandi QGIS di esportazione degli elementi, preferibilmente in GeoPackage.
4. Salva il progetto QGIS e verifica i percorsi delle sorgenti.
5. Se servono alla documentazione, esporta spiegazioni e risultati dei controlli.

Il layer cumulativo dei punti confermati nasce come **layer in memoria**: salvarne soltanto il progetto non garantisce la conservazione degli elementi. I marker temporanei sulla mappa non sostituiscono un layer salvato. Ripeti l'esportazione quando aggiungi risultati, oppure gestisci consapevolmente la tua sorgente persistente.


### Spiegazione e validazione

Nei dettagli del candidato, **Mostra spiegazione del risultato** apre il report esportabile in JSON, HTML o PDF. **Valida questo risultato** permette di confrontare il punto con coordinate reali note, inserite o scelte sulla mappa, e di aggiungere la verifica a un CSV.

Il menu **Plugins > GeoLichen** contiene anche validazione su CSV, benchmark fra metodi, prestazioni e controlli di rilascio. Richiedono i dati pertinenti forniti dall'utente. Un controllo del pacchetto non equivale a validazione scientifica dei punti.

### Servizi e dati locali

Photon riceve nomi di località/comuni e limiti geografici; ITALIC riceve i nomi dei taxa cercati; Overpass riceve interrogazioni per l’area geografica. Le richieste avvengono durante le operazioni pertinenti e seguono le impostazioni di rete QGIS. Controlla termini, quote e disponibilità dei servizi prima dell'uso.

Cache e snapshot ITALIC sono conservati nel profilo QGIS, nella sottocartella GeoLichen; le cache OSM sono anch'esse locali al profilo. Non sono incluse nello ZIP. Conserva versione del plugin, dati originali, versioni dei layer, CRS, scelte dell'operatore e report per rendere il lavoro verificabile. Copiare lo ZIP su un altro PC non trasferisce i dati o le cache.

## 21. Problemi frequenti
| Problema | Cosa controllare |
| --- | --- |
| "Seleziona una riga nella tabella" | Seleziona un elemento, non solo una cella; controlla Tabella record e il conteggio della selezione |
| Sono selezionate più righe | Riduci la selezione a una riga per l'analisi; usa il flusso di copia per destinazioni multiple |
| Località assente o sbagliata | Connessione e servizio Photon, area, comune/toponimo; distingue timeout da assenza di risultati. Prova ricerca approfondita, archivio o strumenti manuali |
| Profilo ITALIC non disponibile | Nome del taxon, connessione e risposta del servizio; esamina la diagnostica dei dati mancanti |
| Quota vuota | DEM selezionati, priorità, copertura, CRS e celle NoData; non sostituire automaticamente con zero |
| Impossibile aggiungere colonne | Permessi e formato; esporta una copia modificabile in GeoPackage e selezionala come sorgente |
| Copia mostra poche righe | Filtro stessa località/comune, testo di ricerca ed esclusione del record sorgente |
| Dati non ritrovati alla riapertura | Salvataggio delle modifiche del layer e del layer in memoria, non solo del progetto |
| Il plugin non si carica in QGIS 4 | Il port Qt 6 è sperimentale; controlla versione del plugin, errore e matrice di compatibilità |

### Controllo rapido prima di confermare

- Tabella e riga corrette; cartellino letto e località plausibile.
- Buffer/corridoio coerente e passo della griglia noto.
- Layer ambientali e DEM pertinenti, con copertura e significato verificati.
- Punto scelto, quota e coordinate controllati; CRS e colonne di destinazione corretti.
- GSS, MCI, SSI e le due incertezze interpretati separatamente.
- Modifiche della tabella e punti confermati salvati su sorgenti persistenti.

## 22. Glossario e fonti
| Termine | Significato operativo |
| --- | --- |
| Record | Una riga della tabella associata a un'osservazione o campione |
| Cartellino | Fonte originale delle informazioni della raccolta |
| Geocoder | Servizio che propone elementi geografici a partire da un nome o descrizione |
| Buffer | Area attorno a un riferimento; nella guida indica anche l'area di ricerca corrente |
| CRS | Sistema di riferimento delle coordinate, con unità e datum associati |
| DEM | Modello digitale dell'elevazione usato per leggere la quota |
| NoData / NULL | Valore assente o non disponibile, distinto da zero |
| Rank | Posizione nell'ordinamento dei candidati dell'analisi |
| Proxy | Informazione indiretta, per esempio un bosco come contesto di supporti arborei |
| Snap | Aggancio del clic a un candidato già esistente |
| GeoPackage | Formato di file che può contenere layer e tabelle persistenti |

### Fonti e approfondimenti

- [Photon: progetto, uso e servizio pubblico](https://github.com/komoot/photon).
- [OpenStreetMap: attribuzione e licenza](https://www.openstreetmap.org/copyright).
- [QGIS 3.44: formati e testo delimitato](https://doc.qgis.org/3.44/en/docs/user_manual/managing_data_source/supported_data.html).
- [QGIS 3.44: riproiezione e assegnazione del CRS](https://documentation.qgis.org/3.44/en/docs/user_manual/processing_algs/qgis/vectorgeneral.html).
- [GDAL: opzioni di esportazione CSV](https://gdal.org/en/stable/drivers/vector/csv.html).


Questo manuale è stato confrontato con interfaccia, controller e servizi della versione 15.6.33. Per i dettagli implementativi: `services/scoring_model.py`, `services/model_uncertainty_service.py`, `services/model_confidence_service.py`, `services/solution_stability_service.py`, `services/confirmation_fields_service.py` e `controllers/plugin_controller.py`.

- [Sorgenti e README GeoLichen](https://github.com/LucaGrazia0/geolichens).
- [Segnalazione problemi](https://github.com/LucaGrazia0/geolichens/issues): indica versione QGIS, sistema operativo, versione GeoLichen, azione e messaggio di errore; evita di pubblicare chiavi API o dati riservati.
- [QGIS 3.44 - Gestione dei plugin](https://docs.qgis.org/3.44/en/docs/user_manual/plugins/plugins.html): installazione da ZIP.
- [QGIS 3.44 - Creazione ed esportazione dei layer](https://docs.qgis.org/3.44/en/docs/user_manual/managing_data_source/create_layers.html): formati persistenti e layer in memoria.
- [GBIF - Georeferencing Best Practices](https://docs.gbif.org/georeferencing-best-practices/1.0/en/): principi generali di georeferenziazione e documentazione dell'incertezza.
- [ITALIC](https://italic.units.it/): riferimento per i profili ecologici consultati dal plugin.

Le fonti esterne descrivono strumenti e metodi di riferimento; non certificano gli algoritmi o i risultati di GeoLichen. Per la revisione dei pesi e dei proxy consulta anche `docs/SCORING_15_6_11.md` nella cartella del progetto.

## 23. Diagnostica, attese e disponibilità dei servizi

Apri **Plugins > GeoLichen > GeoLichen — Performance e robustezza** per tempi e
stato del progetto. L'opzione **Registra dettagli diagnostici** abilita messaggi
aggiuntivi nel pannello **Visualizza > Pannelli > Messaggi di log**, scheda
**GeoLichen**. Gli avvisi restano registrati anche con dettagli disattivati.
La preferenza è salvata nel profilo QGIS; non cambia score o impostazioni TLS.
Gli URL nel registro centralizzato sono ridotti al solo server, senza percorso
o parametri. Prima di condividere report o screenshot verifica comunque che
non contengano nomi di file, località o altri dati riservati.

Photon attende fino a 35 s per richiesta, con un budget complessivo di 80 s per
ricerca e fino a sei richieste. Dopo un errore il plugin può recuperare varianti
già presenti nella cache valida. Un timeout non significa che la località non
esista. Overpass distingue il tempo di esecuzione sul server dall'attesa di rete:
il download sentieri può attendere fino a 60 s per server. I problemi dei due
servizi sono indipendenti dal profilo ITALIC.

Se QGIS mostra un errore del certificato HTTPS, scegli **Abort** senza salvare
un'eccezione. GeoLichen mantiene i controlli TLS e può usare profili ITALIC
salvati quando il percorso di recupero lo consente; una cache scaduta è segnalata
come tale. Nessun servizio esterno è reso disponibile da questi controlli locali.

Durante la scelta del candidato la preview sotto i pulsanti mostra rank,
coordinate WGS84 e incertezza GeoLichen R55–S65; non scrive nella tabella.
Se nessun punto supera i filtri, l'avviso invita a controllare località, buffer,
quota/DEM e campi ambientali. Non interpretare l'assenza di candidati come prova
che la specie sia assente nella zona.


### Overpass indisponibile e tempi dell'analisi — 15.6.33

Un HTTP 502 indica una richiesta fallita sul lato del servizio; non prova che
non esistano sentieri. Il pulsante di analisi comprende anche il download OSM:
la finestra **Performance e robustezza** ora distingue `download_sentieri_osm`
e `calcolo_ecologico`, con durata e stato. Anche i tentativi falliti sono misurati.

La risposta completa della stessa richiesta viene riutilizzata per 24 ore senza
rete. Dopo un errore online, il plugin può recuperare l'archivio della richiesta
identica fino a 30 giorni, mostrando l'età e «non aggiornato». Il ritaglio segue
sempre il buffer corrente. Questa risposta non diventa una nuova acquisizione:
il file conserva la sua data e non viene rinnovato artificialmente. Risposte
parziali, archivio troppo vecchio e dati di altre aree non vengono usati.

Dopo un download fallito, una ripetizione sulla stessa area entro 60 secondi
non rilancia altre richieste; la presenza di una cache fresca ha comunque priorità.
Al termine di tale pausa è possibile un nuovo tentativo. La prima richiesta può
ancora attendere i timeout dei due server. Se non esiste un archivio utilizzabile,
il problema resta segnalato e non vengono inventati sentieri. Puoi selezionare
un tuo layer sentieristico in **Accessibilità**; verifica provenienza e copertura.
Usare dati archiviati può cambiare lo score rispetto all'assenza di accessibilità,
perché cambia l'evidenza disponibile, non la formula del modello.
