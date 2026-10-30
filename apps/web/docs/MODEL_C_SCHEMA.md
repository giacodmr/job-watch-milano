# Model C / PR 2 — schema locale inattivo

Baseline: PR #31 MERGED tramite squash `5abbdf67cea4d4004b0cdfa066ef292b7e499682`. Branch `codex/model-c-local-schema` dal main aggiornato. Questa PR definisce schema, laboratorio sintetico e prove; non implementa l'importer Model C o i suoi reader.

## Separazione fisica e compatibilità

- `model-c/catalog/migrations/0001_catalog.sql`: database **CATALOG** autonomo, schema 1.
- `model-c/personal/migrations/0001_personal.sql`: database **PERSONAL** autonomo, schema 1.
- `migrations/0001…0005`: fondazione **v1**, schema 5, immutata e ancora attiva. Nessun nuovo SQL viene aggiunto a questa directory.

Non ci sono nuovi binding/configurazioni Wrangler, route, feature flag, UI o comandi di sync attivi. Il Worker continua a usare soltanto il binding v1 `DB`. I due database Model C esistono soltanto nei runtime effimeri dei test/laboratorio. Il runner verifica il ruolo del database e rifiuta la sovrapposizione fra ruoli e sopra v1; il solo prefisso delle tabelle non è la separazione fisica.

## CATALOG

Le identità permanenti sono in `catalog_company_identity`, `catalog_source_identity`, `catalog_vacancy_identity`; `catalog_aliases` conserva tutte le chiavi autorevoli. Nessun algoritmo SQL ricalcola ID, alias o fingerprint. UPDATE/DELETE delle identità/mapping confermati sono bloccati; le chiusure non autorizzano cancellazioni. Le FK composite impongono ownership aziendale di source e vacancy.

`catalog_company_current`, `catalog_source_current`, `catalog_vacancy_current` hanno una riga per ID. Il catalogo vacancy contiene solo i lifecycle aperti NEW/STILL_OPEN/UPDATED e kind OPPORTUNITY/AI_QUEUE. Le fonti hanno coverage separata VERIFIED/PARTIAL/FAILED/NOT_CHECKED. I riferimenti personali CLOSED/UNKNOWN stanno in PERSONAL, mentre la loro identità rimane nel ledger CATALOG. Il payload corrente può essere rimosso tramite un delta esplicito senza rimuovere l'identità.

Nessuna colonna owner, decisione personale, motivazione, fit score, reportable o sintesi AI è nel catalogo o nello staging. Non ci sono payload JSON arbitrari, JD o descrizioni. Titoli/URL sono campi strutturati, non un rilevatore di PII: l'importer dovrà applicare le allowlist e i validatori del contratto. Il catalogo selettivo rimane comunque privato.

Provenienza e revisioni:

- `catalog_origins`: commit/path/hash del dato, legato a un run; immutabile.
- `catalog_content_revisions`: digest del contenuto e origine (commit + hash manifest), immutabili; non contiene versioni complete delle vacancy.
- `catalog_ledger_checkpoints`: digest e conteggi attesi dell'intero ledger. Il ledger fidato è quello raggiunto da catalog_head, mai l'ultima riga preparata. Il controllo SQL verifica conteggi alla pubblicazione; **l'hash canonico e la sua origine fidata devono essere verificati dall'adapter PR 3**.
- `catalog_runs`: commit osservato, digest della proiezione, revisione CAS attesa, revisione contenuto/ledger, conteggi e stato STAGING → READY → PUBLISHED oppure ABORTED.
- `catalog_head`: unico scope `catalog`, revisione di sincronizzazione monotona e riferimenti a run, contenuto e ledger. Una nuova osservazione può conservare la stessa revisione contenuto; avanzamenti di contenuto/ledger saltati o senza nuovo digest sono respinti.
- `catalog_audit`: pubblicazione append-only inserita dal trigger nella stessa operazione che avanza l'head.

## Staging e atomicità: garanzie precise

`catalog_stage_companies/sources/vacancies/aliases` sono tabelle tipizzate separate dai dati correnti. Le vacancy staged distinguono IDENTIFY_ONLY, UPSERT e REMOVE. Le identità nuove non sono inserite nel ledger confermato dalla sola scrittura in staging. I riferimenti staged possono indirizzare nuove identità non ancora applicate: risoluzione nell'unione ledger+staging e integrità del batch completo spettano alla PR 3. I dati correnti hanno FK effettive.

`catalog_chunks` conserva indici contigui, digest dichiarati e conteggi. READY richiede tutti gli indici attesi. Le righe staged sono immutabili; non si aggiungono righe dopo READY. Dopo PUBLISHED/ABORTED la pulizia dei soli record staged/marker è consentita in ordine FK; audit, origini, checkpoint, identità e alias rimangono. Tempi e budget della pulizia non sono implementati.

