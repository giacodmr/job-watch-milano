# Audit delle fondamenta esistenti

Analisi read-only del codice effettivo `main`, SHA `0f6287a461de3951ba6dc4d2a00235a5fde494fd`, acquisito il 2026-10-29. La directory locale iniziale era su un altro branch con modifiche utente; questo lavoro usa un worktree dedicato dal main remoto. Nessun dato operativo è stato aggiornato dall'audit.

## Addendum: avanzamento main durante il lavoro

Prima della consegna è stato confrontato anche main `6725fefa45e5bab0494ceb05b9edb2fe999a1e1f`, poi integrato nel solo branch web. I commit upstream aggiungono `worldline_collector.py`, il dispatch Worldline in `collector.choose`, nove test dedicati, strumenti/documentazione e `.github/workflows/ats_worldline_probe.yml`, oltre a checkpoint operativi. Il collector nuovo recupera metadati da fonte ufficiale e dettagli verificati, mantenendo intenzionalmente `coverage=PARTIAL` per conteggi/ordine non riconciliati: conferma il requisito di non dedurre chiusure dalle assenze in una fonte parziale. Non cambia le autorità di aziende, regole, memoria, alias, worker o bridge descritte sotto.

I conteggi citati nell'audit principale sono quelli dello SHA iniziale, non dati aggiornati dalla web app. I cambiamenti operativi upstream sono stati recepiti tramite merge nel branch dedicato, senza modificarli; il diff della PR rispetto al main aggiornato contiene soltanto i file di Fase 0. Anche la suite Python aggiornata è verificata in copia temporanea (esito in VALIDATION.md).

## Autorità per dominio

- **Policy globale:** `job_watch_rules.json`, sezioni `configuration_authority`, `user_decision_policy`, `analysis_policy`, `daily_worklist_policy`, geografie e certificazione. La policy effettiva è implementata anche in `sync_analysis_state.py`, `harden_job_watch_state.py`, `location_policy.py`, `rejection_reasons.py`: non basta importare un JSON e reinterpretarlo in TypeScript.
- **Aziende attive:** `companies_job_watch_v2.json:companies` (207 righe nello SHA analizzato). Contiene `id`, nome, tier, priorità, career URL, preferenze e `allowed_locations`. `job_watch_batches.json:batches` assegna JW1–JW4; `coverage_aliases` e `company_metadata` sono contesto di routing, non autorità alternativa per preferenze aziendali.
- **Staging aziende:** `company_candidates.json:records` (77 nello SHA), con storia di promozioni e ricerche. Un candidato non equivale a un'azienda attiva. `authority` esplicita il confine.
- **Accesso tecnico alle fonti:** `ats_mapping_jw1.json` … `jw4`, righe companies con ATS, URL/API, verifica e limitazioni. Dati descrittivi duplicati non sovrascrivono aziende o routing.
- **Inventario operativo e copertura:** `collector.py` e collector specializzati chiamati dal suo dispatch; output `current_jobs_jw*.json`. `amazon_target_check.py`/`amazon_target_check.json` forniscono evidenza prioritaria Amazon. `sync_analysis_state.sync_batch` chiama manutenzione e riconcilia il prioritario nell'inventario; `project_batch` dichiara esplicitamente di non leggere l'overlay Amazon durante la proiezione ordinaria.
- **Decisioni durevoli:** `job_memory_jw*.json:records[job_key]` con sezioni indipendenti `identity`, `semantic`, `user`, `surfacing`, `jd_fetch`, più `applied_update_ids`. `job_memory.py` è il codec e validatore; `semantic_evidence` non è JD, ma pool di testi di evidenza deduplicati.
- **Identità storiche chiuse:** anche `archive/vacancies_YYYY_MM.jsonl`, append compatto di metadati identità quando lo stato passa ufficialmente a CLOSED e viene rimosso dal current. Non contiene un log completo di tutte le revisioni semantiche. Le memorie trattengono decisioni, ma tipicamente l'ultima per sezione: non inventare uno storico precedente al primo import.
- **Proiezione effettiva e coda:** `sync_analysis_state.project_batch`, `harden_job_watch_state.queue_row/queue_sort_key` e `daily_worklist.action_reason/build_worklist`. La proiezione unisce current e memoria con alias; per identità mancanti include solo alcune scelte attive, non tutto l'archivio.
- **Daily:** `daily_worklist.json` è un read model limitato. Allo SHA contiene 56 record, ma il numero non misura l'inventario. I nuovi candidati sono limitati dalla policy; backlog, retry differiti e identità chiuse non hanno rappresentazione esaustiva. Non usarlo come tabella jobs o registro storico.
- **Stato processi:** `pipeline_execution.json` raccoglie stage/errori; `job_watch_run_state.json` è una proiezione deterministica dello snapshot (versione 2.0), non un'autorità di completamento; `daily_activity.json` conserva evidenze di ricerche legate allo snapshot. `certify_job_watch.py` genera `job_watch_healthcheck.json` e summary con collection, `DAILY_COMPLETE`, `FULL_SEMANTIC_COMPLETE`, debito tecnico e storico distinti. Il run_id di pipeline è hash di sorgenti, non GitHub Actions run ID.
- **Trasporto semantico:** `job_watch_bridge.py`, `semantic_worker.py`, `job_watch_bridge_runner.py`, `.job_watch_bridge/requests` e `receipts`, `JOB_WATCH_BRIDGE.md`, `CHATGPT_WORKER_PROMPT.txt`, `CHATGPT_HANDOFF_E_RICORRENZE.md`. I giudizi vengono da ChatGPT esterno, mai da una API LLM della web app.

