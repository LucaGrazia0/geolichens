# GeoLichen 15.6.24: tipi di percorso e disponibilità dei dati

Verifica del 23 ottobre 2026. Questa revisione mantiene geocoding, geometrie,
score, ranking e metodi di incertezza della 15.6.23. Cambiano la visualizzazione
dei percorsi e la diagnostica delle richieste Overpass.

## Una sola località nella scelta iniziale

La finestra «Seleziona località» elenca risultati geografici del geocoder, non
i candidati della griglia ecologica. Un solo risultato è un esito possibile,
anche richiedendone fino a dieci. La griglia viene generata successivamente.

Prova live: la grafia esatta `Monte Pornina` restituisce una sola feature Photon,
denominata «Monte Pornina, Vione, Brescia, Lombardy, Italy». La variante con
grafia diversa `Monte Porrina` restituisce anche risultati fuzzy, molti dei
quali non identificano la stessa località. Il plugin non aggiunge alternative
fittizie per riempire la tabella. Le varianti di query continuano a fermarsi
al primo successo per riferimento: la ricerca non è un censimento esaustivo.

## Sentieri, piste e strade

Il filtro richiede già le way OSM `path`, `footway`, `bridleway`, `steps`,
`pedestrian`, `track`, `service` e `living_street`. Le ultime due classi sono
strade di accesso; una `track` è una pista agricola/forestale, non necessariamente
un sentiero pedonale. Il download non è limitato alle strade carrabili.

Il dato locale dell'area di Monte Pornina contiene, dopo ritaglio a un buffer
di riferimento di 1 km, **7 segmenti path e 2 track**, senza service/living_street.
È una verifica della risposta OSM già salvata, non una dichiarazione di nuovo
download online. Non viene distribuito alcun dataset locale nel pacchetto.

Prima il layer usava un solo simbolo sottile per tutti i percorsi. Ora:

- viola: sentieri, percorsi pedonali/equestri e scalinate;
- marrone: piste agricole/forestali;
- grigio: strade di servizio/residenziali.

La legenda usa le classi effettivamente presenti e ne conserva il nome OSM.
Il pannello mostra conteggi distinti dei **segmenti ritagliati**, non il numero
di itinerari o di way originali. Il riepilogo rimane visibile anche quando
lo stato operativo cambia per mostrare rank e distanza del punto sotto il mouse.
Se OSM restituisce soltanto strade, il pannello dichiara esplicitamente che
non sono stati restituiti sentieri pedonali. Nessun tratto viene riclassificato
artificialmente; geometrie, attributi e uso nell'accessibilità restano invariati.

Un sentiero assente da OpenStreetMap non può essere ricavato da questa risposta.
Un layer sentieristico regionale può essere caricato e selezionato in Accessibilità.

## Rete e cache

Nelle prove live il server principale ha risposto via GET con HTTP 502 e un
messaggio di capacità esaurita; il secondo endpoint non ha risposto entro 18 s.
Una successiva prova con il trasporto POST QGIS aggiornato, una sola piccola
query e timeout server 3 s, è terminata in **10,016 s**: due tentativi, ciascuno
interrotto dalla scadenza totale di 5 s, senza dati ricevuti.

Quindi la disponibilità del nuovo download pubblico resta irrisolta. Il codice
non interpreta questi errori come assenza di sentieri e non aggira i rifiuti
HTTP 406/429 cambiando server. Gli endpoint restano i due già configurati.

Oltre al limite di inattività esiste ora una scadenza totale `timeout_s + 2`
per endpoint, applicata con cancellazione QGIS. Per i sentieri il valore
predefinito è 27 s per endpoint, con al massimo due tentativi. HTTP 502/503/504
sono identificati come servizio occupato/non disponibile. L'avviso rimane
leggibile nel pannello anche dopo il calcolo ecologico.

La cache conserva il TTL di 24 ore e viene sempre ritagliata al buffer corrente.
Una cache con risposta parziale (`remark`) o struttura non valida è scartata;
le risposte di errore non vengono salvate come dataset. Nessun contenuto della
cache personale viene cancellato o pubblicato.

## Incertezze: stesso metodo della 15.6.23

L'incertezza della località usa la geometria documentale o, nei casi puntuali
senza estensione, l'area operativa prevista dal flusso esistente. Per il
point-radius ordinario è la distanza massima dal centro geografico corretto
al bordo, combinata in quadratura con gli errori indipendenti disponibili.
Il passo della griglia resta una diagnostica distinta, non viene sommato a
`coordinateUncertaintyInMeters`. Restano anche le convenzioni precedenti per
le geometrie manuali, inclusa la lunghezza totale per la località lineare manuale.

L'incertezza GeoLichen R55–S65 considera punti con GSS almeno il 65% del valore
del punto scelto. Il peso è `(GSS/GSS_scelto)^2 × exp(−d/λ)`, con
`λ = max(2 × passo, mediana delle distanze compatibili)`. Il raggio interpolato
copre il 55% del peso; conserva il limite di risoluzione `passo/√2` e il limite
superiore legato al 90° percentile delle distanze compatibili. Non è un
intervallo di confidenza statistico e non sostituisce l'incertezza della località.

La soglia 65% era già presente nella 15.6.22; la 15.6.23 ne ha corretto
l'etichetta storica S70. Le correzioni degli score della 15.6.23 possono cambiare
il valore del raggio perché cambiano gli input, senza cambiare questa formula.
La 15.6.24 non modifica né formula né score.

## Verifiche riproducibili

- Test OSM: categorie/colori, riepilogo strade sole, cache parziale, fallback
  dopo 502, cancellazione e pulizia del timer; regressioni precedenti mantenute.
- Test interfaccia: riepilogo/errori persistenti durante il cambio dello stato
  operativo; pulizia al cambio buffer; geometrie usate dal motore reale.
- Server HTTP locale: POST, 429, download/ritaglio/cache e interruzione di una
  risposta bloccata dopo circa 2,05 s, senza server esterni.
- Rendering QGIS delle geometrie OSM locali verificato con categorie distinte.

Le prove di rete locali non garantiscono la disponibilità dei server pubblici.
Windows 3.40 e QGIS 4 richiedono ancora la verifica completa nel runtime relativo.
