# Esito operativo — retry JD e raccolta serale

**GO tecnico.** Branch `refactor/job-state-simplification`, PR #11 open/non merged.
SHA iniziale: `aea8cf764d9e99c0214a5e9c653b7245aa071dde`.
SHA finale: HEAD della PR, riportato nel messaggio conclusivo (il documento appartiene allo stesso commit).
Main remoto verificato prima della pubblicazione: `791eba5e49a14b1b61a302ca22975eb55141f285`; nessuna scrittura a main.

## Già disponibile / aggiunto

Già verificati live: packet 10/20, JD temporanee, errori isolati, APPLY atomico, checkpoint remoto, replay SELECT/APPLY, writer unico e separazione Worker/Daily. Nessun ridisegno del bridge.

Aggiunti: lifecycle tecnico finito nella memoria autorevole del JW, selezione dei soli retry eleggibili, alias protetti, snapshot del packet coerente con il checkpoint tecnico SELECT, contatori tecnici distinti nei riepiloghi, raccolta serale e freschezza della giornata successiva. Nessuna modifica a scoring, regole, geography, salary, L.68/99 o priorità aziende.

## Schema esatto

`job_memory_<jw>.json → records[job_key].jd_fetch`:

```json
{"evidence":{"fingerprint":"fp","source_url":"https://official.example/job"},"attempts":1,"last_failure_at":"2026-10-08T00:00:00Z","retry_from":"2026-10-09","status":"RETRY_PENDING"}
```

Campi obbligatori esattamente questi. attempts è 1–4; retry consumati = attempts−1. Fallimento iniziale + tre retry nei giorni di calendario Europe/Rome successivi. Dopo attempts=4: status=JD_UNAVAILABLE, retry_from=null. Nessun rientro per il semplice passare del tempo. Fingerprint o URL nuovo rende irrilevante il vecchio stato e il prossimo fallimento riparte da attempts=1. Il fetch riuscito cancella soltanto i metadata di fallimento; la review resta responsabilità di ChatGPT. Gli alias della stessa evidenza non aggirano il limite.

SELECT predice il byte hash della memoria risultante e lo inserisce nel packet prima dell'upload. La finalizzazione controlla lo snapshot sorgente e salva memoria tecnica + receipt nello stesso journal, poi Git li pubblica insieme. Il receipt espone technical_retry; APPLY usa lo snapshot del packet e non incrementa nuovamente i tentativi. Tutte le JD fallite non richiedono un APPLY vuoto. PARTIAL salva le review valide. Replay senza fetch o cambi ai contatori.

JD_UNAVAILABLE non è ANALYZED, NOT_INTERESTED o surfaced. I pending semantici totali lo includono, mentre la queue automatica lo esclude. Zero pending processabili non autorizza FULL_SEMANTIC_COMPLETE. Scelte attive preservate.

## Orari canonici Europe/Rome

| Componente | Orari | Stato |
|---|---|---|
| Collector GitHub | 23:00, recovery 23:45 | Configurato nella PR, non ancora su main |
| Worker ChatGPT unico | 00:00, 02:00, 04:00, 05:30 | Prompt pronto; task non creata/attivata |
| Daily ChatGPT esistente | 09:00 | Nessuna creazione o attivazione |

La raccolta delle 23:00 in D alimenta D+1. UTC reale preservato; funzione condivisa di freschezza con confine Rome alle 23:00, verificata a mezzanotte e ai cambi d'ora. La recovery salta soltanto snapshot completi e riconciliati; FAILED/NOT_CHECKED/PARTIAL ritentano.

Massimo 20 tentativi/run, normalmente 10+10 sequenziali dopo APPLY/checkpoint. 80 è soltanto 4×20: nessun file di budget, contatore globale, state machine per slot, lease, database o lock aggiuntivo. Un'intera run fallita termina; la successiva riconcilia il remoto.

Il prompt definitivo è [CHATGPT_WORKER_PROMPT.txt](CHATGPT_WORKER_PROMPT.txt); il file unico con entrambe le chat è [CHATGPT_HANDOFF_E_RICORRENZE.md](CHATGPT_HANDOFF_E_RICORRENZE.md). Quattro orari espliciti, evitando combinazioni ora/minuto indesiderate.

