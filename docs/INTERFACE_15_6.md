# GeoLichen 15.6.10 — interfaccia e verifiche

Modifiche aggiornate al 20 ottobre 2026.

## Interfaccia

La prima sezione «Configurazione layer e campi tabella record» è richiudibile e
comprende chiave API, area, campi della tabella e tutti i layer precedentemente
presenti in «Layer ambientali». Geologia, suolo, alberi, accessibilità, fasce
vegetazionali e DEM hanno box distinti. Nomi dei widget e collegamenti ai servizi
esistenti sono preservati.

«Georeferenziazione Località» conserva le azioni esistenti. Punto e linea manuali
sono raggruppati in una sezione richiudibile; il passo della griglia non è
modificabile dall'utente. «Profilo ITALIC» è richiudibile. «Risultato» e «Campi
input correnti» sono nascosti; un messaggio operativo rimane visibile.

La superficie effettiva del buffer (ha o km²), il raggio o l’offset e il passo
base sono sempre visibili sotto «Ricerca della località». Per le aree
automatiche è indicato il raggio di riferimento usato per scegliere il passo.
Il riepilogo si aggiorna al cambio di geometria e si azzera a una nuova analisi.

Nella finestra «Usa questo candidato» i dettagli ecologici, GBIF, incertezza,
spiegazione e validazione sono raccolti in una sezione inizialmente chiusa.
I valori da inserire e i campi di destinazione restano visibili. Dalla 15.6.3
il valore calcolato di «Incertezza R55–S70» resta sempre visibile, sopra il
campo di destinazione; il valore è di sola lettura. Se non è disponibile
non viene sostituito da uno zero. La scrittura numerica nella tabella sorgente
e nel layer dei punti confermati è verificata dal test di conferma ecologica.

## Conferma e copia su più record (15.6.6)

I campi della conferma ora si chiamano «Incertezza località» (metodo GBIF) e
«Incertezza GeoLichen» (raggio R55–S70). Cambiano le etichette; i valori e i
metodi di calcolo restano invariati. I nomi delle colonne già esistenti sono
riconosciuti e conservati.

Se manca una colonna di destinazione, «Crea le colonne mancanti» aggiunge solo
i campi necessari e li seleziona nel dialogo. I nuovi campi numerici sono
`longitude`, `latitude`, `quota_dem`, `inc_loc_m`, `inc_geo_m`. I nomi brevi sono
compatibili anche con Shapefile. Se la tabella è già in modifica, il plugin non
salva le altre modifiche dell'utente: l'aggiunta è annullabile e resta da salvare
con le modifiche della tabella. Se il formato non permette di aggiungere campi,
il dialogo invita a esportare una copia modificabile in GeoPackage.
Il pulsante modifica lo schema anche se si annulla in seguito la conferma del punto.

«Copia su altri record» propone prima il punto confermato sorgente e poi le righe della
tabella di destinazione. Il filtro iniziale mostra stessa località e stesso
comune, ignorando maiuscole e spazi ripetuti; può essere disattivato. Si possono
scegliere più righe con Cmd/Ctrl o Maiusc. Le righe già selezionate nella tabella
sono riportate se visibili, ma non vengono aggiunte selezioni per somiglianza.
Una riga nascosta dal filtro viene esclusa dalla selezione di copia. La selezione
originale della tabella QGIS rimane invariata.

Prima della scrittura viene mostrato il numero di destinazioni. Coordinate,
quota e incertezze sono riutilizzate senza nuova analisi ecologica. Le righe
cambiate dopo il riepilogo vengono rifiutate. Le modifiche alle righe sorgenti
sono un'unica operazione annullabile quando la tabella è già in modifica;
un errore di scrittura annulla quell'operazione senza perdere le altre modifiche.
I punti nel layer cumulativo vengono aggiunti solo dopo la riuscita della
scrittura nella tabella. X/Y seguono il CRS della destinazione; il layer dei
punti confermati mantiene coordinate WGS84.

## Punto più probabile automatico (15.6.7)

Il pulsante «Punto più probabile automatico» avvia l'analisi
della singola riga selezionata. Mantiene la scelta della località corretta tra
i risultati del geocoder, quindi calcola la griglia e il ranking con la pipeline
ecologica esistente. Seleziona il candidato univoco di rank 1 e scrive direttamente
coordinate X/Y, quota DEM, incertezza località e incertezza GeoLichen.
Non richiede un clic sulla mappa o le successive conferme del candidato.

