# GeoLichen 15.6.26: ricerca approfondita delle località

## Attesa e cache: correzione 15.6.30

Il confronto diretto degli ZIP 15.6.28 e 15.6.29 conferma che motore di ricerca,
nomi, configurazione endpoint e trasporto erano identici, salvo il numero di
versione nell’User-Agent. Il 12 novembre una richiesta diretta per Ponte di
Legno ha risposto HTTP 200 in 29,576 s, mentre la 15.6.29 interrompeva la prova
QGIS a 12,04 s. Con la correzione, la prova QGIS ha restituito dieci candidati
in 30,4 s. Si tratta di una prova di disponibilità, non di un tempo garantito.
La prova completa Vione/Monte Pornina ha però continuato a fallire in 68,71 s:
il comune ha risposto, la località ha superato i 35 s per richiesta. L’aumento
dell’attesa non garantisce quindi che il servizio pubblico sia disponibile;
la correzione recupera cache valide e distingue l’errore online, senza dichiarare
che la località sia assente.

L’attesa per richiesta è ora 35 s, entro un budget di rete di 80 s per azione;
restano al massimo sei richieste e l’intervallo minimo di 1,1 s. I tempi delle
altre attività locali del plugin non sono inclusi nel budget di rete.
Un errore non avvia una serie di nuovi tentativi: vengono però controllate
le risposte già salvate per il nome e le sue varianti. La cache rimane isolata
per endpoint/area/posizione e valida 30 giorni; non si recuperano risposte
scadute né quelle di un altro endpoint. Una richiesta senza bias di posizione
già salvata può essere riutilizzata mantenendo area e controllo del nome.
Le righe recuperate sono indicate come cache locale; l’errore online rimane
visibile. L’archivio delle località esplicitamente confermate resta separato.

## Potenziamento 15.6.28

La ricerca iniziale non si ferma più al primo nome parzialmente compatibile.
Prova fino a tre varianti uniche per riferimento, interrompendosi prima quando
il nome coincide: nome originale/abbreviazione espansa, parole di collegamento
semplificate e, se presente come suffisso completo, nome del comune separato.
Per esempio «Foppe di Braone» può cercare anche «Foppe Braone» e «Foppe» con
la posizione del comune come contesto. Il testo della tabella e il tipo geografico
non vengono riscritti. Le richieste equivalenti del parser e del record sono
riutilizzate. «Cerca altre località» esplora anche le ulteriori varianti previste.

L'ordine privilegia il nome proprio: prima una corrispondenza esatta completa,
poi tutte le parole distintive, poi possibili refusi e nomi incompleti. Entro la
stessa classe intervengono comune, geometria amministrativa e distanza. Il
comune riportato dalla fonte viene letto dal campo strutturato, anziché dedotto
da «Braone» presente nel nome di una cima o di una malga. Un comune differente
è segnalato, senza escludere automaticamente luoghi di confine. Anche un nome
esatto richiede sempre una verifica geografica.

### Ricerca nella zona iniziale della mappa

1. Chiudi la finestra delle località se è aperta e inquadra sulla mappa la zona
   in cui pensi si trovi il luogo, usando la tua cartografia di riferimento.
2. Premi **Ricerca della località**.
3. Nella finestra scegli **Cerca nella zona iniziale della mappa**. Il nome
   modificabile viene cercato solo nell'inquadratura precedente all'anteprima.
4. Verifica i candidati sulla mappa e conferma con **Crea buffer**, oppure annulla.

La zona viene acquisita prima che la selezione di una riga sposti l'anteprima:
non segue il primo candidato. È trasformata dal CRS del progetto a WGS84 e
intersecata con l'area di ricerca configurata. Se le due aree non si intersecano,
compare un avviso. Per cambiare zona, annulla, sposta la mappa e riavvia la ricerca.
Questa azione non cambia le impostazioni del progetto, non espande il rettangolo
in caso di risposta vuota e non crea un buffer. Se non emergono nuovi risultati,
le alternative precedenti rimangono disponibili e sono indicate come conservate.

### Limiti verificati