## Percorso di esecuzione e dipendenze

`job_watch.py` espone collect/amazon/sync/project e pubblicazione con percorsi consentiti. Collect esegue raccolta e riconciliazione per batch, prioritario Amazon, semantic sync/manutenzione, worklist, validazione e certificazione. Sync può consumare `daily_updates.json`. Project aggiorna viste senza consumare comandi o fare manutenzione: è comunque una scrittura locale e non è stato eseguito sul checkout operativo.

`collector.metadata_fingerprint` usa titolo, location, department, team, employment type, data assoluta e URL; ignora descrizioni e date relative. Produce SHA-256 troncato a 16 caratteri. L'evidenza prioritaria Amazon può usare un fingerprint diverso che include qualifiche. Non normalizzare tutto a SHA-256 di 64 caratteri e non confondere fingerprint con checksum di file o packet.

La copertura è `VERIFIED/PARTIAL/FAILED/NOT_CHECKED`. Il collector trattiene le righe precedenti e marca l'assenza CLOSED soltanto con enumerazione verificata (oppure CLOSED già noto), altrimenti UNKNOWN. Non chiudere tutti i job di un'azienda perché un fetch è fallito. Gli stati di vacancy NEW/STILL_OPEN/UPDATED sono aperti; CLOSED e UNKNOWN non autorizzano una normale review.

## Idempotenza, snapshot e atomicità

- `pipeline_state.source_identity/snapshot`: hash byte SHA-256 dei current JW1–4, Amazon prioritario, rules, batches, aziende; run_id derivato. **Le memorie, ATS mapping e candidati non sono tutti inclusi nel medesimo token globale.** Per una replica web serve manifest completo a commit fissato oltre al token Python, senza modificarlo.
- `semantic_worker.batch_snapshot`: hash di current e memoria del batch, rules, aziende e batches. La SELECT controlla che il token non cambi durante il fetch. APPLY rifiuta batch/snapshot errati; fingerprint e idoneità sono nuovamente verificati. Le due nozioni di snapshot non sono intercambiabili.
- `pipeline_state.writer_lock`: flock POSIX con recupero journal; `atomic_json`: file temporaneo, fsync e os.replace; `transaction`: journal durevole, eventuali append con offset e recovery, poi replace/rimozioni. È un protocollo per writer locali serializzati, **non una transazione distribuita di lettura multi-file**. La replica deve leggere tutti i blob dallo stesso commit Git confermato, non file durante una raccolta.
- `applied_update_ids` deduplica patch. Daily e worker usano serializzazioni/hash Python propri; non ricalcolarli con JSON.stringify. Bridge v2 vincola request ID al digest dell'intera richiesta; stesso ID con contenuto diverso fallisce. La receipt è durevole e replay immutabile.
- SELECT predice il nuovo hash della memoria dopo aggiornamento `jd_fetch`; dopo upload l'artifact viene fissato per ID, run e attempt e memoria+receipt sono scritti insieme. APPLY verifica parent receipt, artifact non scaduto, hash dei byte, run/path/evento/branch, membri del packet e fingerprint. Può applicare un sottoinsieme e restituire PARTIAL: il successo del job Actions non significa che ogni review sia stata applicata.
- `job_watch_bridge_runner.acknowledge` fetch del remoto, verifica commit antenato e uguaglianza receipt. Accetta anche push riuscito con risposta persa. La futura web app deve attendere questo tipo di evidenza e sync successiva.

