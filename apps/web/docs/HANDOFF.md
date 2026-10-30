# Stato corrente — Model C / PR 2

Baseline main `5abbdf67cea4d4004b0cdfa066ef292b7e499682`, squash della #31 verificata MERGED. Schemi CATALOG/PERSONAL separati e inattivi; test e backup/restore soltanto sintetici/effimeri. V1 schema 5 e binding/reader/importer invariati. [Garanzie, limiti PR 3 e rollback](MODEL_C_SCHEMA.md), [misure di schema](MODEL_C_SCHEMA_METRICS.json). Nessun bootstrap dati reale o costo sync Model C misurato. Seguono gli handoff storici.

# Stato corrente — Modello C / PR 1

#25 verificata MERGED tramite squash `004782c1d5b53c9c6abb0399c8368f28831104c7`, baseline del branch `codex/model-c-selection-contracts`. Contratti e prove in [MODEL_C_SELECTION_CONTRACT.md](MODEL_C_SELECTION_CONTRACT.md). Schema 5, protocollo v1, importer, reader e UI invariati; nessun D1 persistente/cloud toccato. Il prossimo passo consentito, dopo CI verde, è lo schema locale separato della PR 2. Seguono i resoconti storici, i cui SHA non sono la baseline attuale.

# Stato corrente — consolidamento tecnico #25

Main 0b2984a recepito nel branch `codex/web-phase-one`; baseline PR b84d778. Correzioni backend per cursori Unicode, ricerca lunga D1 e nome azienda per snapshot; schema 5 additivo, 46 test Vitest e strict/build/dry-run verificati. Misure reali e procedura di ripresa in [PHASE1_CONSOLIDATION.md](PHASE1_CONSOLIDATION.md), numeri aggregati in [PHASE1_COSTS.json](PHASE1_COSTS.json). Nessuna UI V7 o funzionalità anticipata.

Prima di integrare: verificare head/CI della #25, leggere i gate residui e la sequenza #25/#30. La #30 rimane una Draft da cui estrarre selettivamente il read model Dashboard e comportamenti dati, non l'intero backend o il design #29. Nessun merge/deploy/cloud eseguito da questo consolidamento.

Segue l'handoff storico della Fase 1, con misure e schema dell'epoca.

# Handoff Codex ↔ ChatGPT tramite GitHub

## Stato consegnato dopo Fase 1

Repository `giacodmr/job-watch-milano`, branch `codex/web-phase-one`. Base implementazione e import `84593e95d60dd4634a3d7ff5f493c13f7fdb872d`; main ricontrollato `3661d7afc324af1fc51d5a6d7effa4fccf82c0b9`, solo delta operativi di raccolta. Le fondazioni/skill della PR #23 sono già state integrate dall'utente. Questa fase non fa merge su main.

Implementato: exporter da archivio Git isolato, validazione manifest e byte hash, bundle sanitizzato, import D1 locale riprendibile con pubblicazione atomica CAS/audit, query senza dipendenza HTTP e Explorer paginato con provenienza/history. Schema 4; migrazioni precedenti preservate. Import locale reale di 5.454 identità a SHA esplicito; nessun dato operativo è nella build o nei file della PR.

Non implementato: auth remota/JWT, endpoint ingestion, MCP server, dispatcher comandi, selezione arbitraria di analisi, cron/polling o deploy. Nessuna API LLM o risorsa cloud. Leggere README e PHASE1_VALIDATION per comandi, metriche, screenshot e limiti.

PR di consegna: https://github.com/giacodmr/job-watch-milano/pull/25. Commit implementazione verificato su GitHub: `016594232473c459cc9a7bcb9a8cb6abb6a14908` (albero identico al commit locale). Eventuali aggiornamenti documentali successivi non cambiano lo snapshot dati importato.

## Riprendere il lavoro

1. Leggere AGENTS, PLANS, AUDIT, SYNC_CONTRACT, ARCHITECTURE, questo handoff e le tre skill frontend per task UI. Usare il repository, non la sola conversazione.
2. Verificare branch/PR, preservare modifiche locali. Fare fetch e confrontare main con 3661d7a; se cambiano codec, identità, proiezioni o schema operativo, aggiornare audit/test prima di importare il nuovo SHA.
3. Da apps/web: npm ci (server fermo), npm run check, doppia db:migrate:local, worker:check dry-run. Avvio/import soltanto secondo README, con commit completo verificato. DB già presente: non cancellarlo per un normale aggiornamento.
4. Per Fase 2 chiedere un incarico esplicito: sicurezza Access/JWT/ruoli e budget sono gate. Il bootstrap misurato supera 100.000 scritture/giorno Free e l'override 500.000 è soltanto locale; servono contabilità aggregata, versioni invariate/retention e misure Worker reali prima di sync remota continuativa.

