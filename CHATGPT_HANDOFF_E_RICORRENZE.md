# Job Watch — handoff unico e istruzioni delle ricorrenze

Repository `giacodmr/job-watch-milano`. Branch operativo di produzione: `main`. PR #11 (`refactor/job-state-simplification`) è già merged e non è più il branch operativo. Worker, Daily e collector sono componenti di produzione; durante le run ordinarie non modificare codice, regole, allowlist, soglie o pianificazioni.

I pilot live hanno verificato packet 10/20, JD temporanee, errori isolati, APPLY atomico, checkpoint e replay SELECT/APPLY immutabili, senza surfacing. Il bridge v2 è ora il percorso di produzione: non ridisegnarlo durante l'operatività ordinaria.

## Configurazione canonica di produzione

| Componente | Orari Europe/Rome | Limite e funzione |
|---|---|---|
| Collector GitHub | 23:00; recovery 23:45 + fallback | Recovery per snapshot stale/incoerenti, FAILED/NOT_CHECKED e copertura Amazon incompleta; PARTIAL persistenti restano maintenance debt |
| Job Watch Worker | 00:00, 02:00, 04:00, 05:30 | Una sola task, massimo 20 tentativi/run, normalmente 10 + 10 |
| Job Watch Daily | 09:00 | Reporting/surfacing/reminder/scelte attive |

La raccolta delle 23:00 del giorno D serve Worker e Daily del giorno D+1. Timestamp UTC originali preservati; freschezza calcolata Europe/Rome con confine operativo alle 23:00, inclusi ritardi oltre mezzanotte e cambio d'ora.

**Collector recovery e Worker preflight sono due decisioni diverse.** `collection_freshness.recovery_needed` può chiedere al Collector un nuovo tentativo quando ci sono FAILED/NOT_CHECKED o la copertura Amazon target non è VERIFIED. Il Worker, invece, usa `collection_freshness.worker_snapshot_ready`: se gli snapshot del workday e i checkpoint sono freschi e coerenti, può analizzare le vacancy effettivamente raccolte anche in presenza di PARTIAL, FAILED o NOT_CHECKED su alcune fonti. La coverage resta esplicitamente degradata e non autorizza chiusure da fonti non verificate, ma non deve bloccare globalmente tutta la coda semantica. PARTIAL non viene ritentato automaticamente a ogni fallback: la remediation è maintenance non bloccante secondo `job_watch_rules.json`.

Nessun budget persistente per notte: 80 è soltanto il massimo teorico 4 × 20. Una run manuale aggiuntiva autorizzata ha il proprio limite. Con EMPTY si passa agli altri JW; zero lavoro eleggibile termina normalmente la run. Il secondo packet usa sempre lo stato fresco dopo APPLY e checkpoint del primo.

## Request residue e stato in volo

La directory `.job_watch_bridge/requests/` può contenere request storiche pilot/manual già checkpointate. Questo è normale: in particolare una request `PARTIAL` può restare per conservare retry JD o bozze residue. La sola presenza di file nella directory non significa che un altro Worker sia attivo.

Una lavorazione è da considerare realmente «in volo» solo se manca un receipt/checkpoint remoto coerente oppure se la relativa esecuzione GitHub Actions è effettivamente pending/running. Le request checkpointate vanno riconciliate; non vanno cancellate alla cieca e non devono bloccare un nuovo SELECT eleggibile.

## Retry tecnico JD

La memoria autorevole del JW conserva `records[job_key].jd_fetch`: evidenza (fingerprint + URL sorgente), attempts, last_failure_at, retry_from e status. Un fallimento iniziale è attempts=1; tre retry nei giorni successivi portano a attempts=4 e `JD_UNAVAILABLE`. Il retry usa il giorno di calendario Europe/Rome, mai altri slot della stessa giornata. Una nuova evidenza riapre il lifecycle; il semplice passare del tempo no. Un fetch riuscito rimuove i metadata di fallimento, lasciando la review da produrre a ChatGPT.

SELECT salva memoria tecnica e receipt nella stessa transazione dopo l'upload dell'artifact. Il packet contiene lo snapshot esatto della memoria risultante, necessario all'APPLY. Nessuna JD, Semantic Review fittizia, scelta utente o surfacing viene salvata per un errore tecnico. `JD_UNAVAILABLE` è escluso dalla queue automatica, resta nel debito semantico e non certifica un'analisi completata.

Le autorità restano `current_jobs_jw1..4.json` e `job_memory_jw1..4.json`; `daily_worklist.json` è una proiezione. Nessun file legacy, nuova coda persistente, cache JD, lease o database. Un solo writer GitHub con `cancel-in-progress: false`, una request realmente in volo, reload remoto prima di SELECT/APPLY e nessun force push.

## Prompt permanente — Job Watch Worker

Usa come fonte canonica `CHATGPT_WORKER_PROMPT.txt`. In sintesi: branch operativo `main`; preflight su `worker_snapshot_ready`, non su `recovery_needed`; riconcilia request/receipt; non scambiare coverage debt o vecchie PARTIAL checkpointate per lavorazioni attive; massimo 20 tentativi/run normalmente 10+10; SELECT v2 con JD complete temporanee; review reali solo per JD riuscite; APPLY atomico; replay idempotenti; nessun surfacing o user decision dal Worker.

## Prompt permanente — Job Watch Daily

Sei «Job Watch Daily» di `giacodmr/job-watch-milano`. Branch operativo: `main`. Prepara il report ogni giorno alle 09:00 Europe/Rome usando lo stato persistito del repository e il Worker notturno separato per arretrato e nuove review.

Leggi `DAILY.md`, `job_watch_rules.json`, `daily_worklist.json` e il riepilogo health aggiornati. Mostra `NEW_INTERESTING`, tutte le scelte `INTERESTED`/`TO_REVIEW` in perimetro e i `REMINDER` ammessi. Usa link ufficiali, motivo del fit, requisiti e incertezze determinanti. `NEW_CANDIDATE` non significa opportunità già valutata. Non caricare inventory, memoria integrale, archivi o tutte le JD nel contesto.

Non chiedere smaltimenti manuali né attendere indefinitamente le analisi mancanti. Non fabbricare scelte utente. `NOT_INTERESTED` sopprime l'identità anche al cambio fingerprint; `APPLIED` resta fuori dalla normale re-review.

Registra surfacing solo dopo un'effettiva comunicazione all'utente attraverso il percorso validato di `DAILY.md`. Una review tecnica, un packet o un report preparato non sono consegne. Il bridge semantic v2 non scrive surfacing. In produzione il workflow Sync valida `daily_updates.json`; se la persistenza fallisce, non simulare history.

Esegui la discovery leggera prevista da `DAILY.md` con query, data, fonte ed esito reali; nuove scoperte entrano nell'inventory ufficiale riconciliata e nel Worker prima di diventare reportable. Coordina ogni patch con il writer unico, usa uno snapshot fresco e verifica il checkpoint remoto.

Riporta una riga di freschezza/coverage e usa solo le certificazioni persistite: `DAILY_COMPLETE` e `FULL_SEMANTIC_COMPLETE` sono distinte. Non cambiare regole, scoring, geografia, soglie o ricorrenze durante il report. Nessuna API a pagamento.
