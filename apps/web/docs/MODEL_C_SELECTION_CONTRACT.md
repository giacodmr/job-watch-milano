# Modello C / PR 1 — contratti e prove della selezione

Baseline: PR #25 **MERGED tramite squash** in `004782c1d5b53c9c6abb0399c8368f28831104c7`; branch `codex/model-c-selection-contracts` da main aggiornato. Il vecchio head f66a5fc non deve essere un antenato del nuovo main. Nessuna modifica a motore Python, schema/migrazioni, importer, reader, UI, workflow o dipendenze. Nessun D1 persistente/cloud o API LLM. Questo contratto non attiva un percorso di sync alternativo.

## Componenti introdotte

- `shared/model-c-selection.ts`: selettore puro su un bundle v1 validato e contesto esplicito; ledger completo, soggetti conservati, catalogo, record minimi AI, eventi personali/review deduplicati e digest contenuto.
- `shared/projection-proof.ts`: metadati strict della prova, digest degli input e osservazione del catalogo; nessuna scrittura checkpoint.
- `tools/check-model-c.mjs`: adapter Git locale **read-only**, verifica byte/scope, riesegue l'export v1 in copia temporanea isolata, confronta l'intero envelope in memoria e stampa solo aggregati/digest. Non salva un secondo bundle e non importa D1.
- Test sintetici Vitest/Python e baseline pubblica contenente esclusivamente SHA e cardinalità aggregate, mai record reali.

## Regole di selezione v1

1. Validare l'intero bundle con il contratto v1 esistente. La fonte dei flag è la proiezione Python del commit: non ricalcolare fit, soglie, seniority, fingerprint o alias in JS.
2. Costruire/estendere il registro di **tutte** le identità e chiavi/alias, prima di selezionare payload. Modalità obbligatoria: `first-v1-bootstrap` soltanto per un primo import; `confirmed-ledger` per un DB già esistente. Quest'ultima richiede ledger e digest atteso del checkpoint fidato; righe/mapping mancanti o contraddittori falliscono. La provenienza del digest fidato va verificata dal futuro adapter, non può essere fornita da un browser.
3. Riutilizzare l'ID confermato se una chiave/alias lo risolve. Più ID candidati, due righe osservate per lo stesso ID o ownership azienda differente sono errori; nessuna fusione euristica. Un nuovo ID usa la stessa ricetta del primo import v1. Conservare anche identità/mapping non più osservati. Il ledger non è una lista di payload da mostrare.
4. Conservare sempre i soggetti con eventi/scelte personali o riferimenti attivi `SAVED`, `APPLICATION`, `DISMISSED`. Il chiamante deve passare esplicitamente tutti i riferimenti personali **già riconciliati**, anche quando la lista è vuota. Un riferimento senza identità nota è un errore. Non riordinare in JS gli eventi per inventare la precedenza effettiva.
5. `NOT_INTERESTED` effettivo Python o riferimento attivo `DISMISSED` impediscono catalogo e coda AI, anche con nuovo fingerprint, reportable o riapertura. `DISMISSED` qui è un fatto personale ricevuto dal chiamante: non crea un comando, non inventa motivi e non viene trasformato in `NOT_INTERESTED`.
6. Se esistono eventi personali ma manca la scelta effettiva Python, preservare il soggetto come `UNRESOLVED_PERSONAL` e non mostrarlo nel catalogo finché non riconciliato. Una scelta effettiva più recente ha precedenza su eventi storici senza ricostruire nuove regole temporali.
7. Catalogo aperto: solo `NEW`, `STILL_OPEN`, `UPDATED`, senza soppressione manuale/conflitto, e almeno un flag autorevole `reportable=true`, `needsAnalysis=true`, scelta `INTERESTED/TO_REVIEW/APPLIED`, oppure riferimento attivo salvato/candidatura. Non leggere APPLIED come un record CRUD già esistente.
8. La coda è il sottoinsieme aperto con `needsAnalysis=true`, con soli identificativi, fingerprint, URL, batch e stato tecnico/idoneità. `workerEligible=false` o `JD_UNAVAILABLE` restano espliciti: non sono rigetti semantici. Il contratto non amplia la selezione del worker ChatGPT.
9. `CLOSED` e `UNKNOWN` non entrano nel catalogo aperto. Con contesto personale rimangono soggetti archiviati con lo stato originale. Un riferimento non più osservato ha lifecycle **null**, non CLOSED inventato. `PARTIAL` è copertura ATS, non lifecycle: non dedurre chiusure né esclusioni dalla sola coverage.
10. Hard rule e review semantica non reportable sono classificabili come `AUTOMATIC`, mai come scelte utente. Senza utilità/riferimenti, non trasferire il loro payload nel catalogo; ID/alias restano nel ledger.