Il flusso usa i campi configurati o riconosciuti, conservando anche i vecchi nomi.
Le colonne mancanti vengono create automaticamente. X/Y seguono il CRS del layer;
la quota assente resta NULL. Il punto salvato viene aggiunto al layer cumulativo,
mostrato con un marker persistente e inquadrato in mappa anche in modalità sola
heatmap. I calcoli di DEM e incertezza sono condivisi con la conferma manuale.

Annullare la scelta della località non avvia il ranking e non crea colonne.
Errori di geocoding/ranking, mancanza del rank 1, tabelle non modificabili e cambi
di riga interrompono la scrittura. Il pulsante non riutilizza analisi precedenti.
Se la tabella era già in modifica, i dati restano nel buffer di modifica e vanno
salvati dall'utente. Gli altri pulsanti operativi sono disabilitati durante il
flusso e riattivati alla fine. La modalità manuale rimane disponibile.

## Nomi e raggruppamento delle azioni (15.6.8)

«Ricerca della località» sostituisce «Analizza record selezionato».
«Analisi ecologica del punto più probabile» e «Conferma punto ecologico»
sono raccolti nel box «Analisi ecologica». Dalla 15.6.9 questo box è separato da
«Georeferenziazione Località», che termina con «Sono a posto così»; i due box
sono allo stesso livello. Dalla 15.6.10 il box «Analisi ecologica» comprende
anche il pulsante automatico e «Copia su altri record», nuovo nome di «Copia punto».
Analisi e conferma manuale mantengono un riquadro interno distinto, seguito
dai due pulsanti separati. Cambiano solo etichette
e disposizione; i widget e i collegamenti alle funzioni esistenti sono conservati.

## Selezione della tabella (15.6.2)

Il plugin segue la selezione della tabella configurata anche quando è attivo
un layer di risultati. Il mapping è conservato nel progetto e ripristinato al
ricaricamento del plugin; salvare il progetto lo mantiene alla riapertura di QGIS.
Se il mapping è già stato perso, l’avvio dell’analisi propone la configurazione
per la tabella selezionata. Una selezione assente o multipla blocca l’azione:
non si riutilizza l’ultima riga e non si riduce la selezione a una sola riga.

### Più tabelle aperte (15.6.4)

La tabella memorizzata non ha più precedenza su una nuova selezione. Il plugin
ascolta la selezione di tutte le tabelle record e segue l’ultima selezionata,
anche se la finestra attributi è separata e il layer attivo rimane un altro.
«Tabella record» mostra la sorgente usata e permette una scelta esplicita; i
layer omonimi sono distinti tramite ID. Le selezioni nelle altre tabelle
non vengono cancellate. I campi vengono ripristinati o riconfigurati per la
nuova sorgente. Gli errori indicano la tabella e il numero di righe selezionate.

Ranking e conferma verificano tabella e ID del record: una geometria o un
candidato del record precedente non possono essere usati sulla nuova riga.
Il controllo viene ripetuto dopo la conferma, prima della scrittura. Cambiare
record annulla un disegno manuale ancora in corso.

Il ricaricamento del plugin mantiene in RAM chiave API, layer selezionati,
priorità DEM e parametri manuali. La chiave non viene scritta nel progetto
o in altri file da questa funzione. Una chiusura completa di QGIS richiede
nuovamente l’inserimento della chiave.

I nuovi controlli coprono due tabelle con righe selezionate contemporaneamente,
tabelle omonime, finestre attributi separate, sorgenti rimosse, ripristino di
un progetto CSV, cambi di record durante la conferma, connessioni dei segnali
al reload e conservazione delle impostazioni in RAM.

## Griglia e superficie

| Raggio del buffer / offset della linea | Passo base |
| --- | --- |
| 0–250 m | 10 m |
| oltre 250 e fino a 1000 m | 30 m |
| oltre 1000 e fino a 3000 m | 50 m |
| oltre 3000 m, compreso 50000 m | 100 m |

Le soglie sono continue anche per distanze con decimali. Per geometrie automatiche
irregolari si usa metà del lato maggiore dell'inviluppo nel CRS metrico locale.
Per la linea manuale vale la semilarghezza/offset; la griglia copre comunque
l'intero corridoio. I raffinamenti locali adattivi preesistenti sono mantenuti e
possono essere più fini del passo base.

Al cambio di geometria vengono azzerati i candidati, la selezione e le superfici
precedenti, mantenendo i punti già confermati e la geometria documentale. Una
ricerca manuale usa il nuovo centro e non il vecchio riferimento del geocoder.
La heatmap deriva dalla griglia globale: risoluzione e impronta seguono il passo,
con una maschera sull'area effettiva e un limite alle dimensioni del raster.
Le aree prive di campioni validi non ricevono score inventati.

