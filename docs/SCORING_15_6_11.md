# GeoLichen 15.6.11 — prima revisione tecnica ed ecologica

Questa revisione corregge la disponibilità delle evidenze e la pertinenza dei
contributi. Non costituisce una calibrazione scientifica del modello.
La versione precedente è conservata nel commit `b567186` (checkpoint 15.6.10).

## Formula e dati mancanti

I quattro macroscore conservano il peso del 25% ciascuno. Il GSS è un indice di
compatibilità, non una probabilità che il raccoglitore fosse nel punto.

Ogni evidenza ambientale contiene score, stato, motivo, fonte e coefficiente
di qualità. Gli stati sono `valutato`, `mancante`, `non applicabile`.
Preferenze della specie, messaggi diagnostici e valori iniziali a zero non
dimostrano la presenza di un dato nel candidato.

I pesi ambientali sono fissi per gruppo, uguali per tutti i candidati:

| Gruppo | Substrato | Litologia | pH | Habitat | Alberi/contesto forestale |
|---|---:|---:|---:|---:|---:|
| Sassicolo | 37,50 | 37,50 | 0 | 25 | 0 |
| Terricolo | 31,58 | 15,79 | 26,32 | 26,32 | 0 |
| Muscicolo | 38,89 | 11,11 | 16,67 | 33,33 | 0 |
| Epifita | 0 | 0 | 0 | 25 | 75 |
| Lignicolo | 0 | 0 | 0 | 35 | 65 |
| Sconosciuto | 42,86 | 28,57 | 0 | 28,57 | 0 |

Sono i rapporti dei pesi precedenti, dopo la rimozione del bonus arboreo generico
per i gruppi non legnosi e del pH del suolo per i sassicoli. Le differenze dovute
agli arrotondamenti della tabella non sono presenti nel calcolo.

Per ciascuna componente: peso effettivo = peso nominale × qualità. Il peso
restante mantiene lo score neutro 50. Una misura mancante ha qualità zero:
non assorbe e non cede peso agli altri indizi.

`Ambiente = 50 + somma(peso_nominale × qualità × (score − 50)) / 100`

Il coefficiente di qualità è una cautela euristica sul tipo di evidenza,
non una stima validata dell'accuratezza del layer: 1 per i confronti numerici
implementati e la forofita classificata corrispondente; 0,75 per substrato,
litologia, classe di reazione del suolo e copertura arborea generica;
0,5 per habitat dedotto dalla copertura e prossimità forestale epifita;
0,35 per pH dedotto dalla litologia e contesto forestale lignicolo.

Sono esportati `env_cov` (peso con un confronto disponibile), `env_qcov`
(peso dopo la riduzione per proxy), `env_neut` (contributo neutro) e `env_status`.
Il dettaglio della conferma mostra copertura e contributo neutro, così che
la somma dei contributi ricostruisca lo score. MCI usa osservazioni effettive
al posto della sola presenza delle preferenze. Questi indici restano descrittivi.

## Pertinenza ecologica

- Il substrato e la litologia richiedono un confronto fra osservazione e
  requisito. Le incompatibilità restano morbide: un layer grossolano può
  nascondere microhabitat. Una carta forestale non prova il substrato del terreno.
- Il pH numerico e la classe di reazione del suolo sono confrontati con la
  preferenza della specie solo per terricoli/muscicoli. La coerenza fra suolo e
  roccia madre non sostituisce questo confronto. Il pH del suolo non misura la
  superficie rocciosa o la corteccia. Il proxy litologico non viene aggiunto
  al pH se la stessa litologia ha già fornito un confronto.
- L'habitat passa attraverso risultati strutturati. Non si estraggono numeri
  dalle frasi di diagnostica. Copertura forestale e umidità possono essere
  confrontate con requisiti pertinenti; habitat alternativi non accumulano bonus.
  Quota, pendenza e litologia non confermano una seconda volta habitat alpino,
  rupicolo o secco. Un substrato sconosciuto non dimostra apertura dell'habitat.
- La copertura forestale può favorire o sfavorire l'habitat richiesto, senza
  un premio arboreo fisso per sassicoli, terricoli e muscicoli.
- Una forofita classificata corrispondente è più informativa di una generica
  copertura arborea. La prossimità forestale è un proxy debole. Per i lignicoli
  il bosco non conferma il legno morto; l'assenza di bosco mappato non esclude
  alberi isolati o supporti legnosi non cartografati. Nei gruppi legnosi la stessa
  copertura forestale non contribuisce anche all'habitat: servono altre
  osservazioni, per esempio l'umidità, per quel confronto indipendente.
- Pendenza e confronto della quota mancanti non producono uno score perfetto.
  Il solo DEM, senza quota di riferimento, non assegna un bonus altitudinale.
  Anche Terrain conserva i pesi mancanti al valore neutro.
- Un errore nel modello ufficiale interrompe il calcolo; non viene sostituito
  silenziosamente da una formula storica, anche nel flusso automatico.

## Cosa resta per le revisioni successive

La quota del cartellino conserva i filtri precedenti. Non vengono modificati
la griglia, la visualizzazione della heatmap, le geometrie di ricerca, la copia
dei punti o la distinzione tra incertezza della località e raggio del modello.
Le vecchie formule restano diagnostiche; i criteri storici di spareggio fra
candidati equivalenti non sono ricalibrati in questo primo intervento.

Restano da valutare la duplicazione geografia/accessibilità, il contributo
topografico all'accessibilità, funzioni graduali per la quota, indicatori ITALIC
ordinali più dettagliati e misure dedicate di luce/umidità. Per i muscicoli serve
anche riconoscere il supporto sottostante: il gruppo da solo non prova che si
tratti di suolo. Il confronto con il suolo è una possibilità, non un'osservazione
di briofite né una conferma del loro substrato effettivo.

Occorrono coordinate di riferimento indipendenti per valutare i nuovi pesi e
le qualità proxy. I test sintetici verificano correttezza del software e
coerenza delle regole; non dimostrano un miglioramento dell'errore geografico.

## Riferimenti e loro uso

- [ITALIC — informazioni sugli indicatori](https://italic.units.it/key-maker/info):
  intervalli ecologici su scale ordinali, distinzione fra substrati e prudenza
  sulle specie poco conosciute. Non prescrive i coefficienti adottati qui.
- [Phillips et al. 2009](https://doi.org/10.1890/07-2153.1): il bias di raccolta
  nelle aree accessibili motiva la separazione concettuale fra accessibilità e
  idoneità ecologica; la ricalibrazione di quel macroscore è rinviata.
- [Roberts et al. 2017](https://doi.org/10.1111/ecog.02881): per la futura verifica,
  separare località/aree correlate fra calibrazione e valutazione.
- [Zurell et al. 2020 — ODMAP](https://doi.org/10.1111/ecog.04960): documentare
  fonti, decisioni, limiti e metodi di valutazione in modo riproducibile.

I principi degli studi vengono adattati a una ricostruzione della località di
raccolta; GeoLichen non diventa automaticamente un modello di distribuzione
di specie né un modello probabilistico validato.

## Verifiche

Eseguire con l'interprete Python di QGIS e un profilo temporaneo:

```
python -B tests/regression_scoring.py
python -B tests/regression_interface.py
python -B tests/smoke_qgis.py
python -B tools/build_release.py
```

Le fixture sono sintetiche e temporanee. La build usa una allowlist di codice
e documentazione; nessun dataset locale viene incluso nel pacchetto.
