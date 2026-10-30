# Verifica Fase 1 locale — 29/30 ottobre 2026

## Riferimenti e confini

Base implementazione/import reale: `84593e95d60dd4634a3d7ff5f493c13f7fdb872d`. Main ricontrollato: `3661d7afc324af1fc51d5a6d7effa4fccf82c0b9`; delta soltanto dati di raccolta, documentato in AUDIT. Branch `codex/web-phase-one`, PR verso main senza merge automatico. La proiezione locale non è presentata come live main.

Nessuna modifica a Python produttivo, regole/configurazioni/inventari/memorie/archive, bridge o workflow. Nessuna nuova dipendenza applicativa o modifica al lockfile/Node. Nessun deploy, cloud provisioning, D1 remoto, LLM API, fetch JD o comando operativo. Build e bundle sync ignorati da Git; nessun file dati nella build frontend.

## Comandi e test

- `npm ci`: OK, 84 pacchetti installati, audit npm 0 vulnerabilità.
- `npm run check`: **39 test Vitest in 3 file**, OK; include **10 unittest Python sintetici** eseguiti dal test exporter. TypeScript strict e Vite build: OK. Il conteggio 39 include il wrapper Python, non sommare 10 come se fossero altri test Vitest.
- Test D1/workerd effettivo: manifest/hash/allowlist prima delle scritture; input incoerente; idempotenza; chunk riutilizzato con hash diverso; interruzione/ripresa; CAS concorrente con rollback effettivo di checkpoint/pubblicazione/audit; revisione obsoleta e genealogia divergente; decisioni cross-fingerprint e alias; alias di staging futuro invisibile; arresto budget; migrazione 2→4 con osservazioni conservate e foreign_key_check vuoto; filtri/cursori; API di sola lettura e blocco remoto.
- Exporter sintetico: Amazon UUID/ID numerico e scelta persistente, evidenze `$e` compresse e corrotte, UNKNOWN in copertura parziale, archivio CLOSED con batch ignoto, memory-only NOT_INTERESTED, evidenza storica abbreviata, JD_UNAVAILABLE, nessun fingerprint ricalcolato o input modificato, snapshot incoerente rifiutato, CLI fissata a commit anche con checkout dirty, byte hash manomessi rifiutati prima di D1.
- `npm run db:migrate:local`: 0003/0004 applicate localmente; una nuova base locale ha applicato 0001–0004. Due esecuzioni successive: **No migrations to apply**. SQL 0001/0002 invariati.
- `npm run worker:check`: dry-run riuscito con DB locale, ASSETS e APP_ENV=local; nessun upload.
- Suite Python produttiva a 3661d7a: **215 test, OK, 10,742 s**, archivio/venv temporanei con requests 2.32.5. Il primo tentativo con Python di sistema privo di requests non ha potuto importare 18 moduli; ripetuto nell'ambiente temporaneo corretto, senza cambiare dipendenze del progetto.
- `git diff --check`: OK. Confronto dei path produttivi e del lockfile rispetto alla base: invariati.

## Import reale e budget misurati

`sync:export -- --commit 84593e95d60dd4634a3d7ff5f493c13f7fdb872d`: 8.588 record strutturati, 1.761 chunk, bundle sanitizzato 7.477.950 byte. Comprende 284 aziende, 207 fonti, **5.454 job**, 2.340 review, 302 scelte utente e 1 proiezione pipeline. Nessun hashInput o JD nel bundle persistito.

`sync:import` su D1 locale conferma revisione 1, snapshot `snapshot:fd6c5b7a85b6ac0b3652863fb21a22ad5997f5e9a226e6499beeaff7a78b9215`. Il budget standard ha arrestato un bootstrap intermedio lasciando STAGING; per la sola prova locale è stato usato `--max-writes 500000`. Un DB intermedio è conservato sotto `.local-sync/bootstrap-before-alias-membership`; nessun DB preesistente dell'utente è stato cancellato.

Misurazione riproducibile con `/usr/bin/time -l npm run sync:measure` (opzione `-- --file <bundle>`), del medesimo bundle su un D1/workerd effimero vuoto, migrazioni reali, stesso servizio importer:

