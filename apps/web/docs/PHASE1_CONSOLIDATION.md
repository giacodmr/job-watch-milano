# Consolidamento tecnico D1 — 2026-10-30

## Esito e perimetro

GO per la fondazione **locale e read-only** della PR #25 dopo le correzioni sotto e CI verde sul suo head aggiornato. NO-GO per database/sync cloud: non è l'esito di questa fase. Nessun merge su main, deploy, provisioning, cambio visibilità, API LLM o dato operativo modificato. Non viene implementata V7, autenticazione, persistenza personale, CRUD o una nuova pagina.

Main verificato: `0b2984a669c4d0dae0b3b666945855c6cda86627`. #25 iniziale: `b84d7786e977602830f0c88b7afe5b47dc2da16d` (`codex/web-phase-one`, aperta). #29: `43029d1a9e706a42f8be3f7dd261e2705dfa1e23` (Draft). #30: `a811a79991e180f1fb2be2ec548c78dff91aac23` (Draft). #28 è già integrata dall'utente. Main è stato recepito nel solo branch della #25: il diff verso main rimane limitato ad app/documentazione, senza cambi ai file Python/dati/workflow produttivi.

Lavoro eseguito nel worktree separato `d1-consolidation`; preview e D1 persistente della #30 preservati. Le misure usano soltanto D1 effimeri. I bundle reali sanitizzati sono privati e fuori da Git; non sono fixture, build asset o artifact della PR.

## Problemi riprodotti e correzioni

1. **Cursore emesso ma non accettabile dall'API.** `sortKey` ammetteva 2.200 caratteri: JSON/base64 di una chiave Unicode valida poteva superare il limite cursor di 8.000. Test prima della correzione: Zod `too_big` sul cursore generato dalla prima pagina. Il nuovo cursore conserva snapshot/ID/filtri e ricava l'ancora dal PK `(job_id,snapshot_id)`. Non aumenta il limite pubblico; accetta anche i cursori legacy. Un'ancora inesistente dà 400, snapshot o filtri differenti restano rifiutati.
2. **Nome azienda fermo alla prima osservazione.** L'identità globale era inserita con ON CONFLICT DO NOTHING; le letture ignoravano il nuovo nome nello snapshot confermato. Il test rename trovava zero risultati invece di tre. Migrazione additiva `0005_company_names.sql`, schema 5: il nome entra in `company_versions`. Letture/ricerca usano la versione del checkpoint e fallback al nome legacy. Nessun UPDATE globale durante staging; ID azienda invariato. Le osservazioni precedenti conservano NULL/fallback senza inventare il passato; uno staging schema 4 ripreso idrata il campo dal bundle validato sotto CAS/budget. Migrazioni 0001–0004 immutate. La migrazione non inventa alias fra nomi azienda: un cambio di job key richiede ancora mapping autorevole Python, non euristiche nuove.
3. **Ricerca valida → 503.** Il contratto ammette 120 caratteri; D1 limita i pattern LIKE/GLOB a 50 byte. Il test HTTP con query accettata produceva 503. `instr(lower(...),lower(?))` conserva ricerca letterale, parametri bound e comportamento case-insensitive ASCII senza quel limite; wildcard, UTF-8 e input lungo sono coperti. La ricerca substring può ancora scansionare lo snapshot e richiede budget prima del cloud.
4. **Accuratezza della misura dei record invariati.** Osservazioni dello stesso evento possono essere ripetute in più memorie. Un confronto tramite Map singola per event key le classificava erroneamente come nuove. Il confronto è ora multiset e distingue payload, provenance e molteplicità; tre test sintetici coprono il caso. Questo riguarda la diagnostica, non cambia la deduplicazione degli eventi nel DB.

Nessuna modifica al matching, ai filtri Python, alla coda worker, a fingerprint o alle regole di precedenza delle scelte utente. Manifest/protocollo restano v1; DTO read-only e semantica dei filtri invariati.

## Test e verifiche