## Uscita al centroide

«Sono a posto così» usa il centroide dell'intera area di ricerca, calcolato nel CRS
metrico locale e trasformato in WGS84. Campiona i DEM selezionati secondo la
priorità esistente e propone latitudine, longitudine e quota in una conferma
specifica, con campi della tabella facoltativi. Il risultato viene aggiunto al
layer «GeoLichen – Punti confermati», con metodo `locality_centroid`.

Questa azione non richiama ITALIC, il ranking o lo scoring ecologico. Eventuali
letture e analisi preliminari già eseguite dalle azioni precedenti non influenzano
il centroide. La pipeline manuale lineare esistente resta invariata e può aver
eseguito il ranking prima della scelta del centroide. Quota assente, GSS,
incertezza GBIF e raggio del modello non calcolati rimangono NULL. Annullare il
dialogo non scrive dati. Un controllo impedisce di usare l'area di un altro record.

## Riconoscimento dei substrati

La classificazione automatica era già presente: overlay geologico e lettura
puntuale usano descrizioni litologiche; il servizio suolo legge valori pH,
riconosce classi testuali e valuta la compatibilità ecologica. La scrittura
opzionale di GRUPPO_LITO resta un'azione esplicita dell'utente.

Il dizionario integrato nel codice è stato esteso con nomi inglesi comuni,
comprese combinazioni miste, e con suggerimenti di campi come LITHOLOGY,
DESCRIPTION, ROCK_TYPE e PH_H2O. Sono riconosciuti anche termini come acidic,
neutral e alkaline. Nessun dataset è necessario per queste regole di base.
Le categorie ecologiche calcareo/siliceo/misto non equivalgono alla distinzione
petrologica acido/basico di tutte le rocce, e la roccia non misura il pH del suolo.

## Visualizzazione della heatmap (15.6.5)

La resa dei colori si adatta allo zoom con ricampionamento bilineare, sia in
ingrandimento sia in riduzione. Il filtro si applica anche alle heatmap GeoLichen
già presenti. Non modifica il raster originale, il passo della griglia, i punteggi,
i candidati o le incertezze. Lo zoom non avvia una nuova analisi ecologica.
I DEM e gli altri raster non ricevono il filtro.

## Verifica

Controlli eseguiti con QGIS 3.44.9 e Python 3.12 sul Mac: smoke test
preesistente superato e 62 test di regressione superati, anche sull’esportazione
pulita senza dataset.

- smoke test precedente: import dei moduli, avvio, finestre ausiliarie, unload,
  storage, rete locale, errori HTTP, timeout e gestione MapTiler;
- regressioni su sezioni, widget e controlli nascosti;
- soglie della griglia e distanze metriche in modalità automatica e manuale;
- transizione automatico → punto manuale, invalidazione dei vecchi output,
  conservazione della geometria documentale;
- corridoio manuale, avvio ecologico precedente e annullamento del disegno;
- litologia italiana/inglese, campo pH, lettura reale su poligoni sintetici e
  creazione opzionale di GRUPPO_LITO;
- ranking ecologico e conferma/scrittura di un candidato con i servizi reali;
- raster per tutti i quattro passi, copertura interna e NoData fuori dal buffer;
- rendering a più scale, confronto dei colori e verifica che lo zoom non cambi
  file raster, griglia, ranking o incertezze; applicazione ai raster esistenti senza modificare i DEM;
- centroide, coordinate WGS84, scrittura tabellare, DEM con NoData e fallback,
  quota assente, annullamento e blocco delle aree appartenenti ad altri record;
- copia di un centroide già confermato in un secondo record senza rianalisi;
- creazione dei campi numerici, riapertura di un GeoPackage, nomi precedenti,
  formati non modificabili e conservazione delle modifiche pendenti;
- copia multipla, filtri, esclusione delle righe non scelte, annullamento,
  cambio di località dopo il riepilogo, errore di scrittura e CRS proiettati.
- flusso automatico completo con scelta della seconda località, scrittura del
  rank 1 e DEM, sola heatmap, errori, annullamento, cambi di riga durante la scelta
  o il ranking, modifiche pendenti, vecchie colonne e coordinate proiettate.

I dati di prova sono generati temporaneamente. Il pacchetto continua a escludere
i dataset locali. Non sono stati ripetuti test con servizi remoti autenticati,
Windows/Linux, tutte le versioni QGIS o un ranking completo su buffer da 50 km.
