# Compatibilità QGIS — GeoLichen 15.6.34

La release è sperimentale. I metadati consentono QGIS da **3.40** alla serie
**4.2**, con Python, NumPy e GDAL/OGR normalmente forniti da QGIS.
Versioni precedenti e future non sono dichiarate per questa distribuzione.

## Evidenze e limiti

| Ambiente | Evidenza disponibile | Limite |
| --- | --- | --- |
| macOS, QGIS 3.44.9 / Qt 5 | Suite locali e prove d'uso dell'autore | Non tutte le configurazioni dei provider |
| Linux, QGIS 3.40.15 / Qt 5 | Suite complete nel runtime reale su GitHub | Prova automatica senza operatore |
| Linux, QGIS 4.2.3 / Qt 6 | Suite complete nel runtime reale su GitHub | Prova automatica senza operatore |
| Windows, QGIS 3.40 o 4.2 | Procedura di test pronta | Release corrente non ancora verificata |
| QGIS 4, uso interattivo completo | Checklist qui sotto | Ancora da completare |

I risultati delle revisioni precedenti sono conservati in [VERIFICATION](VERIFICATION.md).
Il [workflow corrente](https://github.com/LucaGrazia0/geolichens/actions/workflows/checks.yml)
registra la versione effettiva QGIS, Qt e Python nei report. Un job configurato
non è una prova riuscita: controlla l'esito della revisione che stai distribuendo.
I test non misurano accuratezza scientifica né disponibilità di Photon, ITALIC
o Overpass, e non attestano ogni versione intermedia nell'intervallo dichiarato.

## Compatibilità implementata

Il port iniziato nella 15.6.19 usa import QAction appropriati, enum Qt/QGIS con
namespace, QMetaType per i campi recenti e conversioni esplicite degli enum.
La 15.6.32 ha corretto il formato RichText della finestra candidato dopo una
prova nel vero runtime Qt 6. Il vecchio flag supportsQt6 non è utilizzato.
Le modifiche di compatibilità non cambiano formule ecologiche o incertezze.

## Suite automatica sul computer da verificare

Usa il Python incluso in QGIS. Su Windows apri la OSGeo4W Shell dell'installazione
corretta e raggiungi la cartella dei sorgenti:

```text
python -B tools/run_checks.py --expect-qgis 3.40 --report dist/checks-windows-340.json
```

Per QGIS 4.2 usa `--expect-qgis 4.2`. Il controllo fallisce se la versione non
corrisponde. Su Linux/macOS può essere necessario `QT_QPA_PLATFORM=offscreen`.
Non installare PyQt6 nel Python di un QGIS basato su Qt 5.
Gli script usano dati sintetici e profili temporanei; lo smoke usa un server HTTP
locale. La suite Qt6 standalone resta un controllo aggiuntivo dei widget e non
sostituisce il runtime QGIS, ora coperto dai job Linux.

## Checklist interattiva

Usa un profilo dedicato e copie dei tuoi dati, senza sovrascrivere gli originali.

1. Installa lo ZIP corrente, apri il pannello, configura i campi e seleziona un record.
2. Cerca e scegli una località; controlla buffer circolare e geometrie manuali.
3. Verifica copertura DEM, quota, passo griglia e layer ambientali selezionati.
4. Esegui analisi step by step: Avanti, scelta sulla mappa, Riprova, Sì, editor.
5. Verifica Cancel, Esci, Esc e clic destro; nessuna conferma deve essere implicita.
6. Controlla preview, rank, coordinate, quota e le due incertezze nel candidato.
7. Crea colonne mancanti su una tabella di prova; verifica anche il flusso automatico.
8. Copia su più righe scelte esplicitamente e controlla quelle non selezionate.
9. Verifica punti e Suitability Surface a più zoom, con o senza layer facoltativi.
10. Salva/esporta in GeoPackage, riapri il progetto e verifica mapping e risultati;
    controlla anche disattivazione e riattivazione del plugin.

Per la preparazione dello ZIP e gli scanner offline vedi [DEVELOPMENT](DEVELOPMENT.md).