- Baseline intatta della #25: `npm ci`, `npm run check` → 39 test Vitest PASS, strict/build PASS; zero vulnerabilità segnalate.
- Riproduzione rossa dei due primi difetti: Unicode cursor rifiutato e rename non trovato. Riproduzione rossa separata del 503 sulla query lunga. Non vengono attribuiti a produzione eventi osservati solo nelle fixture sintetiche.
- Dopo correzioni: `npm run check` → **46 test PASS in 4 file**, strict/build PASS. Include il wrapper dei 10 unittest exporter; nessun test legge record produttivi o usa credenziali.
- Copertura preesistente confermata: alias/fingerprint e decisioni persistenti, assenza CLOSED vs UNKNOWN, staging invisibile, ripresa chunk, replay e hash divergente, CAS concorrente con rollback, history/provenance, filtri/pagine, confine loopback e comandi 501 senza persistenza.
- Estensioni mirate: cursore Unicode, legacy e anchor inesistente; nome per snapshot con staging e ripresa dopo upgrade; upgrade 2→5 conserva osservazioni e foreign key; query lunghe Unicode/wildcard; conteggio duplicati e differenze payload/provenance.
- `npm run db:migrate:local` → schema applicato nel solo DB vuoto del nuovo worktree; seconda esecuzione no-op. Ripetuta anche la migrazione finale in un'altra directory D1 effimera tramite `wrangler d1 migrations apply job-watch-local --local --persist-to <directory-privata>`, due volte: prima PASS, seconda no-op. Nessun DB dell'app già esistente cancellato o modificato.
- `npm run worker:check` → PASS, solo dry-run. UI/CSS e design V7 non modificati: nessuna nuova verifica visuale viene dichiarata.
- Stato CI GitHub da leggere sul relativo head della PR; non viene dedotto dai test locali. Le verifiche Python operative nel checkout non sono state eseguite.

## Misure riproducibili

`tools/measure-local.mjs` misura separatamente bootstrap, replay, nuovo commit e commit con le stesse fonti; verifica genealogia Git, valida i bundle e usa un D1 nuovo non persistente. I totali `meta.rows_written` sono confrontati con una strumentazione per statement/target e includono gli indici. Migrazioni e costi delle GET applicative sono esclusi. Tempo e CPU del processo Node locale non sono la CPU di una richiesta Worker remota.

Input reali, esportati dalla CLI corrente a SHA esplicito:

- A: `84593e95d60dd4634a3d7ff5f493c13f7fdb872d`.
- B: `b3540152d55b455dd485b167978e92a914a85fc7`.
- C: `0b2984a669c4d0dae0b3b666945855c6cda86627`, discendente di B con identico manifest dei file operativi.

Risultati aggregati della misura: [PHASE1_COSTS.json](PHASE1_COSTS.json). Nessun payload o chiave di job è versionato in quel file.

- A iniziale: **39.555 letture / 113.175 scritture**.
- Replay A: **2 letture / 0 scritture**.
- A→B: **46.946 letture / 62.728 scritture**, pur aggiungendo solo 16 identità job. Dei 5.454 job già presenti, 587 sono identici anche nella provenance e 3.044 hanno solo provenance diversa: **3.631 payload job invariati**. Alle versioni job/azienda con payload invariato sono attribuite **22.354 scritture**, di cui 4.090 su copie esatte. I cambi di timestamp sono considerati cambi di payload, non nascosti dal confronto.
- Replay B: **2 letture / 0 scritture**.
- B→C, file invariati: **46.963 letture / 62.608 scritture**; tutte le versioni job/azienda/fonte sono identiche. **33.802 scritture** copiano quelle versioni; il resto è soprattutto appartenenze per snapshot, marker e guardie. Queste appartenenze servono all'attuale modello di conferma: non si possono eliminare senza sostituirle con riferimenti equivalenti.
- Replay C: **2 letture / 0 scritture**.

La deduplicazione degli eventi funziona: nel passaggio A→B non si creano scritture di nuovi eventi semantic_reviews/user_decisions. La crescita viene da versioni e appartenenze; non è corretto chiamare incrementale l'import attuale. Dimensione D1 dopo i tre snapshot: circa **20,8 → 34,9 → 49,2 MB**; non è una proiezione garantita della crescita futura.

Esempio, dalla root app, con directory privata fuori da Git:

```sh
npm run sync:export -- --commit 84593e95d60dd4634a3d7ff5f493c13f7fdb872d --file "$PRIVATE_DIR/A.json"
npm run sync:export -- --commit b3540152d55b455dd485b167978e92a914a85fc7 --file "$PRIVATE_DIR/B.json"
npm run sync:export -- --commit 0b2984a669c4d0dae0b3b666945855c6cda86627 --file "$PRIVATE_DIR/C.json"
npm run sync:measure -- --file "$PRIVATE_DIR/A.json" --next "$PRIVATE_DIR/B.json" --same-files "$PRIVATE_DIR/C.json"
```

