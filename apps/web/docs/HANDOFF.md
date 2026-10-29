# Handoff Codex ↔ ChatGPT tramite GitHub

## Punto di partenza

Base audit: main `0f6287a461de3951ba6dc4d2a00235a5fde494fd`, 2026-10-29. Branch fondazioni `codex/web-phase-zero`, PR verso main senza merge automatico. Stato implementato: app locale, schema SQL, health, test, CI e contratti. Stato non implementato: importer, dati operativi nel DB, auth remota, dispatcher comandi, analisi diretta arbitraria, deploy. Leggere l'esito verifiche in `VALIDATION.md` e il prossimo incarico in `../../../PLANS.md`.

## Riprendere in Codex

1. Leggere AGENTS e piano; verificare PR e branch correnti con strumenti GitHub autorizzati. Fetch e confrontare main con lo SHA audit: nuovi cambi alle fonti richiedono aggiornamento dell'audit prima di una sync.
2. Preservare modifiche utente, usare branch dedicato. Leggere AUDIT, ADR, SYNC_CONTRACT e controllare il diff per confermare che non vi siano modifiche produttive involontarie.
3. Da `apps/web`: `npm ci`, `npm run check`, `npm run db:migrate:local`, `npm run worker:check`, `npm run dev:api`. Nessun token richiesto. Il DB è vuoto di dati operativi per scelta.
4. Eseguire solo l'incarico esplicito della fase successiva; aggiornare test, audit se necessario e resoconto con commit verificato. Non invocare scheduler/bridge per «provare» questa base.

## Riprendere in ChatGPT Chat

Aprire il repo e la PR con gli strumenti GitHub autorizzati, leggere `AGENTS.md`, `PLANS.md`, `apps/web/docs/HANDOFF.md`, poi audit/contratto/ADR. Lavorare su branch dedicato, verificare SHA e file reali prima di proporre modifiche. Non affidarsi allo stato di questa conversazione come fonte autorevole; non confondere scaffold e funzionalità attive.

Prompt suggerito:

> Lavora su giacodmr/job-watch-milano dalla PR delle fondazioni web. Leggi AGENTS.md, PLANS.md, apps/web/docs/AUDIT.md e SYNC_CONTRACT.md allo SHA corrente. Implementa soltanto la Fase 1 locale e di sola lettura descritta in PLANS.md. Preserva Python, dati e workflow produttivi. Non usare API LLM, non creare risorse cloud, non deployare, non fare merge. Prima confronta l'audit con main e comunica eventuali divergenze. Consegna test, provenienza dei dati, limiti e una PR.

## Trasferire lavoro semantico esistente

Continuare a usare `JOB_WATCH_BRIDGE.md` e `CHATGPT_WORKER_PROMPT.txt` per il worker corrente. Packet JD soltanto tramite artifact autorizzato, mai incollato in codice/PR/log o nel D1. Ricontrollare request ID, run e attempt, packet SHA, snapshot e ricevute; non fabbricare un giudizio in assenza di JD richiesta dalle regole. READY è disponibilità del packet, PARTIAL non significa completa applicazione, e il push/ACK deve essere verificato.

Questa PR non modifica né avvia il bridge. `request_semantic_review` è soltanto un contratto futuro; expected_job_key non è selezione arbitraria. Se l'incarico successivo richiede capacità produttive nuove, preparare una proposta esplicita e una PR distinta mantenendo i guardrail.

## Resoconto da lasciare a ogni passaggio

Repo, branch, SHA base e head verificati, URL PR, scope eseguito, file cambiati, comandi test con risultato, stato migrazioni, assenza/presenza di dati importati, eventuali operazioni remote autorizzate ed eseguite, rischi e prossimo incarico concreto. Nessun segreto o contenuto sensibile. Non dichiarare test non eseguiti, CI verde senza verificarla o azioni complete prima dell'ACK.