## Stato reale e preservazione

Pending semantici totali 34; processabili 32; retry rinviati 2; JD_UNAVAILABLE 0. Moneyfarm::17AB7ADFEC e Qonto::0b9c49fe-e8d6-4d28-b854-fbdd6b7252af hanno ciascuno due fallimenti reali documentati su identico fingerprint/URL. Importati attempts=2, ultimo fallimento 2026-10-07T16:20:49Z, retry dal 2026-10-08. I due tentativi nello stesso giorno precedono la nuova regola; contarli preserva il limite totale, senza inventare ulteriori tentativi.

Provenienza: receipt select-20261007T1446Z-manual20 (commit 9c0b2a845adf318d5d1a497cc9b9871382bafdbd) e select-20261007T1619Z-live-replayfix10 (commit 1b00088ca614d50625b05955d5c56939e14c85c6). Verificati fingerprint/URL nell'inventory di quei commit contro il current reale. Importazione una tantum; nessun reader di receipt storici nel runtime della queue.

Tutte le sezioni semantiche, user e surfacing, identità preesistenti e applied_update_ids confrontati con lo SHA iniziale: identici. Le sole aggiunte autorevoli sono metadata tecnici nelle due identità JW1. Altri JW e inventory/rules/config invariati. Nessuna JD completa aggiunta, nessun file legacy o coda duplicata. Modifica locale dell'utente nel paragrafo Daily preservata separatamente dalla pubblicazione.

## Verifica

- Preflight e persistent input validation: PASS.
- Suite completa: 137 test PASS, inclusi 17 nuovi test di retry/freschezza.
- Project, strict state validation e seconda proiezione byte-identica: PASS.
- Tutte le autorità immutate durante project: PASS.
- Workflow YAML e Python incorporato: PASS; diff check: PASS.
- Casi coperti: tentativi 1/2/3/4, blocco nella stessa giornata, terminale anche dopo mesi, nuovo fingerprint/URL, alias, successo, crash memoria/receipt SELECT, replay, nessuna review fittizia o modifica user/surfacing, 8 valide + 2 fallite, EMPTY, secondo packet fresco, mezzanotte e DST.

CI remota e audit finale del ref/PR sono verificati dopo la pubblicazione; risultati e link nel messaggio conclusivo e nella PR.

## Limiti / fase successiva

Nessun problema tecnico locale aperto. Health operativo NEEDS_REVIEW per il lavoro residuo non equivale a un test fallito. I test temporali simulano i quattro giorni; non è stata attivata una notte unattended. La configurazione delle task ChatGPT non è ispezionabile tramite gli strumenti di questa sessione; nessuna chiamata di creazione, modifica o attivazione è stata effettuata. Gli schedule GitHub eseguono il branch predefinito: quelli nuovi diventeranno operativi soltanto dopo un futuro aggiornamento autorizzato di main.

Fermarsi qui per revisione finale; merge e attivazione sono una fase separata.

Replay tecnico SELECT sul vecchio packet: riconsegna dello stesso comando con sola formattazione JSON diversa. Il confronto remoto verifica che i due contatori tecnici importati non aumentino al replay e che non vengano creati artifact/JD nuovi.

## File modificati

- `.github/workflows/chatgpt_job_watch_bridge.yml`
- `.github/workflows/collect_jobs.yml`
- `AUDIT.md`
- `CHATGPT_HANDOFF_E_RICORRENZE.md`
- `CHATGPT_WORKER_PROMPT.txt`
- `DAILY.md`
- `JOB_WATCH_BRIDGE.md`
- `OPERATIONS_RETRY_REPORT.md`
- `audit_job_watch.py`
- `certify_job_watch.py`
- `collection_freshness.py`
- `daily_worklist.json`
- `daily_worklist.py`
- `jd_retry.py`
- `job_memory.py`
- `job_memory_jw1.json`
- `job_watch_audit.json`
- `job_watch_bridge.py`
- `job_watch_healthcheck.json`
- `job_watch_summary.txt`
- `sync_analysis_state.py`
- `test_collection_freshness.py`
- `test_jd_retry.py`
- `test_job_watch_bridge.py`
- `validate_job_watch_state.py`
- `.job_watch_bridge/requests/select-20261007T1619Z-live-replayfix10.json`
