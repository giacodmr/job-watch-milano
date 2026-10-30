# Job Watch Web — Fase 1 locale

Vacancy Explorer di sola lettura su D1 reale locale. GitHub/Python conservano regole, fingerprint, alias, decisioni e autorità operativa. Exporter e importer leggono un commit esplicito senza eseguire collector o comandi. Nessuna risorsa cloud, API LLM o dipendenza applicativa aggiuntiva.

## Avvio riproducibile

Requisiti: Node.js 24 LTS, npm, Git e Python 3.12+ (exporter: sola libreria standard). Da root:

```sh
cd apps/web
npm ci
npm run check
npm run db:migrate:local
npm run db:migrate:local
npm run worker:check
npm run dev:api
```

Aprire `http://127.0.0.1:8787`. Il Worker serve build React e API nello stesso host. Senza import compare «Nessuno snapshot confermato»; nessuna fixture viene caricata nell'app. Dopo modifiche UI ricostruire la build. Per HMR: `npm run dev` in un secondo terminale, porta 5173 con proxy API verso 8787. Fermare il server prima di reinstallare `node_modules`, poi riavviarlo.

## Importare un commit verificato

Prima leggere AGENTS, AUDIT e SYNC_CONTRACT; confrontare il codice operativo dal precedente SHA analizzato. Fare fetch è un'operazione Git esplicita separata dalla sync:

```sh
git fetch origin main
git rev-parse origin/main
```

Passare lo SHA completo verificato, ad esempio il commit importato durante questa fase:

```sh
npm run sync:export -- --commit 84593e95d60dd4634a3d7ff5f493c13f7fdb872d
npm run sync:import
```

Oppure `npm run sync:local -- --commit <SHA-completo>` per export e import insieme. Il commit deve essere antenato di `origin/main` nel repository autorizzato. L'export legge un archivio Git temporaneo: modifiche non committate nel checkout operativo non entrano nell'import. Non avviare direttamente `tools/export_snapshot.py`: il suo stdout è un pipe privato verso la CLI, che calcola gli hash delle review ed elimina le preimmagini prima di qualsiasi persistenza.

Il bundle sanitizzato va in `.local-sync/snapshot.json` (directory 0700, file 0600, ignorato da Git); `--file` sceglie un percorso locale alternativo. Non copiarlo in `public/`, build, PR o log. La CLI stampa soltanto codici e metriche. D1 persiste in `.wrangler/state/v3/`, condiviso con `dev:api`. `remoteBindings:false`, binding locale e `APP_ENV=local` sono verificati; nessuna credenziale necessaria.

Il budget predefinito è 70.000 righe scritte **per invocazione**, con margine di 1.000 prima di ogni chunk. `LOCAL_WRITE_BUDGET_REACHED` lascia staging riprendibile e checkpoint precedente visibile. Il bootstrap reale misurato richiede 113.175 scritture e quindi più di un budget. Una successiva esecuzione riprende i chunk identici. Per il solo sviluppo locale è disponibile:

```sh
npm run sync:import -- --max-writes 500000
```

`npm run sync:measure` misura bootstrap e replay; `--next FILE --same-files FILE` aggiunge un nuovo commit e un commit a fonti identiche, con confronto dei payload/provenance e scritture per statement. Il comando opera su un D1 effimero separato, senza toccare il DB persistente. Per misurare CPU aggregate locali: `/usr/bin/time -l npm run sync:measure`; non equivale al budget CPU Worker remoto.

Questo override non è una configurazione cloud: il bootstrap supera le 100.000 scritture giornaliere D1 Free. Ripetere il comando nello stesso giorno non costituisce gestione di una quota remota. Prima della Fase 2 servono budget aggregato dell'account, pianificazione su più giorni o ottimizzazione delle versioni. Replay dello snapshot già confermato: zero scritture. Un nuovo commit crea nuove versioni, anche quando molti record non cambiano; nessuna retention automatica.

Conservare il DB per storico/replay; non rimuoverlo come procedura ordinaria. Migrazioni numerate 0001–0005: schema 5, nessuna riscrittura di 0001/0002. Un DB locale di sviluppo intermedio creato durante questa fase è stato conservato in `.local-sync/bootstrap-before-alias-membership`, escluso da Git.

## Consolidamento tecnico

La base read-only è stabilizzata senza dipendenze dalle UI #29/#30 o dalla futura V7. Correzioni di paginazione Unicode, ricerca lunga e nomi azienda versionati, misure bootstrap/replay/nuovo commit, gate e sequenza di integrazione in [PHASE1_CONSOLIDATION.md](docs/PHASE1_CONSOLIDATION.md). Schema 5 additivo; nessun cloud o mutation abilitati.

## Servizi e API

- `GET /api/health`: schema 5, `synchronization: local-read-only`, `productionAccess:false`. Non certifica la pipeline Python.
- `GET /api/snapshot`: checkpoint confermato, SHA, date fonti/import, flag Python e numero import incompleti; `snapshot:null` prima del primo import.
- `GET /api/jobs`: filtri `q`, `company`, `batch`, `lifecycle` (`OPEN` aggrega NEW/STILL_OPEN/UPDATED, `ALL` include storico), `assessment`, `decision`; `limit` 1–100, default 25. Paginazione keyset con cursore legato a snapshot e filtri.
- `GET /api/jobs/<job:id>?snapshot=<snapshot:id>`: metadati, alias osservati, ultime 50 review e decisioni confermate, provenienza. Nessuna JD o motivazione libera.
- `POST /api/commands`: sempre 501. Nessun endpoint ingestion o mutation pubblico.

Parametri sconosciuti/duplicati/invalidi: 400; cursore o dettaglio di un checkpoint superato: 409; DB non leggibile: 503 con codice redatto; metodo errato: 405. Tutte le API sono `no-store`. Ambiente diverso da local o host non loopback: 403, inclusi asset. Il controllo host è un confine di sviluppo; JWT Cloudflare Access e autorizzazioni restano bloccanti per qualsiasi deploy.

`worker/data/queries.ts` espone `getSnapshot`, `listJobs`, `getJob` senza Request/Response o UI. Un futuro adapter MCP potrà chiamare gli stessi servizi validati; nessun server MCP è attivo. L'import massivo gira nella CLI Node su D1 locale, non in una richiesta Worker soggetta al budget CPU Free.

## Struttura e verifiche

`src/`: UI; `shared/`: contratti/hash/DTO; `worker/data/`: import e query; `worker/index.ts`: HTTP; `tools/`: adapter Git/Python; `migrations/`: SQL numerato; `tests/`: fixture sintetiche D1/workerd. Il browser non importa moduli server o file operativi.

`npm run check` esegue Vitest, i test Python sintetici dell'exporter, TypeScript strict e build. La CI web esistente esegue anche doppia migrazione locale e dry-run Worker, senza secret o deploy. Test Python produttivi: soltanto in copia temporanea isolata.

Leggere [audit](docs/AUDIT.md), [architettura](docs/ARCHITECTURE.md), [contratto](docs/SYNC_CONTRACT.md), [verifiche Fase 1](docs/PHASE1_VALIDATION.md), [handoff](docs/HANDOFF.md) e [piano](../../PLANS.md). La verifica visiva segue le tre skill frontend versionate; non sostituisce i test sui dati.

## Modello C — contratti, senza attivazione

La selezione current-state è definita e verificabile separatamente dalla sync v1. Contratto, criteri, digest e verifica privata in [MODEL_C_SELECTION_CONTRACT.md](docs/MODEL_C_SELECTION_CONTRACT.md). Importer, reader, schema e UI attuali non cambiano.