Free verificato il 2026-10-30: 5 milioni letture/giorno, 100.000 scritture/giorno, reset 00:00 UTC, 5 GB/account e 500 MB/database. Quote dell'account condivise, quindi due futuri D1 non raddoppiano il budget giornaliero. Indici e DDL incidono sull'uso. A quota Free esaurita le query falliscono. Fonti: [pricing](https://developers.cloudflare.com/d1/platform/pricing/), [account billing](https://developers.cloudflare.com/d1/observability/billing/), [limiti](https://developers.cloudflare.com/d1/platform/limits/). Nessun account cloud è stato interrogato: non viene dichiarato un residuo quota reale dell'utente.

## Sequenza esatta #25 / #30 / V7

1. Revisionare e integrare manualmente **solo #25 aggiornata**, dopo CI verde e verifica del diff contro main. Porta read-only/export/import/schema 5 e la UI diagnostica minima già esistente, senza #29. Nessun merge è eseguito da questo incarico.
2. Tenere #29 fuori dalla catena di merge. È un riferimento storico superato; archiviazione/chiusura eventuale spetta al proprietario. Non importarne App/CSS/skill come requisito della base tecnica o di V7.
3. Conservare #30 Draft come fonte del lavoro riutilizzabile, senza merge integrale. Exporter/importer/migrazioni/dipendenze sono già quelli della #25: **non ricopiarli**. Dopo #25, creare una branch da main aggiornato e portare soltanto il read model `getDashboard`, DTO, route GET e relativi test tramite hunk selettivi. Riutilizzare le nuove colonne/join e i fix della #25; nessun cherry-pick dell'intero file queries.ts o di sync.test.ts che li annulli.
4. Preservare inoltre i comportamenti utili della #30 per la successiva UI: query/abort/errori, filtri e cursori URL, lettura dettaglio/history/provenance, focus/scroll del dialog. Estrarre controller/hook indipendenti dalla presentazione quando si implementa V7, senza duplicare SQL o regole nel browser. Nessuna estrazione UI viene anticipata qui.
5. Integrare V7 **in una PR distinta da main consolidato**, usando il prototipo approvato fissato a versione/hash, le skill frontend e gli endpoint confermati. Riutilizzare i controller e i servizi; sostituire soltanto la presentazione precedente. Le operazioni senza backend restano disabilitate. Confronto visuale reale desktop/mobile e test dei contratti prima della review.
6. Ritirare la vecchia #30 solo quando i suoi hunk/comportamenti utili sono stati trasferiti e verificati. Non chiudere o riscrivere ora la #30; non renderla una dipendenza Git della futura UI. Una sola implementazione autorevole per exporter/importer/query e migrazioni additive ordinate.

## Gate residui e prossimo incarico

Prima di sync cloud: fast path per commit a fonti identiche, separazione osservazione/provenance da contenuto delle versioni con riferimenti stabili, contabilità condivisa account/giorno con prenotazione e stop conservativo (import, indici, schema, retry, due D1), bootstrap distribuito/ottimizzato e retention misurata senza cancellare identità, decisioni, alias o audit. Servono anche test di crash/CAS sul nuovo modello e misure runtime Worker effettive; 70.000 per invocazione non è un budget giornaliero.

Prima di persistenza personale o accesso remoto: autenticazione e autorizzazioni utente/servizio, storage privato separato dal catalogo e dal refresh Git, backup/restore e CRUD transazionale verificati. Non sono difetti attribuiti alla base read-only né capacità presenti oggi. La sicurezza/privatizzazione operativa segue il runbook #28 e richiede un incarico esplicito.

**Prossimo incarico circoscritto:** fast path locale per commit discendente con identici file allowlist, separando il commit osservato dallo snapshot contenuto condiviso. Acceptance: B→C non riscrive versioni/eventi/appartenenze, aggiorna solo checkpoint/provenance/audit con poche scritture misurate; identità/history e contesto letture restano coerenti; replay, crash, CAS, rollback e commit divergenti coperti. Nessun cloud, auth o nuova UI. È il primo risparmio dimostrabile sul caso da 62.608 scritture, senza un refactor generale.
