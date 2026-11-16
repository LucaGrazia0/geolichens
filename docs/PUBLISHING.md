# Pubblicazione GeoLichen — 15.6.34

Il codice pubblico è su [GitHub](https://github.com/LucaGrazia0/geolichens),
con Issues e controlli automatici attivi. L'invio al catalogo QGIS non è ancora
stato effettuato. Questa release rimane **sperimentale**.

## Stato e verifiche ancora necessarie

- Il repository contiene soltanto codice, documentazione, licenza, icona e
  configurazione di sviluppo. Dataset, cache, snapshot, ZIP e cronologia privata
  non devono essere caricati nel repository sorgente.
- Le suite sono passate nei runtime Linux/QGIS 3.40.15 e 4.2.3, con verifica
  locale macOS/QGIS 3.44.9. La prova Windows e l'uso interattivo completo di
  QGIS 4 restano distinti e ancora da completare.
- I metadati consentono QGIS 3.40–4.2. Non dichiarano supporto alle vecchie
  versioni 3.22 o a versioni future non verificate. L'intervallo non certifica
  ogni sistema, provider o configurazione compresa tra gli estremi.
- La ricerca attuale usa Photon/OpenStreetMap senza API key MapTiler;
  Overpass scarica i percorsi e ITALIC fornisce profili ecologici. Il pacchetto
  non include questi dataset e non garantisce la disponibilità dei servizi.
- Per risorse esterne e icona controllare [THIRD_PARTY](../THIRD_PARTY.md).
  La provenienza/licenza originale dell'immagine fornita dall'autore del
  progetto deve essere documentata prima dell'invio al catalogo.
- Il [resoconto di sicurezza](SECURITY_REVIEW.md) descrive strumenti, risultati
  e limiti; non equivale all'approvazione del catalogo o a validazione scientifica.

## Preparare uno ZIP verificato

Nel Python di sviluppo separato installa `requirements/development.txt`.
Nel Python di QGIS esegui, indicando quel Python per gli scanner:

```sh
python -B tools/prepare_release.py --security-python /percorso/ambiente-sviluppo/bin/python --source-dir dist/geolichen-15.6.34-public-source
```

Su Windows l'interprete di sviluppo avrà normalmente un percorso come
`C:\ambiente-sviluppo\Scripts\python.exe`; avvia il comando dalla OSGeo4W Shell
per il QGIS da verificare. Non installare PyQt6 o gli scanner nel QGIS dell'utente.

La procedura controlla i sorgenti, esegue la scansione offline e le suite,
quindi genera `dist/geolichen-15.6.34.zip`, manifest SHA-256 e report.
Qualsiasi errore bloccante impedisce la creazione del nuovo pacchetto.
Gli avvisi Bandit di livello basso restano nel report e richiedono valutazione.

Il comando di basso livello `tools/build_release.py` genera uno ZIP senza
attestare l'esecuzione dei test o degli scanner. `--preview` serve solo a prove
locali con metadati incompleti: non è un pacchetto da inviare al catalogo.

L'esportazione pubblica comprende configurazione GitHub/pre-commit, requisiti
di sviluppo e strumenti; lo ZIP installabile contiene la sola lista ammessa dal
builder. Dati privati e vecchie distribuzioni non sono attraversati. Usa una
cartella di esportazione nuova e verifica che codice pubblico e manifest siano
allineati. Non inviare la cartella `dist` né il sorgente ZIP automatico di GitHub.

## Prova interattiva e invio

Su una copia modificabile dei dati verifica: selezione record, ricerca e scelta
località, buffer automatico/manuale, lettura ITALIC, percorsi OSM o layer locali,
candidato guidato/automatico, coordinate/quota/incertezze, copia su altri record,
salvataggio e riapertura del progetto e disattivazione del plugin.

Accedi con il tuo account OSGeo a [Upload a plugin](https://plugins.qgis.org/plugins/add/)
e carica lo ZIP finale corrispondente ai sorgenti pubblici. Controlla gli esiti
nella scheda Security della versione e le eventuali richieste dei revisori.
Bandit e detect-secrets vengono eseguiti anche sul catalogo con le sue regole:
una scansione locale favorevole non garantisce l'approvazione.

Mantieni `experimental=True` finché prove d'uso e validazione giustificano una
release stabile. Il workflow GitHub prepara artefatti dopo controlli riusciti,
ma non carica automaticamente nulla nel catalogo QGIS.

Fonti: [pubblicazione](https://plugins.qgis.org/docs/publish),
[scansione](https://plugins.qgis.org/docs/security-scanning),
[strumenti di sicurezza](https://plugins.qgis.org/docs/security-scanning/tools).