Gli eventi personali sono deduplicati per `(jobId,resultSha256)` con lo stesso event ID del v1 e tutte le osservazioni/provenance conservate in memoria. Fatti incompatibili con lo stesso hash sono rifiutati. Le review selezionate mantengono anche lo storico dei soggetti utili/personali. `personalEventPolicy=APPEND_ONLY_NO_DELETE_BY_ABSENCE`: questi output sono osservazioni da unire, **non un piano di cancellazione** di PERSONAL. La futura retention ha un contratto separato.

## Digest verificabile e tre nozioni distinte

La prova `job-watch-model-c/1` affianca il bundle v1: non cambia manifest/protocollo v1, schema 5 o letture correnti.

- `projectionInputDigest`: SHA-256 RFC 8785 di versione contratto, digest del contesto selezione (ledger precedente/riferimenti), runtime Node/Python, metadati byte dei file sorgente e dell'implementazione.
- Chiusura sorgenti conservativa: **tutti i file Git `.py`, `.json`, `.jsonl` al commit osservato**, inclusi regole, archivi, receipt ed eventuali nuovi moduli importati. Implementazione: tutti i `.ts/.mjs/.py` in `shared/` e `tools/`, compresi exporter, contratti e selettore effettivamente usati. I moduli core e tutti i file del manifest v1 sono obbligatori; path ordinati/unici.
- L'adapter verifica repository, genealogia, tipi di blob e hash/byte da Git; non basta fidarsi di hash dichiarati. Un bundle legacy non certifica il codice eseguito: il checker ripete l'export dal Git archive con lo stesso observedAt e confronta l'envelope completo prima di attestarlo. Hash preimages restano nel pipe privato, mai nei log.
- Questa chiusura include anche moduli/test non pertinenti: può invalidare il riuso più spesso del necessario. È deliberatamente conservativa; restringerla richiederà una prova completa delle dipendenze. Non è una firma/autenticazione, né certifica timezone database/ambiente remoto: prima del cloud servono artifact/runtime immutabili e verifica server fidata.

`observedGitCommit` è il commit verificato nell'ultima osservazione. `contentOrigin` conserva commit e hash manifest dell'origine del contenuto attuale. `catalogRevision` aumenta solo quando cambia `catalogContentDigest`; commit diverso a contenuto identico conserva origine e revisione. Il digest contenuto include ledger, selezione, campi funzionali proiettati delle vacancy consultabili e contesto aziende/fonti; esclude hash/path di provenance, timestamp di import e cronologia degli eventi personali. I timestamp operativi restano significativi.

`canReuseProjection` verifica solo un prerequisito di uguaglianza degli input verificati. Non attiva no-op, salta eventi personali, verifica antenati o fa CAS: queste operazioni restano responsabilità dell'importer futuro. Un cambio Python/exporter/regole/contesto invalida il riuso anche a JSON o payload identici. Uno stesso contenuto può dunque conservare catalogRevision pur richiedendo nuova verifica della proiezione.

## Verifiche e baseline private

Da `apps/web`:

```sh
npm ci
npm run check
npm run worker:check
node tools/check-model-c.mjs --file "$PRIVATE_BUNDLE_A" --baseline tests/baselines/model-c-audit-a.json
```

