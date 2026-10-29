# Verifiche Fase 0

Eseguite il 2026-10-29 su worktree dedicato da main `0f6287a461de3951ba6dc4d2a00235a5fde494fd`. Runtime locale Node 24.15.0, npm 11.12.1. Nessuna migrazione o risorsa Cloudflare remota.

## Esiti

- `npm install --no-fund --no-audit`: lockfile generato e dipendenze installate. Riproduzione successiva/CI con `npm ci`.
- `npm run check`: **21 test passati**, 2 file Vitest; compilazione TypeScript strict senza errori; Vite build riuscita. Test Worker bundle eseguito con Miniflare/workerd e D1 reale locale effimero, non mock del database. Uso dell'adapter ufficiale `convertV4MiniflareOptions` per il runtime Miniflare 5 richiesto da Wrangler.
- `npm run db:migrate:local`: 0001 e 0002 applicate con successo al binding locale UUID nullo; seconda esecuzione: **No migrations to apply**. I file SQL identici sono applicati nei test.
- `npm run worker:check`: bundle dry-run riuscito con binding DB/ASSETS/APP_ENV, nessun upload. Worker circa 774 KiB non compresso / 122 KiB gzip; bundle client circa 313 kB / 96 kB gzip.
- `npm audit --omit=dev --json`: nessuna vulnerabilità segnalata per dipendenze di produzione al momento della verifica; non costituisce garanzia futura o audit completo del tooling.
- `npm run dev:api`: Worker e D1 dichiarati **local**, server 127.0.0.1:8787. HTTP health 200 con `database: ready`, schema 2, sync disabilitata, accesso produzione false e UTC. HTML 200 con CSP same-origin e no-store.
- Browser in-app: pagina React renderizzata, API raggiungibile e schema pronto; click «Verifica di nuovo» aggiorna l'orario Europe/Rome da una nuova risposta; nessun errore o warning console rilevato. Vista stretta del pannello verificata visivamente, senza KPI o dati operativi inventati.
- Suite Python invariata: **197 test, OK**, 9,383 s. Eseguita con requests 2.32.5 dell'ambiente Python locale esistente in una copia temporanea estratta da `git archive HEAD` della base analizzata, fuori dal checkout operativo. Le scritture delle fixture/proiezioni della suite restano nella copia temporanea. Nessun collector produttivo o workflow schedulato avviato.
- Dopo il riallineamento al main `6725fefa45e5bab0494ceb05b9edb2fe999a1e1f`: suite Python aggiornata **206 test, OK**, 11,148 s, sempre in una nuova copia temporanea isolata. I nove test aggiuntivi sono quelli Worldline ricevuti da main; il codice produttivo rimane identico a quell'upstream.
- `git diff --check`: senza errori. Verifica diff rispetto alla base per file produttivi Python/JSON/archive e workflow preesistenti: nessuna modifica. Il branch locale utente iniziale non è stato modificato.

## Copertura significativa

SQL: tabelle richieste, assenza colonne JD, FK e conservazione identità chiuse, snapshot incompleto/sparso non pubblicabile, checkpoint solo confermati, staging invisibile nella lettura checkpoint, distinzione semantica/utente, dedup review/decisioni, idempotency comandi, payload immutabili, transizioni senza salti, conferma vincolata a receipt/commit/checkpoint, audit append-only.

API: schema pronto/vecchio/tabella mancante/binding mancante; metodi/query non ammessi; JSON 404 senza fallback SPA; comando 501 senza persistenza/echo; blocco remoto su API/asset anche con header Access fittizi; ambiente diverso da local negato. Contratti: unknown fields, JD/status/actor arbitrari, motivi vaghi/mancanti/lunghi, batch/capacità/versioni non valide, allowlist path, manifest duplicato o chunk sparso.

## Limiti espliciti

Auth Cloudflare Access/JWT, importer, sync di conferma, canonicalizzazione hash web, adapter comandi e quote applicative sono progettati ma non implementati. La configurazione implementata è esclusivamente locale e rifiuta richieste remote. Nessun dato GitHub nel D1; nessun endpoint accetta realmente un comando. La disponibilità residua dei piani cloud e il budget GitHub account non sono stati certificati.

I test di schema non sostituiscono i futuri test di importer/adapter: genealogia commit, hash effettivi manifest, validità semantica Python, matching del risultato confermato e ruoli richiedono le fasi successive. Lo storico prima del primo import non è ricostruito. Nessun test JWT remoto o smoke cloud viene dichiarato eseguito. L'esito CI GitHub è distinto da queste verifiche locali e va letto sulla PR.