## Persistenza e precedenza utente

`job_memory.resolve_identities` riconcilia alias di URL in modo conservativo, vincolato alla stessa azienda e a URL corrente non ambiguo; Amazon normalizza il requisition numerico pubblico da `/jobs/<id>`. Conserva evidenze vecchie, sceglie per timestamp e preferisce review dello stesso fingerprint. La UI non deve inventare equivalenze da titolo/location né perdere scelte in caso di cambio source ID.

APPLIED e NOT_INTERESTED sopprimono revisione/report ordinari, anche attraverso fingerprint e alias riconciliati. INTERESTED e TO_REVIEW rimangono azionabili. Daily applica scelte soltanto con fingerprint corrente e timestamp non regressivo; NOT_INTERESTED richiede motivo concreto e categoria coerente con `rejection_reasons.py`. Valori storici privi di categoria vanno conservati, non riscritti.

La semantica richiede validazione esistente: fingerprint, metodo, evidenze e campi obbligatori; ruoli prioritari/senior/protetti richiedono full JD. Una review storica abbreviata (`historical_evidence`) non autorizza un job riaperto. I filtri hard-rule sono un'altra provenienza ancora: non registrarli come rifiuti utente o review ChatGPT. Non reimplementare criteri di fit o soglie in questa fase.

## Protezione JD e retry

`job_memory.assert_no_jd` proibisce ricorsivamente campi come text/description/body/jd e qualifiche integrali; il codec verifica pool e hash `$e`. Il bridge evita stdout/stderr dei processi worker in caso di errore JSON. Le JD vengono recuperate al bisogno in packet temporanei `/tmp` e artifact Actions con retention 1 giorno (anche diagnostica failure può contenerli); non sono una sorgente da importare o un contenuto da loggare.

Questi divieti basati sui nomi non garantiscono da soli che un testo libero non contenga una JD o dato sensibile. La replica userà allowlist e riepiloghi limitati; nessun import di payload JSON arbitrari. Non espone dettagli personali del profilo di ricerca, evidenze sensibili o testo grezzo di errori.

`jd_retry.py`: iniziale + 3 retry (4 fallimenti totali), riprova dal prossimo giorno Europe/Rome con fingerprint e URL invariati, poi JD_UNAVAILABLE. Il tempo da solo non riapre la review; nuova evidenza sì. `needs_analysis` resta true anche se non processabile. Non trasformare un errore tecnico in scarto semantico o completamento.

## Limiti strutturali da risolvere nelle fasi successive

1. `fetch_candidates` prende `project_batch(...).queue`, esclude alcune chiavi e tronca per limite. Il bridge SELECT ha limite 1–20 e `fetch=true`; `expected_job_key/expected_fingerprint` controllano solo il primo record. **Non seleziona una vacancy arbitraria.** Non aggirare la coda con liste di esclusione costruite dal browser. Serve estensione esplicita, testata e autorizzata del worker.
2. Bridge solo select/apply semantico. Non supporta direttamente comandi aziende, ATS o scelte utente. Daily updates è un altro percorso con possibile accettazione parziale (`rejected_daily_updates.json`). Un adapter futuro deve verificare ciascun esito; nessun endpoint mutativo viene attivato ora.
3. Timestamp di generazione dei file non garantiscono un insieme coerente. Import a commit singolo + manifest completo + snapshot Python distinti. Alias e pool compressi richiedono codec Python esistente, o porting con test di equivalenza in un incarico distinto.
4. I registri conservano l'ultima evidenza, non tutti gli eventi passati. D1 potrà conservare ogni versione osservata dal primo import; la ricostruzione antecedente da Git history richiede un piano separato e budget misurato.
5. La CI Python preesistente si attiva su tutte le PR. `job_watch_bridge_ci.py` normalmente richiede full validation per modifiche applicative: aggiungere la CI web non elimina questo costo. Nessun workflow esistente viene modificato qui.

## Workflow osservati (tutti lasciati invariati)