Nel test reale del 29 ottobre, la ricerca estesa di «Foppe di Braone» ha raccolto
12 alternative con nomi compatibili in quattro richieste (16,128 s). Il nome
completo esatto non è emerso. Un rettangolo di prova nella zona montana ha
restituito soltanto «Malga Foppe di Sotto»: questo riduce gli omonimi, ma non
prova che la malga rappresenti tutta la località descritta nel cartellino.
Non sono state inserite equivalenze o coordinate fisse per questo caso.
La durata dipende dal server e dalle risposte già disponibili nella cache.

Rimangono il limite di sei richieste di rete per azione e l'intervallo minimo
di 1,1 s tra richieste. La ricerca di varianti può richiedere più tempo del
percorso precedente che si fermava al primo risultato parziale. La disponibilità
di un toponimo dipende dall'indice del servizio, non soltanto da quante varianti
vengono interrogate. Se il luogo resta irrisolto, usa la ricerca manuale e verifica
la cartografia; non scegliere una struttura vicina soltanto per somiglianza.

## Correzione 15.6.27: nomi generici e corrispondenze parziali

Il confronto del nome proprio vale anche per località generiche. Quando è
configurato il campo comune, il solo nome del comune non basta a giustificare
un risultato: «Foppe di Braone» non deve consigliare «Municipio di Braone».
Se manca una corrispondenza esatta, compare un avviso e le righe con nomi
parziali non ricevono il segno «Consigliato». La somiglianza non dimostra
che due luoghi siano la stessa località: verifica sempre la posizione.
Se viene trovato solo il comune, la località distinta rimane non risolta;
puoi correggere la ricerca o usare gli strumenti manuali. Le associazioni
già confermate esplicitamente nell’archivio restano disponibili.

## Ricerca iniziale e altre alternative

«Ricerca della località» conserva un percorso iniziale breve. Nella finestra
«Seleziona località», il campo del nome è modificabile: premi **Cerca altre
località** per confrontare altre varianti. Puoi farlo anche se il primo tentativo
non ha restituito risultati. Il testo originale della tabella non viene modificato.

La ricerca approfondita continua dopo il primo risultato: prova il nome,
varianti controllate e qualificazioni con il comune o l'Italia. Riunisce gli
oggetti OSM duplicati e mostra le ricerche che hanno contribuito a ciascuna riga.
Le alternative precedenti rimangono disponibili se una nuova richiesta fallisce.
Un errore di rete interrompe le altre richieste di quell'azione. Restano fino a
sei richieste di rete per azione, incluso il comune, distanziate di almeno 1,1 s.
Le risposte Photon già salvate sono riutilizzate per 30 giorni.

Il numero di risultati non misura la qualità: il confronto del nome scarta
alcuni risultati fuzzy palesemente estranei, mantenendo tolleranza per refusi.
Non è garantito un censimento esaustivo dei toponimi. I server possono restituire
meno dei dieci risultati richiesti per query.

Seleziona una riga e premi **Crea buffer** per confermare. **Annulla** lascia
disponibili gli strumenti manuali. Nessun buffer viene creato dalla sola ricerca
approfondita. I buffer operativi restano circolari sul punto scelto.

## Abbreviazioni e tipo geografico

Sono riconosciute varianti conservative come `M.te`/`Mt.` → Monte, `Rif.` →
Rifugio, `P.so` → Passo e `L.to` → Laghetto, oltre ad apostrofi e accenti.
Il parser geografico usa le stesse espansioni: un nome abbreviato non deve
diventare una località generica soltanto per l'abbreviazione.
Abbreviazioni ambigue come `S.` non vengono espanse automaticamente.

Il tipo OSM aiuta a distinguere una cima, un passo, un rifugio, uno specchio
d'acqua o una strada omonima. La tabella mostra tipi leggibili, motivazione,
fonte e varianti cercate. Lo **Score ricerca** ordina queste località:
non è il GSS ecologico e non è una probabilità statistica.

## Confini comunali facoltativi

Carica nel progetto un tuo layer **poligonale dei confini comunali**. In
«Configurazione layer e campi tabella record» seleziona:

1. **Confini comunali (facoltativo)**: il layer dei comuni;
2. **Campo nome comune**: la colonna con il nome del comune, coerente con la
   tabella record. Per esempio una colonna chiamata `COMUNE` o `nome`.

