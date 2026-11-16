# GeoLichen 15.6.25: buffer circolari e download dei sentieri

## Area di ricerca delle località

Per scelta dell'utente, tutte le località ricercate usano sempre un **cerchio sul
punto selezionato**. Si conservano i raggi base specifici del tipo: per esempio
150 m per cime e rifugi, 250 m per passi, 300 m per laghi e corsi d'acqua,
500 m per località generiche, 1000 m per boschi e monti, 1500 m per valli,
2000 m per comuni. Un'accuratezza metrica esplicita del fornitore può ampliarli
secondo i limiti già esistenti; resta l'espansione circolare dei monti guidata
dalla quota. Il cerchio è calcolato in metri nel CRS UTM locale e poi
trasformato in WGS84, non in gradi o metri Web Mercator.

Il parser riconosce ora anche «laghetto» e «laghetti». Prima «Laghetto d'Avio»
poteva ricadere nel tipo generico, con un rettangolo del geocoder ampliato e
angoli arrotondati. L'area rettangolare non era un cerchio deformato.

La ricerca circolare non richiede il download della geometria OSM della località.
Si evita quel lookup superfluo per tutte le categorie. Gli strumenti di disegno
manuale conservano la geometria esplicitamente disegnata dall'utente.
La geometria documentale rimane indipendente: non si sostituisce il contorno
documentale con il cerchio di ricerca. Le formule delle incertezze restano
invariate; cambiare l'area e i candidati può cambiare rank, score e raggio R55.
L'area di ricerca non esclude automaticamente l'acqua.

## Attesa Overpass

La 15.6.24 aveva aggiunto una scadenza **totale di 27 s** per server. Il vecchio
limite di inattività non era equivalente: una risposta poteva arrivare dopo
più di 27 s complessivi. Non è corretto attribuire ogni timeout alla sola
indisponibilità dei server.

Ora il download dei sentieri mantiene la query con `[timeout:25]`, ma concede
**60 s di attesa di rete per server**, includendo coda, esecuzione e trasferimento.
Restano al massimo due tentativi sugli stessi endpoint: fino a circa due minuti
prima di proseguire senza quei dati. La cancellazione rimane limitata.
L'errore della risposta QGIS è controllato anche se la chiamata bloccante
riporta NoError. Il timeout di inattività scatta un secondo dopo il watchdog
totale, evitando una corsa tra due cancellazioni contemporanee.

Non cambiano i tipi di percorso richiesti, il ritaglio esatto al buffer, i dati
validi in cache o i rifiuti 406/429. Un errore HTTP 502 rimane un errore del server;
un timeout non equivale a «nessun sentiero». Il pannello distingue il risultato
vuoto dal download fallito. Attendere più a lungo non garantisce la risposta.

L'archivio permanente per area discusso con l'utente non è incluso in questa
modifica: la cache attuale conserva il TTL di 24 ore e le chiavi delle query.

## Verifica

Le regressioni controllano centro e distanza di tutti i vertici del cerchio,
geometria documentale separata e assenza di lookup OSM superfluo per laghi,
boschi, valli, passi, cime, monti, torrenti, comuni, rifugi, sentieri e luoghi
generici. I test del trasporto distinguono budget della query, attesa di rete
e cancellazione. Il server HTTP locale simula una risposta ritardata che
superava la vecchia scadenza e viene ora accettata.

Prova live sul cerchio del Laghetto d'Avio: il principale risponde HTTP 502,
il secondario supera i 60 s; nessun dato scaricato (61,236 s complessivi).
I dati storici locali del 4 agosto, usati solo come verifica e non come fallback
di produzione, restituiscono nel cerchio quattro segmenti `track` e un segmento
`path`, incluso il tracciato a est mostrato dall'utente. Il ritaglio lo conserva.

## Differenze rispetto a MapTiler

Lo ZIP 15.6.19 conferma che anche la versione MapTiler scaricava i sentieri da
Overpass tramite POST. MapTiler forniva il geocoding, ora sostituito da Photon.
La query dei tipi highway è la stessa; il ritaglio esatto del buffer è stato
introdotto nella 15.6.21, la simbologia e la scadenza totale nella 15.6.24.
L'endpoint secondario storico `overpass.kumi.systems` è stato aggiornato a
`overpass.private.coffee`. Una mappa di sfondo può mostrare i sentieri anche
quando il relativo download analitico fallisce.

Il servizio pubblico [documenta code e limiti condivisi](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html).
Non è disponibile una prova che i timeout siano causati dalla frequenza d'uso
di questo utente. Le prove locali non garantiscono la disponibilità dei server.
