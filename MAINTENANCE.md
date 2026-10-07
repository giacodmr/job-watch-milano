# Manutenzione Job Watch

`current_jobs_jw*.json` è lo stato ufficiale corrente in perimetro; `job_memory_jw*.json` conserva semantic/user/surfacing. Queue e analysis sono funzioni in memoria. `daily_worklist.json` è una proiezione piccola. JD recuperate just-in-time, senza cache versionata. `archive/vacancies_YYYY_MM.jsonl` contiene soltanto metadata storici compatti e non viene letto da collection, worker, Daily o certification.

La configurazione `companies_job_watch_v2.json` contiene `allowed_locations`. Le vecchie indicazioni descrittive `locations` non autorizzano London/Luxembourg. Per abilitarle modifica esplicitamente l'allowlist della società canonica; nessuna categoria CORE/SELECTIVE/TIER governa il filtro.

- London: Mastercard, Amazon, Prima Assicurazioni, American Express, Uber, Revolut, Satispay, EssilorLuxottica, Snam, Webuild, Campari Group (alias Campari).
- Luxembourg: Amazon, Mastercard, Ferrero.

Le ricerche italiane mantengono lo scope precedente. Le soglie esistenti sono 70 Milano/Roma e 80 London/Luxembourg, ora in `reporting_thresholds_by_geography`: nessuna nuova soglia inventata. Fonti che espongono soltanto link senza location possono ancora richiedere una richiesta alla pagina di dettaglio per leggere la location. Dopo quella verifica non parte alcun enrichment/analisi per le location escluse. Per inventory strutturati il filtro viene applicato nel loop metadata, prima di qualsiasi JD fetch del worker.

Settimanalmente leggi `partial_remediation` nell'audit. Priorità Amazon/Mastercard e mapping FULL con coverage PARTIAL; verifica adapter/paginazione/ID su fonte ufficiale senza promuovere label artificialmente. Source/record errors restano warning; batch errors bloccano solo il batch interessato. Le vacancy UNKNOWN non vengono dichiarate chiuse senza evidenza; le scelte attive con location ancora ignota conservano una minima riga UNKNOWN e la decisione.

I collector conservano `first_seen_at`, aggiornano `last_seen_at` e archiviano i CLOSED durante sync, con la stessa transazione che li rimuove dal current. Le memorie conservano tutte le decisioni pregresse, anche per vacancy chiuse, per evitare perdita di scelte e consentire deduplica su identità. Le vecchie UUID Amazon sono riconciliate al public job ID tramite URL; le scelte più recenti governano la proiezione e le originali restano intatte.

Tutti i writer usano il lock/journal locale. Gli append all'archivio registrano un offset nel journal: un crash ripristina l'offset e completa l'append senza duplicarlo. Gli snapshot worker includono soltanto current/memory del proprio batch, regole, routing e configurazione aziendale. Per checkouts Git diversi, il lock locale non basta: integra i quattro file disgiunti attraverso Git e mantieni la serializzazione Actions per la pubblicazione condivisa. Non sovrascrivere main da un vecchio checkout.

Controlli prima di pubblicare:

```sh
python preflight_job_watch.py
python validate_job_watch_inputs.py
python -m unittest -q
python job_watch.py sync
python validate_job_watch_state.py --strict
```

Per restaurare un checkout dello schema precedente, esegui esplicitamente `python job_watch.py migrate` prima del sync. L'upgrade verifica equivalenza e ownership prima di rimuovere il legacy; rifiuta stati misti e non sostituisce memorie già esistenti. Il modulo resta come upgrade testabile per restore/rebase e per i fixture permanenti; nessun reader legacy è attivo nel runtime. `state_migration_report.json` è un receipt freddo, con hash sorgenti, conteggi e decisioni irriconciliabili: non caricarlo nella Daily. ION Group esclusa conserva lì la sua scelta storica.