Non mettere percorsi/bundle privati in fixture, script CI o output. La baseline numerica è soltanto test data aggregato; il selettore non contiene 5454/5474/300/429/151. I test pubblici costruiscono sorgenti sintetiche in directory temporanee e invocano codec/proiezione Python invariati. Le prove reali sono un comando locale esplicito, non parte della CI.

Input A (`84593e95…`): **5.454 identità, 5.474 mapping, 300 eventi personali unici, 429 soggetti, 151 record catalogo, 66 coda AI, 360 review**. Riconciliati con l'audit. Nessuna selezione limita il ledger; i 429 non sono 429 identità totali. Scarti manuali e chiuse restano nell'archivio personale, non fra le opportunità aperte.

Input B (`b3540152…`) e C (`0b2984a…`): confronto locale aggiuntivo dei conteggi e del contenuto; esiti effettivi nel resoconto PR. Le misure di costo pregresse 113.175/62.728/62.608 non sono nuove misure di questa PR: **zero scritture D1 del checker**. Nessun beneficio di costo del futuro importer viene dichiarato implementato.

## Risultati eseguiti

- `npm ci`: PASS, 0 vulnerabilità segnalate; nessuna modifica di versione Node o dipendenze.
- `npm run check`: PASS, **63 test Vitest in 5 file**, TypeScript strict e build. Include il wrapper degli **11 unittest Python exporter** e sei scenari di proiezione Python sintetici. L'equivalenza ID/alias/eventi è confrontata anche con l'importer v1 su D1 effimero.
- `npm run worker:check`: PASS, solo dry-run; bundle frontend invariato rispetto alla baseline.
- Checker privato su A con baseline numerica: PASS, replay completo v1 identico, cardinalità esatte sopra. Su B e C: PASS, **5.470 identità / 5.490 mapping / 300 decisioni / 440 soggetti / 161 catalogo / 77 coda / 360 review** per entrambi.
- B/C hanno lo stesso catalogContentDigest; projectionInputDigest differisce per la chiusura conservativa dei file/codice, senza implicare una nuova revisione contenuto. Nessun no-op attivato.
- Test del checker con codice Python realmente modificato in un repository sintetico temporaneo: JSON sorgenti invariati, contenuto catalogo invariato, input digest diverso. Tentativo di manifest alterato rifiutato con codice redatto; nessuna chiave/titolo sentinella nei report.
- `git diff --check`: PASS. Nessun comando locale `db:migrate:local` eseguito e nessuna migrazione aggiunta/modificata. I test e la CI legacy continuano a creare soltanto D1 effimeri del runner per verificare lo schema esistente.
- CI GitHub: verificare sul nuovo head della PR; non dedotta dai risultati locali. Non sono stati eseguiti collector o comandi produttivi Python.

## Gate PR 2

GO allo schema **locale** soltanto dopo test e CI verdi di questa PR. PR 2 deve definire: checkpoint fidato del ledger completo e contesto PERSONAL completo; FK/riconciliazione tra due DB; provenienza duale; promozione atomica e reader current-state; budget condiviso comprensivo di staging/apply/cleanup; backup/restore prima di qualsiasi rimozione. Non ricostruire un DB esistente da un bootstrap sull'ultimo commit ignorando gli ID precedenti.

Nessun trasporto mutativo, autenticazione, nuovi eventi Python, schema, importer nuovo o UI è attivato. Non integrare #29 o l'intera #30. Il solo schema futuro non autorizza cloud o nuovi costi.


## PR #33 post-review: retained decision presence

The importer may supply optional `personalDecisionJobIds` from confirmed V1 / PERSONAL history. These are identity-checked and bound in `selectionContextDigest`, carrying only the existence of original personal events. The existing rule 6 applies when a current Python effective choice is absent: `UNRESOLVED_PERSONAL`, no catalog or AI queue, personal subject retained (lifecycle null if unobserved). This does not synthesize a NOT_INTERESTED/DISMISSED choice or reorder events. Omission preserves the original context format/digest; no V1 envelope or database schema changes. The current importer rejects multi-owner PERSONAL rather than combine owners' references.
