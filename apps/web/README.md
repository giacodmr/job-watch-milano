# Job Watch Web — Fase 0

Fondamenta locali della futura applicazione privata. Il Job Watch Python resta indipendente. Questa fase non importa dati GitHub, non esegue analisi e non scrive comandi operativi. Nessuna risorsa Cloudflare è stata creata.

## Avvio riproducibile

Requisiti: Node.js 24 LTS e npm. Nessun account cloud o segreto richiesto. Dalla root:

```sh
cd apps/web
npm ci
npm run check
npm run db:migrate:local
npm run dev:api
```

Aprire `http://127.0.0.1:8787`: il Worker serve la build React e `/api/health` dallo stesso host. `npm run check` include la build; dopo modifiche frontend ricostruirla. La health verifica soltanto versione schema locale, non certificazione o freschezza del Job Watch.

Per HMR, in un secondo terminale da `apps/web` eseguire `npm run dev` e aprire `http://127.0.0.1:5173`. Vite inoltra `/api` al Worker locale. Fermare i processi con Ctrl-C. Per ripristinare un DB di sviluppo vuoto, fermare il Worker, rimuovere **solo** `apps/web/.wrangler/state/` e riapplicare le migrazioni.

```sh
npm run db:list:local
npm run db:migrate:local  # seconda esecuzione: nessuna migrazione pendente
npm run worker:check      # bundle dry-run, nessun upload
curl -i http://127.0.0.1:8787/api/health
```

`.env.example` documenta le variabili senza segreti: non occorre copiarlo. `APP_ENV=local` è in Wrangler. Eventuali override server locali andranno in `.dev.vars` ignorato da Git. Non usare `VITE_` per segreti. Il database UUID nullo è un identificatore locale intenzionale; `remote: false`, assenza di route e script di deploy, `workers_dev: false` e blocco HTTP fuori da loopback impediscono di presentare questa base come applicazione remota autenticata. Il controllo hostname è esclusivamente un confine di sviluppo: Cloudflare Access con JWT è un requisito bloccante prima di qualsiasi deploy.

## Struttura

```text
apps/web/
  src/                     React e CSS; nessun modulo server
  worker/                  API health e blocco runtime remoto
  shared/contracts.ts      schemi Zod per health, manifest e comandi futuri
  migrations/              schema SQL numerato D1
  tests/                   integrazione Worker/D1 e contratti sintetici
  docs/
    AUDIT.md               autorità e dipendenze osservate su main
    ARCHITECTURE.md        responsabilità e diagramma
    SYNC_CONTRACT.md       protocollo futuro, invarianti e conflitti
    HANDOFF.md             passaggio Codex/ChatGPT tramite GitHub
    VALIDATION.md          risultati effettivi e limiti
    adr/                   scelte e limiti Free verificati
```

Alla root: `AGENTS.md`, `PLANS.md`; CI nuova in `.github/workflows/web-foundation.yml`. Nessun npm workspace alla root, nessuna dipendenza Node nel processo Python.

## Contratto HTTP attivo

- `GET /api/health`: 200 con schema pronto; 503 se D1 non disponibile o schema da migrare. Parametri query non previsti: 400; altri metodi: 405. Risposta `no-store`, UTC, `productionAccess: false`, `synchronization: disabled`.
- `POST /api/commands`: 501 `commands_disabled`. Non legge né persiste il body; non restituisce un'accettazione fittizia. Altri metodi: 405.
- Altri `/api/*`: 404 JSON. Richiesta fuori da loopback o ambiente diverso da local: 403, inclusi asset.

## Test e CI

`npm test` crea Worker e D1 effimeri tramite Miniflare/workerd, applica gli stessi SQL tracciati e verifica vincoli, health, errori, confini e contratti. Tutte le fixture sono sintetiche, senza accessi GitHub/cloud. `npm run build` include TypeScript strict UI/API/test. `npm run worker:check` valida bundle e binding con deploy dry-run. Lockfile committato; Miniflare è allineato alla versione richiesta da Wrangler, incluso il suffisso prerelease del runtime corrente.

La CI dedicata è read-only, limitata ai path della nuova app e della propria configurazione, senza secret, deploy, schedule, artifact o cache aggiuntivi. Il workflow Python preesistente su tutte le PR può comunque avviarsi: non è stato modificato.

## Documentazione

Iniziare da [audit](docs/AUDIT.md), [architettura](docs/ARCHITECTURE.md), [ADR](docs/adr/0001-stack-costs-security.md), [contratto sync](docs/SYNC_CONTRACT.md) e [handoff](docs/HANDOFF.md). Piano e prossimo incarico in `../../PLANS.md`.
