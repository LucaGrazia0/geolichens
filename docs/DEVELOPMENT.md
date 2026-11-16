# GeoLichen 15.6.32 — sviluppo, verifiche e distribuzione

## Versione di riferimento

Il commit locale `ba40402` conserva la 15.6.30 precedente a queste modifiche.
Lo ZIP `dist/geolichen-15.6.30.zip` resta disponibile, con il suo manifest.
I dati del progetto e le cache non fanno parte dei commit o delle distribuzioni.

## Controlli prima del commit

Con un ambiente Python di sviluppo separato, Python 3.10 o successivo:

```sh
python -m pip install -r requirements/development.txt
python -B tools/check_source.py
ruff check .
python -B tests/regression_release_tools.py
```

`pre-commit install` abilita facoltativamente i due controlli nel checkout di
sviluppo; non è eseguito automaticamente e non è richiesto agli utenti QGIS.
Ruff controlla errori di sintassi e nomi non definiti, senza riformattare tutto
il codice. Il controllo locale dei sorgenti verifica metadati, sintassi,
versione del manuale, chiavi private e chiamate esplicite di bypass TLS.
Questi controlli non sostituiscono un audit di sicurezza o la scansione QGIS.

## Suite completa nel Python di QGIS

Su macOS, con l'installazione usata per questa release:

```sh
QT_QPA_PLATFORM=offscreen /Applications/QGIS.app/Contents/MacOS/python -B tools/run_checks.py --report dist/checks-macos.json
```

Su Windows, apri la **OSGeo4W Shell della versione QGIS da verificare**, raggiungi
la cartella dei sorgenti e lancia:

```text
python -B tools/run_checks.py --expect-qgis 3.40 --report dist/checks-windows-340.json
```

Per QGIS 4 cambia il prefisso richiesto con la versione realmente installata,
per esempio `--expect-qgis 4.2`. Il controllo fallisce se il runtime non coincide.
Non installare PyQt6 nel Python di QGIS 3. Le suite creano dati sintetici e profili
temporanei; lo smoke usa un server HTTP locale. Non interrogano i servizi pubblici
né modificano i dataset dell'utente. Ogni suite ha un limite di 300 s e un log
separato; qualsiasi fallimento impedisce la preparazione verificata dello ZIP.

Le suite coprono formule/ranking/incertezze, campionamento, ricerca e cache,
selezione dei record, flusso candidato, scrittura/copia, diagnostica e ciclo
caricamento/apertura/chiusura del plugin. Non provano la correttezza scientifica
su dati reali né la disponibilità dei servizi esterni.

## Compatibilità e GitHub Actions

`.github/workflows/checks.yml` prepara verifiche su push, pull request o avvio
manuale: controlli dei sorgenti, suite nel runtime QGIS 3.40 e QGIS 4.2 e, solo
dopo esito positivo di entrambi, ZIP e sorgenti pubblici come artefatti.
Le immagini ufficiali Linux sono fissate a versione e digest; il report registra
QGIS, Qt, Python e sistema. Un'immagine Linux non verifica Windows o macOS.

La configurazione è ora attiva nel repository pubblico: ogni push o pull request
avvia i controlli. Il workflow usa permessi di sola lettura e nessun segreto;
non pubblica sul catalogo QGIS. La prima esecuzione ha rilevato il formato Qt 6
della finestra candidato e un’ipotesi errata del test sui vicini equidistanti,
corretti nella 15.6.32. Consulta l’esito della revisione corrente su GitHub Actions.
Per stato reale e prova interattiva vedi [compatibilità](QGIS4_COMPATIBILITY.md).
Fonti: [immagini ufficiali](https://github.com/qgis/qgis-docker),
[test dei plugin](https://github.com/qgis/qgis-docker/blob/main/desktop/README.md).

## Preparare una distribuzione verificata

Usa il Python di QGIS:

```sh
python -B tools/prepare_release.py --source-dir dist/geolichen-15.6.32-public-source
```

La procedura controlla i sorgenti, esegue tutte le suite e poi crea lo ZIP con
manifest SHA-256. Usa una cartella di esportazione nuova. Il builder usa una lista
esplicita e non attraversa dataset o vecchie distribuzioni. La configurazione di
sviluppo e GitHub entra nei sorgenti pubblici ma non nello ZIP installabile.
Il comando di basso livello `tools/build_release.py` rimane disponibile per
ispezioni locali: da solo non attesta l'esecuzione dei test.

Verifica la corrispondenza tra versione, codice pubblico e ZIP prima di qualsiasi
caricamento. Le prove locali non autorizzano una compatibilità universale:
conserva report e lista delle prove manuali ancora da fare.

## Diagnostica

La scheda **GeoLichen** nei Messaggi di log QGIS raccoglie avvisi e guasti dei
servizi. L'opzione nella finestra Performance abilita dettagli aggiuntivi nel
solo profilo QGIS corrente. Nessuna configurazione globale di logging è cambiata,
nessuna eccezione SSL è aggiunta. URL completi e risposte ITALIC non sono scaricati
nel registro centralizzato; restano i soli nomi dei server e le categorie d'errore.
I messaggi operativi del pannello e la diagnostica scientifica esistente restano
consultabili. Prima di condividere esportazioni controlla eventuali dati privati.

## Misurare le prestazioni

```sh
python -B tools/benchmark_ecological_analysis.py > dist/benchmark-local.json
```

Il benchmark sintetico confronta anche l'uguaglianza dei risultati. È separato
dai test di correttezza: i tempi dipendono da hardware e runtime, quindi non c'è
una soglia universale. Confronta lo stesso scenario su Windows e macOS; la rete
va misurata separatamente. Nessun peso ecologico è modificato dalla 15.6.31.
