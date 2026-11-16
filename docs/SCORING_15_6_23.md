# GeoLichen 15.6.23: score coerenti e calcolo più leggero

Revisione del 23 ottobre 2026, successiva al checkpoint `cc53d04` (15.6.22).
Corregge le incoerenze riprodotte nell'audit. Le modifiche del modello possono
cambiare GSS, rank e punto proposto; le sole ottimizzazioni devono produrre
gli stessi risultati del modello corretto eseguito senza ottimizzazioni.

## Formula e pertinenza dei contributi

`GSS = 0,25 Geografia + 0,25 Terreno + 0,25 Ambiente + 0,25 Accessibilità`

I quattro pesi restano al 25%. Anche i pesi ambientali per gruppo e la gestione
neutra dei dati mancanti della [revisione 15.6.11](SCORING_15_6_11.md) restano
validi, con le precisazioni seguenti.

- **Geografia:** usa il contesto ricevuto per la località corrente, anche nel
  raffinamento. Il contesto precedente non viene recuperato per errore. I nomi
  `summit`, `summit_peak`, `peak` e `cima` hanno la stessa interpretazione.
- **Accessibilità:** deriva dalle distanze dai percorsi, con le classi esistenti;
  senza misura resta a 50. La distanza dalla località non entra più anche qui.
  Il suo peso sul GSS è quindi 25%, senza la precedente miscela geografica.
  È corretto anche un limite inferiore impostato erroneamente a 50: una misura
  sfavorevole ora conserva i valori 30 o 10 previsti dalle classi, mentre il
  dato mancante resta neutro a 50.
- **Pendenza:** conserva le penalità morbide per gruppo ecologico, senza
  dimezzarle vicino ai sentieri. Non esclude punti. Il dato di accessibilità
  rimane nella componente dedicata.
- **Substrato:** un valore numerico di pH o una classe acida/neutra/basica non
  dimostra la presenza di suolo nel punto. Un campo che descrive esplicitamente
  il supporto resta utilizzabile anche se lo stesso layer contiene un altro
  campo di pH numerico. Il pH diretto resta pertinente solo ai gruppi previsti.
- **Forofita:** se il dato deriva da un poligono forestale e il tipo arboreo
  differisce da quello richiesto, il confronto è neutro: il poligono non
  dimostra né esclude alberi isolati. La corrispondenza del tipo forestale è
  un proxy con qualità 0,75. Un'osservazione specifica del supporto, distinta
  dal poligono forestale, può invece produrre incompatibilità morbida (30/100).
  Le normali letture della carta forestale sono marcate come `forest_polygon`.
- **Habitat:** rimane basato sulle osservazioni indipendenti già implementate.
  Non vengono inventati dati di luce, umidità o microhabitat mancanti.

La separazione dei contributi elimina un doppio uso dell'informazione; non
dimostra che i pesi risultanti siano ottimali su record reali. Accessibilità
odierna e condizioni del raccoglitore storico restano indizi distinti.

## Quota ed esposizione

Il filtro HARD della quota mantiene le precedenti tolleranze: per la quota
singola la precisione inferita dal numero; per l'intervallo almeno ±10 m.
La compatibilità altitudinale ora varia in modo continuo:

`score_quota = max(0, min(100, 100 − 50 × distanza / tolleranza))`

Per una quota singola la distanza è lo scarto assoluto dal valore indicato.
Con 1500 ±100 m: a 1500 m vale 100; a 1550 m vale 75; a 1600 m vale 50;
a 1601 m il filtro esclude il punto. La gradualità è una scelta euristica
esplicita, non una probabilità calibrata.

Per un intervallo la distanza è zero in tutto l'intervallo e cresce solo
oltre i suoi estremi. Il punto medio non riceve preferenza. Con 1400–1600 m:
ogni quota interna vale 100; 1610 m vale 50 ed è ancora ammessa con tolleranza
10 m; 1611 m è esclusa. Il delta coerente viene usato anche nello spareggio.
Senza DEM o senza confronto altitudinale il contributo resta neutro.

Una superficie DEM con gradiente numericamente nullo non ha esposizione:
il valore resta assente e non genera bonus nord/sud. Si sopprime solo lo zero
numerico (gradiente ≤ 10⁻¹²), senza assumere un'accuratezza del DEM non fornita.
Una soglia per superfici quasi piane richiede informazioni sulla qualità DEM.

