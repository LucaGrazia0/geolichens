# Pubblicazione GeoLichen

Preparazione del 15 ottobre 2026. Il plugin non è ancora pubblicato.

## Da risolvere prima del rilascio pubblico

1. Il repository pubblico è [LucaGrazia0/geolichens](https://github.com/LucaGrazia0/geolichens),
   con Issues attive. Pubblicare soltanto codice, documentazione, licenza e
   strumenti di sviluppo. Non caricare ZIP, dataset o cache.
2. `knowledge/`, `data/`, `examples/`, cache e snapshot restano privati e sono
   esclusi sia dal repository sia dal pacchetto QGIS. Il codice gestisce la
   mancanza dei dizionari opzionali e dell'indice locale con i fallback esistenti.
3. Non pubblicare vecchi commit locali contenenti dataset: il primo commit
   pubblico deve essere creato da un'esportazione pulita, con una nuova cronologia.
4. I tre link in `metadata.txt` puntano al repository indicato dall'utente.
   Verificare che README e codice siano presenti nella revisione pubblicata.
5. Eseguire una prova interattiva su una copia dei propri dati: avvio, lettura
   ITALIC, geocodifica con chiave personale, selezione candidato, correzione
   manuale, conferma/salvataggio, riapertura progetto, disattivazione plugin.
   Ripetere su Windows e Linux. I controlli automatici non dimostrano l'accuratezza
   scientifica né la compatibilità con tutti i sistemi.

## Preparare i sorgenti e lo ZIP

`python3 tools/build_release.py --preview` produce uno ZIP esplicitamente
preliminare per le prove locali. `python3 tools/build_release.py` richiede tutti
i metadati di pubblicazione. Entrambi producono un manifest SHA-256 per verificare
che ogni file del pacchetto corrisponda ai sorgenti.

Per creare un albero sorgente pulito da caricare su GitHub:

```sh
python3 tools/build_release.py --preview --source-dir dist/public-source/geolichen
```

La directory risultante comprende anche strumenti di sviluppo e test, ma
esclude tutti i dataset (`knowledge/`, `data/`, `examples/`, JSON e CSV),
cache, snapshot, file nascosti (eccetto `.gitignore`), bytecode,
ZIP, binari, manifest generati e vecchie note. Copiare i file sorgente,
non il contenitore `dist`, nel repository. Prima del rilascio generare di nuovo
senza `--preview` e confrontare il manifest con la revisione pubblicata.

## Invio al catalogo QGIS

1. Accedere con il proprio account OSGeo al
   [catalogo QGIS](https://plugins.qgis.org/plugins/).
2. Usare [Upload a plugin](https://plugins.qgis.org/plugins/add/) e caricare
   lo ZIP finale creato dal builder, dopo aver pubblicato la stessa revisione
   dei sorgenti. Non usare lo ZIP automatico di GitHub: la cartella radice
   potrebbe avere un nome diverso da `geolichen`.
3. Controllare le email e la sezione Security della versione caricata;
   correggere gli eventuali problemi e attendere l'approvazione dei revisori.
4. Mantenere `experimental=True` fino a quando le prove giustificano un rilascio
   stabile. Non dichiarare QGIS 4 senza migrazione e prove dedicate.

Le procedure ufficiali sono nelle
[linee guida](https://plugins.qgis.org/docs/publish) e nella
[procedura di approvazione](https://plugins.qgis.org/docs/approval).
