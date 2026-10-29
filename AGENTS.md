# Job Watch: istruzioni permanenti

## Confini e fonti

- Il sistema operativo Python/GitHub Actions resta indipendente da `apps/web/`.
- Per la web app leggere prima `apps/web/README.md`, `apps/web/docs/AUDIT.md`, `apps/web/docs/SYNC_CONTRACT.md` e `PLANS.md`.
- Autorità: regole in `job_watch_rules.json`; aziende attive in `companies_job_watch_v2.json`; routing in `job_watch_batches.json`; candidati in `company_candidates.json`; accesso ATS in `ats_mapping_jw*.json`; inventari in `current_jobs_jw*.json`; decisioni persistenti in `job_memory_jw*.json`; identità chiuse anche in `archive/*.jsonl`. Le viste Daily/health non sostituiscono queste fonti.
- Non modificare collector, filtri, business rule, configurazioni, dati operativi, sentinel, richieste bridge o workflow preesistenti per sviluppare la web app. Un incarico che li coinvolga richiede un ambito esplicito e una PR distinta.
- Le scelte utente hanno precedenza secondo le regole Python attuali. Non trasformare un rifiuto individuale in filtro generale. Non ricomputare fingerprint o risolvere alias con euristiche nuove nel frontend.
- Il bridge v2 seleziona dalla coda; `expected_job_key` non è un selettore arbitrario.

## Sicurezza e costi

- Solo piani gratuiti. Nessuna API LLM, nessun deploy, provisioning o accesso D1 remoto nel lavoro di Fase 0.
- Non eseguire `wrangler deploy` (salvo `--dry-run`), `wrangler d1 create`, `--remote`, dispatch di workflow produttivi o scritture su `main` senza incarico esplicito.
- Nessun segreto nel browser, nei file tracciati, nelle fixture o nei log. Nessuna JD integrale in D1, Git o log. Usare allowlist di campi e riepiloghi limitati, mai dump di payload.
- Il runtime attuale accetta solo loopback con `APP_ENV=local`. Non rimuovere il blocco remoto prima di introdurre e testare Cloudflare Access con verifica JWT di firma, issuer, audience, scadenza e autorizzazioni distinte per utente e servizio.
- Non dichiarare completato un comando prima della conferma GitHub e della successiva proiezione D1 verificata. Non presentare dati di esempio come reali.

## Metodo e verifica

- Branch dedicati `codex/`, PR verso `main`, nessun merge automatico. Preservare modifiche locali preesistenti.
- TypeScript strict; API in `worker/`, UI in `src/`, contratti puri in `shared/`. Il browser non importa moduli server.
- Migrazioni numerate additive; non riscrivere migrazioni già applicate. Conservare i marcatori `-- statement-breakpoint` tra statement SQL completi per i test D1.
- Da `apps/web`: `npm ci`, `npm run check`, `npm run db:migrate:local` (anche una seconda volta), `npm run worker:check`. Nessuna credenziale necessaria.
- I test nuovi usano esclusivamente fixture sintetiche in memoria. Non avviare `job_watch.py sync`, collect, project o validatori che scrivono sul checkout operativo. Le verifiche Python che possono scrivere vanno eseguite in una copia temporanea isolata.
- Aggiornare documentazione e handoff con SHA analizzato, comandi verificati, risultati e limiti reali. Non caricare archivi o inventari produttivi nella build frontend.
