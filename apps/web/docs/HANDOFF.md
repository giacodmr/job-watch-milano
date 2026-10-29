# Handoff Codex ↔ ChatGPT tramite GitHub

## Stato consegnato dopo Fase 1

Repository `giacodmr/job-watch-milano`, branch `codex/web-phase-one`. Base implementazione e import `84593e95d60dd4634a3d7ff5f493c13f7fdb872d`; main ricontrollato `3661d7afc324af1fc51d5a6d7effa4fccf82c0b9`, solo delta operativi di raccolta. Le fondazioni/skill della PR #23 sono già state integrate dall'utente. Questa fase non fa merge su main.

Implementato: exporter da archivio Git isolato, validazione manifest e byte hash, bundle sanitizzato, import D1 locale riprendibile con pubblicazione atomica CAS/audit, query senza dipendenza HTTP e Explorer paginato con provenienza/history. Schema 4; migrazioni precedenti preservate. Import locale reale di 5.454 identità a SHA esplicito; nessun dato operativo è nella build o nei file della PR.

Non implementato: auth remota/JWT, endpoint ingestion, MCP server, dispatcher comandi, selezione arbitraria di analisi, cron/polling o deploy. Nessuna API LLM o risorsa cloud. Leggere README e PHASE1_VALIDATION per comandi, metriche, screenshot e limiti.

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