Servizi futuri MCP: chiamare getSnapshot/listJobs/getJob in worker/data/queries.ts con DTO condivisi. Non duplicare la policy Python nel frontend o nel trasporto MCP. Import Node bulk e letture Worker hanno budget/runtime distinti.

Verifiche: 39 test Vitest (incluso wrapper di 10 test exporter Python), strict/build, migrazioni locali, dry-run e 215 unittest produttivi in copia isolata a 3661d7a. CI PR da verificare separatamente sullo SHA head corrente. Nessun comando produttivo, merge o deploy eseguito.

## Trasferire lavoro semantico esistente

Continuare a usare `JOB_WATCH_BRIDGE.md` e `CHATGPT_WORKER_PROMPT.txt` per il worker corrente. Packet JD soltanto tramite artifact autorizzato, mai incollato in codice/PR/log o nel D1. Ricontrollare request ID, run e attempt, packet SHA, snapshot e ricevute; non fabbricare un giudizio in assenza di JD richiesta dalle regole. READY è disponibilità del packet, PARTIAL non significa completa applicazione, e il push/ACK deve essere verificato.

Questa PR non modifica né avvia il bridge. `request_semantic_review` è soltanto un contratto futuro; expected_job_key non è selezione arbitraria. Se l'incarico successivo richiede capacità produttive nuove, preparare una proposta esplicita e una PR distinta mantenendo i guardrail.

## Resoconto da lasciare a ogni passaggio

Repo, branch, SHA base e head verificati, URL PR, scope eseguito, file cambiati, comandi test con risultato, stato migrazioni, assenza/presenza di dati importati, eventuali operazioni remote autorizzate ed eseguite, rischi e prossimo incarico concreto. Nessun segreto o contenuto sensibile. Non dichiarare test non eseguiti, CI verde senza verificarla o azioni complete prima dell'ACK.

## Model C PR 3 — inactive incremental importer

Base `254c22965ce83da17d0d8565796a3b757fbc3861`, branch `codex/model-c-incremental-importer`. Node-only trusted Git replay/proof adapter and incremental importer, single atomic staging/publication batch with CAS, permanent ledger, minimal PERSONAL append/reconciliation, conservative shared daily reservations including cleanup and failure/retry costs. Only additive separate Model C migrations; active V1, UI, engine and workflows unchanged.

Implementation, recovery semantics, exact measurement scope and remaining capacity/cloud gates: [MODEL_C_IMPORTER.md](MODEL_C_IMPORTER.md). Reproducible synthetic-only harness: `node tools/model-c-import-lab.mjs` from `apps/web`; no database/input arguments accepted. Do not infer production readiness or authorize cutover from local test results. Final PR records the reviewed head and actual CI outcome.


### PR #33 independent-review correction

Reviewed head `471f768422659ae4149a63acafc4294de421d668`: retained V1/PERSONAL decision presence now reaches the proof-bound selector before catalog planning, preserving UNRESOLVED_PERSONAL on first import and replay. Multi-owner PERSONAL is explicitly unsupported and rejected before writes. Schemas/V1/limits remain unchanged. The synthetic baseline preflight (5,454 identities, 5,474 mappings, 151 current vacancies) demonstrates a 22,025-statement plan against the 8,000-statement limit, rejected with zero importer writes. **Bootstrap capacity remains blocked**; the minimal atomic SQL compaction / potential pending-stage follow-up is documented in MODEL_C_IMPORTER.md. Do not treat small-fixture CI success as readiness for the real baseline. Final-head CI and updated validation results are in the same PR #33.


## Model C PR #34 — compact SQL, residual write admission blocker

Base main `1133c6aed1f94de6fec38f541b9869dac4543367` (#33 squash), branch `codex/model-c-bootstrap-capacity`. Multi-row typed staging and set-based permanent/current promotion retain one atomic CAS batch, all counts/FKs/proofs and the 8,000 / 8 MiB limits. No schema/V1/Python/UI/workflow/binding changes. The exact 5,454 / 5,474 / 151 baseline drops from 22,025 statements / 6,986,391 bytes to 739 / 2,704,855, but admission requires a conservative 94,173 writes and refuses the 60,000 ceiling with zero writes/reservation. A 3,000 / 3,020 / 151 fixture really publishes (42,788 actual / 52,455 reserved), replays at zero and passes a late-error full rollback plus delta. Full baseline remains NO-GO. See [MODEL_C_CAPACITY.md](MODEL_C_CAPACITY.md) for phase costs, runtime probes, memory scope and the minimum separate write-representation review. Do not reactivate Model C or claim that SQL compaction has reduced written rows.