Non è incluso né scaricato automaticamente alcun dataset dei confini. La scelta
di layer/campo è conservata nel progetto QGIS. Il layer può avere un CRS diverso:
il servizio trasforma la geometria in WGS84 e misura in un CRS metrico locale.
Legge solo le geometrie dei comuni il cui nome corrisponde, considerando accenti
e l'eventuale prefisso «Comune di». Le modifiche del layer sono lette alla ricerca
successiva; non si conserva una geometria obsoleta tra le analisi.

Con un poligono utilizzabile, il ranking considera se il punto è interno,
sul bordo, vicino al confine o esterno. Rispetta buchi e geometrie multipart.
Le alternative esterne rimangono visibili. Senza un confine utilizzabile, usa
la distanza dal centro comunale dichiarandola come approssimazione, non come
prova di appartenenza amministrativa. Usa un layer dell'area appropriata per
evitare comuni omonimi di regioni differenti.

Questo controllo serve alla scelta della località: non sostituisce il buffer
circolare né modifica automaticamente la geometria documentale dell'incertezza.

## Archivio delle località confermate

L'opzione **Usa l'archivio delle località confermate e salva le nuove scelte** è
attiva per impostazione iniziale. Dopo **Crea buffer**, GeoLichen conserva nel
profilo QGIS l'associazione tra nome del record, comune e punto geografico scelto.
Un nome corretto cercato e poi confermato può diventare un alias del nome originale.

L'archivio è persistente: rimane dopo la chiusura di QGIS o del computer. Alla
ricerca successiva, un'associazione con lo stesso nome e comune viene proposta
anche senza rete, purché dentro l'area di ricerca configurata. Devi comunque
confermare la località. Puoi sempre usare **Cerca altre località** per confrontare
la scelta con risultati del servizio. Se una fonte ha spostato il punto di un
oggetto OSM, entrambe le posizioni rimangono disponibili per il confronto.

Premi **Archivio località confermate…** per consultare nomi, comuni, località
scelte e date o rimuovere una singola associazione. Disattivando l'opzione non
usi né aggiorni l'archivio; le associazioni già salvate rimangono sul disco.
Non si salva una nuova associazione premendo Annulla.

Il file è `geolichen/confirmed_localities.json` nel profilo QGIS attivo.
La scrittura è atomica; file illeggibili o di versione incompatibile non vengono
silenziosamente sovrascritti. Non vengono pubblicati o inclusi nel pacchetto.

Si conservano **punti delle località**, non i punti ecologici confermati, le quote
DEM calcolate, i GSS o le incertezze del modello. Ogni record mantiene la sua
analisi ecologica. Questo archivio è distinto dalla cache Photon e dall'archivio
dei sentieri per area discusso in precedenza, che non è implementato qui.

## Esempio

Per un cartellino «M.te Pornina», comune «Vione»:

1. Seleziona il record e premi «Ricerca della località».
2. Esamina i risultati e le motivazioni. Se necessario premi «Cerca altre località»:
   il nome viene confrontato anche come «Monte Pornina» e qualificato con il comune.
3. Verifica nome, tipo e posizione in mappa, quindi seleziona la località corretta.
4. Premi «Crea buffer». Si crea il cerchio della località e, se abilitata, si
   conserva l'associazione nell'archivio.
5. Esegui l'analisi ecologica come prima. Il prossimo record della medesima
   località potrà riutilizzare il riferimento geografico, mantenendo la propria
   ecologia e il proprio ranking.

## Disponibilità e limiti

Le regole di confronto e i bonus di ranking sono euristiche, non calibrate su
un campione indipendente. Un toponimo storico assente dall'indice non può essere
ricostruito automaticamente: correggi il nome con una fonte verificata o usa la
posizione manuale. L'archivio aiuta dopo una conferma, non inventa nomi storici.

Il servizio Photon pubblico richiede un uso moderato e non garantisce la
disponibilità. Per uso intensivo resta configurabile un endpoint Photon proprio.
Le nuove funzioni non aumentano i limiti delle richieste e non introducono
fallback verso il Nominatim pubblico. Vedi [API Photon](https://github.com/komoot/photon/blob/master/docs/api-v1.md)
e [condizioni del servizio](https://photon.komoot.io/).