Le viste `catalog_visible_*` leggono solo le tabelle correnti e restano vuote prima del primo head. Stage e READY non diventano visibili. Queste viste sono un contratto di lettura futuro, **non sono collegate ai reader attuali**.

La pubblicazione finale PR 3 dovrà usare **un unico `db.batch()` transazionale** comprendente:

1. `INSERT INTO catalog_cas_guard(expected_revision) VALUES (?)`, che fallisce sulla revisione sbagliata e si ripulisce da solo.
2. Inserimento di identità/alias nuovi, applicazione dei soli delta correnti e verifica delle invarianti.
3. Aggiornamento/creazione dell'head con la revisione prevista; trigger strutturali (inclusi conteggi correnti aziende/fonti/vacancy e intero ledger), stato PUBLISHED e audit completano la pubblicazione atomica.

I test dimostrano rollback del batch dopo una scrittura corrente seguita da CAS fallito, e un solo vincitore fra due pubblicazioni concorrenti. Una UPDATE con WHERE che modifica zero righe **non sostituisce l'asserzione CAS**.

Lo schema non può obbligare un amministratore a includere ogni UPDATE corrente nel batch, verificare hash SHA sui payload o dimostrare genealogia Git. **Scrivere direttamente nelle tabelle current prima della transazione finale è vietato dal contratto dell'importer**: lo schema non mantiene copie complete della versione precedente. I test di schema non equivalgono alla validazione dell'importer. Dimensione/durata massima della promozione, letture a revisione coerente, digest reali e failure injection del percorso completo sono gate PR 3. Non è permesso pubblicare un delta a pezzi per rispettare un budget.

## PERSONAL e riconciliazione

PERSONAL contiene:

- `personal_owners` e `personal_job_refs`: owner opaco, job ID stabile, cattura minima privata e lifecycle nullable, inclusi CLOSED e UNKNOWN.
- `personal_reference_state`: riferimenti attivi SAVED/APPLICATION/DISMISSED con revisioni, senza motivo inventato o obbligatorio per DISMISSED.
- `personal_decision_events` e puntatore current: tutti gli eventi personali disponibili, ID originali, scelta, fingerprint, categoria/motivazione breve nullable, timestamp, hash e provenance. Eventi append-only; FK locali impediscono puntatori ad altro owner/job.
- `personal_assessment_events/current`: review personalizzate, fingerprint, metodo, decisione semantica, fit/reportable, sintesi limitata ed evidenza. Il puntatore non rende valida una review con fingerprint storico.
- `personal_heads` e `personal_audit`: digest del contesto privato, revisione monotona e audit essenziale.
- `personal_catalog_receipts` e `personal_reconciliation`: copie immutabili delle prove di catalogo e stato PENDING/VERIFIED/CONFLICT per i riferimenti.

Nessuna FK attraversa i database. Il job ID esterno può esistere prima che il catalogo sia disponibile: il dato personale non si cancella per questa assenza. L'applicazione dovrà verificare ID/alias contro il ledger completo, non soltanto le vacancy selezionate, e confrontare la receipt con l'head CATALOG attuale. La FK alla receipt garantisce solo un riferimento **locale**; non dimostra la verità dell'altro database.

VERIFIED richiede receipt locale e revisione personale corrente. `personal_verified_reconciliation` esclude verifiche rimaste a una revisione personale precedente. Un avanzamento CATALOG non può invalidare automaticamente una riga nell'altro DB: confronto e nuova riconciliazione sono applicativi. La receipt attesta la riconciliazione del riferimento, non un ACK di un comando GitHub.

Ordine futuro: conservare prima i fatti personali e segnare riconciliazione pendente; pubblicare il catalogo completo; verificare i riferimenti e registrare la receipt. Un'interruzione mantiene PENDING/CONFLICT, non successo simulato. La scelta personale più recente non viene sovrascritta dal refresh. Il significato delle precedenze rimane Python/contratto PR 1; le revisioni SQL non inventano una regola temporale o una nuova API mutativa.

## Migrazioni e laboratorio riproducibile

`tools/model-c-schema.ts` è un helper Node dei test, mai importato da Worker/browser: migrazioni additive in batch, journal nome/hash e ruolo verificato. Una seconda applicazione è no-op; hash diversi per una migrazione già registrata falliscono. Non modificare questi file dopo l'integrazione: aggiungere la prossima migrazione numerata nel relativo scope.

```sh
cd apps/web
npm ci
npm run check
npm run worker:check
node tools/model-c-lab.mjs
```

