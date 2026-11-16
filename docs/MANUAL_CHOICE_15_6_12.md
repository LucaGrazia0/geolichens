# GeoLichen 15.6.12 — scelta guidata del candidato ecologico

Il pulsante **Analisi ecologica step by step** usa il buffer corrente
e la pipeline già esistente per generare, valutare e ordinare i candidati.

Dalla 15.6.13 **Esci** è a sinistra, mentre **Riprova** e **Sì** sono affiancati
a destra. La configurazione si estende per l'intera larghezza del pannello.
**Ricerca della località** e il comando del centroide sono sulla stessa riga,
in proporzione 4:1; il centroide usa l'icona mirino con badge verde fornita
dall'utente e conserva il tooltip «Sono a posto così».

1. **Scelta del punto ecologico** mostra il numero dei candidati. **Avanti**
   attiva la scelta sulla mappa; **Cancel** chiude la procedura lasciando la
   griglia disponibile e senza scrivere nelle tabelle.
2. Il cursore mostra lo snap al candidato esistente più vicino. I candidati
   vengono resi visibili anche quando la visualizzazione scelta è solo heatmap;
   la superficie e l'impostazione di visualizzazione non vengono ricalcolate.
3. Il clic apre **Vuoi usare questo punto di rank …?**, con GSS e distanza dal clic:
   **Sì** apre la finestra candidato esistente; **Riprova** mantiene la stessa
   griglia e consente un altro clic; **Esci** ripristina lo strumento precedente.
   La chiusura della finestra equivale a Esci. Durante la scelta, anche Esc e
   clic destro escono senza scrivere dati.
4. Nella finestra candidato restano coordinate, quota DEM, scelta/creazione dei
   campi di destinazione, incertezze, diagnostica e validazione. L'accettazione
   di questa finestra scrive i risultati attraverso il metodo già esistente.
   L'annullamento non scrive. La seconda domanda riepilogativa successiva a
   questa finestra è rimossa.

Non esiste più un pulsante separato **Conferma punto ecologico**. La distinzione
fra analisi guidata e automatica resta nei due pulsanti affiancati nello stesso
box; dalla 15.6.14 **Copia su altri record** occupa la riga sottostante. Il titolo
della configurazione è su una sola riga.

## Prestazioni e gestione dello stato

- Analisi e ranking vengono eseguiti una volta per avvio. Riprova e movimenti
  del cursore non richiamano ITALIC, geocodifica o scoring.
- Un indice spaziale in un sistema metrico locale seleziona i candidati vicini
  al clic; il controllo finale usa la distanza metrica esistente. Se l'indice
  non è disponibile si conserva la scansione precedente come fallback.
- I dettagli di incertezza per il candidato vengono preparati solo dopo Sì.
- Il passaggio a un altro strumento QGIS interrompe la cattura senza sostituire
  il nuovo strumento. Invalidazione del buffer e unload disconnettono i segnali.
- Prima di aprire la finestra e di scrivere, si verifica che il risultato e il
  record selezionato corrispondano ancora all'analisi corrente.
- **Analisi ecologica automatica** conserva il suo percorso diretto al rank 1
  e non apre le finestre della selezione manuale.

Questa modifica riduce i passaggi manuali e il lavoro durante lo snap. Non
modifica l'algoritmo ecologico, i pesi, il ranking, il passo della griglia o
le formule di incertezza; la durata del calcolo iniziale dipende ancora da
numero dei candidati, layer, DEM e servizi remoti.

## Verifica

La suite `tests/regression_interface.py` include i rami Avanti/Cancel,
Sì/Riprova/Esci, Escape/clic destro, cambio dello strumento, cambio del record,
visibilità dei candidati sopra la heatmap, ripristino dello strumento precedente
e indipendenza del flusso automatico. Verifica anche che Riprova non richiami
ranking o calcolo dell'incertezza e che lo snap riutilizzi l'indice spaziale.
I test precedenti di conferma continuano a verificare coordinate, quota e
incertezze scritte nella tabella e nei punti confermati.