## Classifica e incertezza

Ordine degli spareggi, dopo il GSS non arrotondato:

1. minore scarto dalla quota singola/intervallo, se disponibile;
2. minore distanza dal riferimento della località;
3. minore distanza dal percorso;
4. minore distanza dal centro dell'area;
5. identificativo del candidato, per un ordine deterministico.

Zero metri è un dato valido e precede distanze positive; un dato mancante
non viene trasformato in zero. Le formule storiche restano diagnostiche,
escluse sia dal GSS sia dagli spareggi. Il nuovo ordine può cambiare il rank 1
quando più candidati hanno lo stesso GSS.

L'etichetta dell'incertezza del modello è **R55–S65**, coerente con la soglia
65% e copertura pesata 55% già in uso: la soglia non viene cambiata al 70%.
Le colonne precedenti contenenti R55/S70 continuano a essere riconosciute;
non vengono rinominate o cancellate. È corretto anche il percorso di fallback
senza candidati, che prima riferiva una costante assente.

MCI, SSI e incertezza della località conservano la propria definizione. La
riformulazione scientifica dell'SSI per un solo candidato è rinviata.

## Ottimizzazioni senza cambiare i risultati

- Riutilizzo del misuratore ellissoidale WGS84 per la singola analisi,
  condiviso da raggio del modello, MCI e SSI, senza cache globale persistente.
- SSI: se tutti i nodi equivalenti sono collegati al nodo selezionato e
  `min_samples=2` include il nodo stesso, tutti sono nodi centrali dello stesso
  cluster DBSCAN. In questo caso la soluzione esatta evita le distanze fra
  tutte le coppie. Negli altri casi resta il clustering completo.
- Un solo gruppo di quattro campioni DEM per pendenza ed esposizione:
  con un DEM i campioni per candidato passano da 9 a 5. Con più DEM restano
  tutti i campioni centrali necessari per priorità, fallback e dispersione.
- Il filtro HARD altitudinale precede letture vettoriali e campioni DEM
  circostanti dei punti già esclusi. I candidati ammessi restano gli stessi.
- Una sola lettura della feature pedologica per valore del campo e pH.
- Vincoli e contesto ecologico invarianti vengono preparati una volta per
  griglia; aggregazione ambientale ufficiale una sola volta per candidato.
- Le geometrie forestali trasformate vengono riutilizzate nella singola
  griglia, mantenendo la query originale e la proiezione locale. La cache
  viene ricreata a ogni analisi, anche dopo modifiche ai layer.
- Le griglie intermedie del raffinamento non ricalcolano le incertezze: il
  calcolo completo viene eseguito sulla griglia finale. La superficie globale
  e il punto finale mantengono i rispettivi insiemi di candidati.

## Prove e tempi

Fixture locali sintetiche, macOS 26.6, QGIS 3.44.9, Python 3.12.11. Nessun
download o dataset personale. Il benchmark confronta il modello corretto con
un percorso di riferimento che ripristina campionamenti ripetuti e SSI completo.

| Prova | Percorso completo | Ottimizzato |
|---|---:|---:|
| SSI, 800 candidati compatti | 9,261 s | 0,00263 s |
| SSI, 800 candidati dispersi | 9,406 s | 1,576 s |
| 300 candidati, creazione punti e superficie | 1,330 s | 0,476 s |

I risultati confrontati sono identici. L'ultima prova esclude rete, rendering
del canvas e raffinamento adattivo: il rapporto circa 2,8× descrive quella
fixture, non un'accelerazione garantita dei 3–5 minuti osservati su Windows.

I test confrontano anche attributi e celle della heatmap, verificano cluster
compatti/dispersi/multipli (60 casi deterministici), filtri, cache dopo modifica
del layer, priorità multi-DEM e calcolo finale unico dell'incertezza.

Riproduzione con l'interprete Python di QGIS:

```
python -B tests/regression_analysis.py
python -B tests/regression_scoring.py
python -B tests/regression_interface.py
python -B tools/benchmark_ecological_analysis.py
```

Per confrontare Windows usare le stesse fixture e annotare versione QGIS e
hardware. Restano da misurare i layer regionali reali, la latenza dei servizi
e i progetti Windows 3.40. QGIS 4 richiede ancora verifica completa nel proprio
runtime. I test software non sostituiscono la validazione su coordinate note,
separando località/aree correlate fra calibrazione e valutazione.
