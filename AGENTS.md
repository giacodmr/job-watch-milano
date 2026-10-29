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

## Frontend design: skill obbligatorie e verifica visiva

- Nei task che progettano, implementano o modificano interfacce, leggere e applicare entrambe le skill locali prima di intervenire: [frontend-design](.agents/skills/frontend-design/SKILL.md) e [job-watch-ui-direction](.agents/skills/job-watch-ui-direction/SKILL.md). La direzione Job Watch specifica il brief del progetto; le indicazioni generiche delle skill non sostituiscono i requisiti dell'utente, i contratti reali o le regole di sicurezza e costo.
- Revisionare ogni implementazione UI, comprese le modifiche a UI esistenti, con [web-design-guidelines](.agents/skills/web-design-guidelines/SKILL.md). Seguire la skill per recuperare le linee guida ufficiali aggiornate e applicarle ai file UI interessati; correggere i difetti riscontrati e ripetere la verifica prima di dichiarare il task UI completato.
- Se è disponibile un browser o una preview utilizzabile, effettuare una verifica visiva effettiva sia desktop sia mobile: aprire l'interfaccia renderizzata, controllare layout, leggibilità, tabelle/filtri/navigazione, focus e stati empty/loading/error pertinenti. La sola compilazione o lettura del codice non sostituisce questa verifica.
- Documentare viewport/dimensioni, schermate o altre evidenze osservate e risultati dei controlli; correggere i difetti visivi riscontrati e ricontrollare le viste coinvolte prima del completamento. Se browser/preview o linee guida non sono disponibili, indicare precisamente la verifica mancante e il limite, senza dichiararla eseguita o superata.
- Non applicare queste skill ai task esclusivamente backend. Installazione/configurazione delle skill non autorizza redesign, modifiche applicative, nuove funzionalità o l'avvio di una fase successiva.
- Le skill sono versionate in `.agents/skills/` nello scope repository Codex; le due copie upstream vanno mantenute integre. Provenienza, comandi di installazione e verifiche sono documentati in [configurazione frontend design](docs/frontend-design-skills.md).
