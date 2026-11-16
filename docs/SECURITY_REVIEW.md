# Resoconto di sicurezza — GeoLichen 15.6.34

Data: 16 novembre 2026. Il controllo riguarda i sorgenti correnti ammessi nella
distribuzione e la configurazione pubblica di sviluppo. Non è una certificazione,
un penetration test, una scansione dei dataset privati o una verifica completa
delle dipendenze/installazioni QGIS e della cronologia Git.

## Metodo e riproduzione

Gli strumenti sono **Bandit 1.8.6** e **detect-secrets 1.5.0**, installati in un
ambiente Python di sviluppo separato. Una copia temporanea con lista esplicita
esclude dati, cache, vecchi ZIP e vecchi report. Lo scanner delle credenziali
usa `--no-verify`: nessuna credenziale candidata viene verificata online.

```sh
python -m pip install -r requirements/development.txt
python -B tools/security_audit.py --report dist/security-audit.json
```

La scansione completa conserva anche gli avvisi Bandit LOW. La politica locale
blocca problemi MEDIUM/HIGH, potenziali credenziali non risolte, errori dello
scanner o scansione incompleta. Non sono disabilitate intere famiglie di regole
e non viene usata una baseline per nascondere i risultati iniziali.
Il report contiene versioni degli strumenti, hash dei file, percorsi, righe,
regole e livelli. Non salva frammenti di sorgente o valori delle credenziali.
Il resoconto generato sta in `dist/` o `output/`, esclusi dal repository sorgente.
La stessa procedura fa parte di GitHub CI e della preparazione verificata dello ZIP.

## Riscontri e correzioni

La prima scansione della 15.6.33 ha riportato un avviso MEDIUM B310 nello strumento
opzionale `tools/build_italic_index.py`: la funzione HTTP non limitava direttamente
gli schemi accettati. Le chiamate esistenti usavano già l'API ufficiale; la 15.6.34
rende il vincolo esplicito e verifica anche ogni redirect: solo HTTPS,
`italic.units.it`, porta standard e percorso `/api/v2/`, senza credenziali URL.
Non viene aggiunta alcuna eccezione SSL. Test offline verificano anche i rifiuti
di file locali, HTTP, altri host e redirect fuori dall'API.

L'unico candidato di detect-secrets nella prima scansione era la credenziale
fittizia di un test che verifica la redazione dei log. Non è una credenziale
reale, non viene trasmessa e ora è annotata soltanto su quella riga come fixture
sintetica. Le altre regole e gli altri file continuano a essere controllati.
Dopo la correzione e l'annotazione, la scansione locale non ha riportato MEDIUM,
HIGH o ulteriori candidati di credenziali. Il report generato della release finale
è il riferimento per conteggi e hash esatti.

## Esito locale della release 15.6.34

- **0** segnalazioni Bandit HIGH e **0** MEDIUM.
- **0** potenziali credenziali non risolte dopo la revisione della fixture sintetica.
- **228** avvisi Bandit LOW mantenuti nel report: B110 166, B112 16, B311 2,
  B404 4, B101 36, B603 4. Nessun errore di scansione.
- **164** file ammessi con hash nel report, compresi i file di configurazione;
  l'immagine è controllata anche dal builder, non trattata come sorgente Python.
- **248** regressioni e smoke QGIS superati localmente su QGIS 3.44.9/macOS.

I conteggi si riferiscono a questi sorgenti e a queste versioni degli strumenti;
non significano assenza garantita di vulnerabilità.

## Avvisi LOW mantenuti visibili

- **B110/B112:** gestione ampia delle eccezioni o proseguimento dopo un errore,
  diffusi nei percorsi facoltativi QGIS/DEM/rete. Non sono prova automatica di una
  vulnerabilità, ma possono ridurre la diagnostica: restano debito tecnico.
- **B311:** numeri pseudocasuali usati per il centro geografico approssimato e
  fixture scientifiche; non generano password, token o materiale crittografico.
- **B404/B603:** avvio di interpreti negli strumenti di test/build/scansione,
  con lista di argomenti e senza `shell=True`; non eseguono testo del cartellino.
- **B101:** assert nei test e nel benchmark, non controlli di autorizzazione
  del plugin. Gli strumenti di verifica vanno eseguiti senza l'opzione Python `-O`.

Questi avvisi non sono stati cancellati o dichiarati tutti risolti. Il miglioramento
progressivo dei fallback e della gestione delle eccezioni resta utile.

## Controlli aggiuntivi e limiti

Il controllo dei sorgenti cerca chiavi private e chiamate esplicite di bypass
TLS. Il builder usa una lista di file ammessi, verifica sintassi, metadati,
limite di 25 MB, contenuto ZIP e hash; esclude directory private e collegamenti
simbolici. Le richieste del plugin usano la rete QGIS; lo strumento opzionale
standalone dell'indice usa la rete Python con i vincoli HTTPS descritti sopra.
L'endpoint Photon può essere configurato dall'utente: scegliere un servizio
fidato, preferibilmente HTTPS; una scelta HTTP non protegge il testo trasmesso.

Non è stata dimostrata la sicurezza di qualunque servizio esterno, provider,
dataset o ambiente dell'utente. Il risultato favorevole della scansione locale
non sostituisce le regole e l'approvazione del catalogo QGIS. Il sito può usare
versioni e soglie differenti. Anche provenienza/licenze delle risorse e correttezza
scientifica restano verifiche distinte.

Fonti: [strumenti QGIS](https://plugins.qgis.org/docs/security-scanning/tools),
[Bandit](https://bandit.readthedocs.io/en/latest/start.html),
[detect-secrets](https://github.com/Yelp/detect-secrets).