- `collect_jobs.yml`: schedule 23:07, 23:17, 23:32, 23:47 Europe/Rome, guard freshness, manual dispatch/sentinel; nessuna garanzia di puntualità del scheduler.
- `amazon_priority.yml`: dispatch e sentinel dedicato. `sync_semantic_state.yml`: dispatch e push main su input produttivi/Python.
- `chatgpt_job_watch_bridge.yml`: push main di un solo request JSON per push, writer serializzato, artifact temporanei e receipt; nessun workflow_dispatch generico.
- I writer condividono concurrency `job-watch-state-writer`, cancel false, coda max. Un adapter nuovo dovrà rispettarla senza cambiare gli scheduler.
- `validate.yml`: validazione PR e push main selezionati. `ats_coverage_recovery.yml`, `ats_probe_batch2/3/4.yml`, `ats_unicredit_probe.yml`: strumenti operativi diagnostici, non un'integrazione per la web app.

La Fase 0 cambia soltanto nuovi file `apps/web/**`, `AGENTS.md`, `PLANS.md` e il nuovo workflow web. Le criticità sono documentate, non corrette modificando produzione.

## Addendum Fase 1 — confronto con main vivo

Inizio implementazione dal merge delle fondazioni/skill, `84593e95d60dd4634a3d7ff5f493c13f7fdb872d`. Il checkout era pulito; branch distinto `codex/web-phase-one`. PR #23 risulta già integrata dall'utente. Non è stata ricostruita la Fase 0.

Confronto dal primo audit `0f6287a461de3951ba6dc4d2a00235a5fde494fd` e dal riallineamento `6725fefa45e5bab0494ceb05b9edb2fe999a1e1f`:

- Worldline e relativa copertura PARTIAL erano già nell'addendum della Fase 0.
- Tra 6725fef e 84593e9 sono entrati `nexi_collector.py`, modifica del ramo Oracle in `collector.py`, test/probe Nexi e workflow diagnostico. L'enumerazione Nexi resta PARTIAL in presenza di risultati ambigui. Questa copertura non autorizza chiusure per assenza.
- I moduli `pipeline_state.py`, `job_memory.py`, `sync_analysis_state.py`, `daily_worklist.py`, `location_policy.py`, retry e bridge non sono cambiati in questo intervallo. L'export usa comunque il codice del commit importato, senza una copia divergente delle regole.
- Nuovo fetch prima della consegna: `main=3661d7afc324af1fc51d5a6d7effa4fccf82c0b9`, commit «Update Job Watch collect state». Rispetto a 84593e9 cambia 15 file operativi (inventari, memorie, health/run, pipeline e viste); nessun Python, workflow, regola o contratto. Lo snapshot locale rimane intenzionalmente fissato a 84593e9: l'app mostra SHA e date di quel commit, non dichiara di seguire main in tempo reale.

Verifica regressione su 3661d7a: 215 unittest Python invariati, OK, eseguiti in archivio Git temporaneo con requests 2.32.5 in un venv temporaneo. Nessuna scrittura nel checkout operativo, nessuna raccolta/sync produttiva o dispatch. I nuovi test exporter usano soltanto fixture sintetiche e moduli Python copiati come codice.

La Fase 1 replica solo metadati strutturati delle identità/review/scelte; anche le motivazioni libere sono escluse. Health/Daily concorrono alla proiezione e alla provenienza, senza sostituire inventari, memorie o archivio. Dettagli e misure in PHASE1_VALIDATION.

## Riallineamento integrazione UI

Main `b3540152d55b455dd485b167978e92a914a85fc7` confrontato con `3661d7a`: nuovi collector Fineco/PayPal e aggiornamenti operativi upstream; nessun cambio a codec memoria, identità/alias, proiezione, worker, bridge o autorità delle configurazioni. Ricevuti nel branch senza modificarli. Import locale reale al nuovo main confermato alla revisione 2; dettagli e limiti in [JET_INTEGRATION.md](JET_INTEGRATION.md). Nessuna nuova discovery generale o modifica produttiva.

Prima della consegna main è avanzato a `0b2984a669c4d0dae0b3b666945855c6cda86627`: merge safety PR #28 effettuato dall’utente. Delta di soli strumenti/test/documentazione/CI e ignore, senza cambi alle fonti operative importate. Integrato nel branch; nessun replay ridondante a nuovo SHA o modifica ai relativi strumenti.