- **39.555 righe lette, 113.175 scritte**, 1.761 chunk applicati; DB 20.779.008 byte; servizio import 111.163 ms.
- `/usr/bin/time -l` sul processo di misura (include preparazione schema, import e replay): 113,06 s real, **82,42 s user + 16,08 s system**, picco RSS 468.303.872 byte. Sono CPU aggregate locali del processo/figli, non CPU di una richiesta Worker Cloudflare. Non attribuirle al limite remoto da 10 ms.
- Replay effimero: 2 righe lette, **0 scritte**, 0 chunk applicati, revisione invariata. Replay CLI sul DB persistente: stesso risultato, DB 20.791.296 byte (differenza per metadata migrazioni Wrangler).

Budget standard: 70.000 scritture/invocazione con margine 1.000 prima del chunk e soglia DB 350 MB. Non è una quota giornaliera aggregata: bootstrap >100.000 scritture e nuovi commit con versioni complete non sono pronti per sync cloud continuativa Free. Prima della Fase 2: riduzione delle versioni invariate/retention, contabilità account/giorno, schedulazione/ripresa con quota reale e misure CPU Worker. Nessuna spesa locale.

API sulla proiezione persistente (misure puntuali; durata locale non SLA): inventario ALL 5.454, pagina 25, 21.894 righe lette/80 ms; OPEN 1.811, 11.144/16 ms; pending 66, 10.078/24 ms; APPLIED 9, 10.962/10 ms. Le righe includono count e SELECT pagina, non le query di contesto; ricerca substring e count possono leggere molte righe. Nessuna proiezione di KPI inventata.

## Revisione UI e browser effettivo

Applicate frontend-design e job-watch-ui-direction; revisione dei file UI con [Web Interface Guidelines ufficiali](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md), recuperate durante la verifica. Direzione: superficie neutra, verde funzionale, tipografia di sistema intenzionale, tabella compatta e stati distinti; nessun template promozionale, glow, KPI gigante o dato simulato.

Browser IAB su 127.0.0.1:8787, dati reali confermati. Desktop 1440×1000 CSS; mobile **390×938 CSS misurati dal DOM** (override IAB 351×844 con zoom del browser). Corpo mobile largo 390, regione tabella 349, tabella 1010: overflow confinato alla tabella, senza overflow del body. Le dimensioni CSS effettive sono distinte da quelle richieste al browser.

Controllati: layout/leggibilità, filtri nativi etichettati, filtri avanzati mobile, risultati reali e pagina successiva, URL/ripristino filtri ALL al reload, dettaglio con provenienza/history distinta, focus visibile e restituito al ruolo dopo Escape, stato loading reale del dettaglio, ricerca senza corrispondenze con zero reale, errore reale 400 tramite limit=101 e recupero «Reimposta e riprova». Nessun mock di risposte nel browser. I test API verificano anche DB senza checkpoint; questa vista iniziale non è stata catturata nel browser prima dell'import.

Difetti corretti e ricontrollati:

- `src/App.tsx`: filtri avanzati mobili richiudibili e URL esplicito lifecycle=ALL dopo azzeramento.
- `src/styles.css`: contenuto del dialog scorrevole con header/azioni sempre raggiungibili; wrap di titoli/hash e controlli mobile a 16px.
- `index.html`: titolo Opportunità e theme-color coerente.
- `src/JobDetail.tsx`: identificatori protetti dalla traduzione automatica.

Evidenze JPEG locali fuori da Git, directory visualizzazioni della chat: `job-watch-phase-one-desktop.jpg`, `job-watch-phase-one-mobile.jpg`, `job-watch-phase-one-mobile-detail.jpg`, `job-watch-phase-one-empty.jpg`, `job-watch-phase-one-error.jpg`. Contengono soltanto la vista locale, nessuna JD o motivazione personale. Revisione finale: nessun difetto bloccante osservato nei file UI. Non è un audit assistivo completo con screen reader o dispositivi fisici.

## Limiti e prossimo passo

Nessun auth/JWT remoto, MCP server, dispatcher, polling, comando o storico ricostruito da tutta Git history. History inizia dalle versioni osservate; ogni elenco dettaglio è limitato a 50 eventi. Promozione candidati/rename con mapping identità diverso richiede riconciliazione esplicita, mai fuzzy matching. Nessuna garanzia di costo/CPU remoto derivata dalle prove locali. La Fase 2 richiede incarico esplicito e i gate sicurezza/budget del piano.