Il laboratorio non accetta path/config/database di input. Crea CATALOG, PERSONAL e v1 sintetici in D1 Miniflare effimeri, senza persistenza e con `cf:false`. Nessun comando `db:migrate:local` è eseguito contro il checkout corrente. La CI v1 esistente continua a usare il proprio DB temporaneo del runner. Nessuna fixture legge bundle/dati reali.

Misure effettive della configurazione locale bloccata dal lockfile in [MODEL_C_SCHEMA_METRICS.json](MODEL_C_SCHEMA_METRICS.json). Sono costi `meta.rows_written` per **schema vuoto/journal e restore sintetico**, non per il bootstrap del catalogo. Il seed della fixture e le letture non sono inclusi. Nessuna conferma dei target 47–50 mila iniziali o 30–60 mila giornalieri: rimangono da validare con l'importer e contabilità completa nella fase successiva.

## Backup/restore locale verificato

Il laboratorio esegue realmente il ciclo su tutti e tre gli scope:

1. Catturare soltanto le tabelle applicative sintetiche, nomi/colonne, fingerprint dello schema e journal delle migrazioni; checksum SHA-256 canonico dell'intero backup. Limite intenzionale di 1.000 righe: non è un tool di backup produttivo.
2. Scrivere e rileggere il file in directory temporanea **0700**, file **0600**. Nessun backup è versionato, pubblicato o lasciato al termine.
3. Ripristinare **solo su un nuovo D1 vuoto**: verifica checksum, ruolo, fingerprint schema e hash delle migrazioni. Database già inizializzati/non vuoti sono rifiutati.
4. In una transazione sul target offline, sospendere i soli trigger di transizione, ripristinare lo snapshot con FK differite e reinserire gli stessi trigger. Serve per ricreare stati già PUBLISHED/CONFIRMED senza rieseguire effetti di pubblicazione. Nessun trigger viene disabilitato su un DB attivo.
5. Verificare `foreign_key_check`, `quick_check`, checksum di tutti i dati, ledger migrazioni e comportamento dei trigger dopo il restore. Sono testati corruzione, ruolo errato, journal incompatibile e destinazione non vuota.

Il backup v1 sintetico conserva ID, alias, NOT_INTERESTED e checkpoint confermato. La prova dimostra il percorso locale su fixture; non dichiara eseguito un backup di dati reali o provata la capacità di ripristinare un DB produttivo di dimensione arbitraria.

## Verifiche eseguite

`npm ci`: PASS, zero vulnerabilità; `npm run check`: **80 test Vitest in 7 file PASS**, TypeScript strict/build PASS (include gli 11 unittest exporter sintetici legacy); `npm run worker:check`: PASS, solo dry-run. I 17 nuovi casi coprono struttura, isolamento, CAS, ownership, eventi, replay e backup/restore. Nessun dataset privato è stato aperto per questa PR.

`node tools/model-c-lab.mjs`: PASS sui tre scope, file realmente scritti/riletti con permessi verificati, restore verificato e rimozione finale. Replay migrazioni: zero scritture. `git diff --check`: PASS; immutabilità dei file v1/binding/importer/reader/UI/dependency verificata nel diff. CI GitHub da verificare sullo head della nuova PR; non dedotta dai test locali.

## Rollback e gate PR 3

Ora: rollback del codice semplicemente lasciando v1 attiva. Nessun DROP, downgrade, reset o migrazione inversa del database esistente; i due nuovi schemi non sono applicati lì. Se un test/lab fallisce, eliminare soltanto il runtime effimero che ha creato.

Per il futuro cutover: conservare v1 e copie private complete, verificare restore a versione schema/commit fissata, costruire Model C separatamente e tenere i reader v1 finché il nuovo percorso non è validato. In caso di problema sospendere la sync Model C e tornare ai reader v1; non riscrivere main, ID o decisioni. Il ripristino dei due DB richiede ricevute di snapshot e riconciliazione, non una transazione distribuita presunta.

**GO alla PR 3 per implementare e misurare l'importer locale**, dopo CI verde di questa PR. Rimangono obbligatori: copia fedele del ledger v1 e dei fatti personali, verifica dei digest e delle precedenze, transazione unica di applicazione, controlli di completezza, riconciliazione, budget per staging/indici/apply/cleanup e test di crash in ogni fase. **NO-GO all'attivazione Model C o al cloud** finché importer e reader non sono validati. Nessun lavoro della PR 3 è anticipato qui; le funzioni di pubblicazione nella cartella test contengono solo fixture costanti.

Riferimenti tecnici primari: [batch D1 transazionali](https://developers.cloudflare.com/d1/worker-api/d1-database/), [FK e defer_foreign_keys](https://developers.cloudflare.com/d1/sql-api/foreign-keys/). Le garanzie sopra sono delimitate anche dai test effettivi, non dedotte soltanto dalla documentazione.
