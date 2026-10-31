# M47 — Durable local publication, cross-D1 recovery and bounded retention

**State: IMPLEMENTED LOCALLY IN PART — DO NOT MERGE AS COMPLETED M47.**
**TESTED LOCALLY:** subject to the latest PR #48 CI result (record SHA below).
**CLOUD_VERIFIED: NO; DEPLOYED: NO; ACTIVATED: NO; Gate B CLOSED.**

## Scope and architecture

The existing Node-only `importModelC` remains the sole trusted author of
CATALOG and PERSONAL SQL. The M46 service JWT continues to grant only
`catalog:stage`. It can never initiate publication, PERSONAL writes or GC.
None of these offline modules is imported into either deployable Worker.

Physical databases are separate: CATALOG schema v6, PERSONAL schema v3.
No cross-database transaction is asserted. CATALOG publication retains one
transactional D1 batch and an atomic compare-and-swap publication head.
PERSONAL append precedes that batch, and a separate PERSONAL reconciliation
follows it. Retry is based on durable receipts, not network response status.

### V6 additive migration

`catalog/migrations/0006_ingest_journal.sql`:
- Adds an append-only `catalog_ingest_journal` chain initialized by M46 run
  creation (and backfilled for existing M46 receipts).
- SQL triggers check prior sequence, prior digest, allowed transitions and
  the matching published head before `CATALOG_PUBLISHED`.
- Creates immutable `catalog_ingest_archive_runs` and
  `catalog_ingest_archive_chunks` carrying original digests/idempotency
  receipts without record payloads.
- Narrows the M46 delete triggers solely for transactions with a matching
  immutable archive, a terminal COMPLETED journal and no current head. For
  unarchived, incomplete, pending, malformed or current runs, deletions
  still fail. All archive/journal UPDATE/DELETE operations remain forbidden.
- Keeps M46 run and chunk content immutable. No historical migration was
  rewritten.

`model-c-schema.ts` applies the additive migration atomically and is
migration-hash-locked. Readers/preflights are upgraded to require v6. The
v1 ingestion *wire* remains `schemaVersion:5` for compatibility; it MUST
not be confused with the physical v6 database version.

### Journal and recovery phases

`model-c-publication-journal.ts` implements the durable event chain:

`RECEIVING → COMPLETE → VERIFIED → PERSONAL_PREPARED →
CATALOG_PUBLISHED → PERSONAL_RECONCILED → COMPLETED`

Fail-closed terminal/problem markers are `RECOVERY_REQUIRED`,
`CONFLICT`, `STALE` and `UNVERIFIABLE`. They never mean completed.
The journal is read back and digest-checked before advancement; replay with
different proof is a conflict. A failed D1 write requires readback and
returns `JOURNAL_OUTCOME_UNKNOWN` where certainty cannot be established.

`COMPLETE` is based on a full audit of actual immutable M46 chunk bytes,
counts, digests, and referential structure — it does not imply independent
Git provenance. `VERIFIED` follows verification by the trusted Git/Python
adapter against the full selection, ledger and digest-checked plan.
`PERSONAL_PREPARED` is recorded after the PERSONAL append transaction.
`CATALOG_PUBLISHED` is inserted **inside the same D1 batch** that switches
the CATALOG head; the SQL trigger verifies the head/run binding.
`PERSONAL_RECONCILED` and `COMPLETED` require an owner-bound readback of
the receipt and matching PERSONAL references, including the zero-reference
case. A concurrent APP revision causes conservative failure rather than an
unfounded completion claim.

The journal records compact proof digests, not personal data, source JSON,
tokens, file contents or secrets. It is a transition audit, not a substitute
for signed Git provenance, and it does not imply distributed atomicity.

### Transport versions

**v1** remains `job-watch-model-c-ingestion/1`, with its unchanged
reduced schema and strict legacy limits. Only the full independently
replayed Git/Python source may be published; a lossy v1 payload never
becomes CATALOG SQL directly.

**v2 (offline contract only)** in `shared/model-c-ingestion-v2.ts` adds
complete owner-neutral CATALOG records: companies, ATS sources, vacancy
metadata including nullable/closed lifecycles, confirmed identities,
alias mappings and source/coverage provenance. It preserves deterministic
chunk digests, idempotency keys, inventory digests and replay comparison
against a *trusted, independently computed* projection.

Private user/semantic event payloads are excluded from CATALOG v2. They
must remain inside the separately authorized, owner-bound PERSONAL
pipeline. Do not invent a `catalog:stage` permission to read PERSONAL.

**Important limitation:** there is NO authenticated v2 HTTP ingestion
handler or v2 durable staging table yet. The contract is only an offline
packet builder/verifier. It is NOT a production transport or complete
resolution of the v1 capacity limitations. Packet limits are conservative
laboratory constraints, not remote CPU or quota verification.

### Compaction and historical replay

`model-c-ingest-retention.ts` performs a bounded, single-run-at-a-time
D1 transaction to archive completed **non-current** run/chunk receipts,
then delete only their bulky staged payloads. It verifies the terminal
journal, published historical run, exact inventory cardinality, archive
receipts and postcommit state. Unknown write outcome causes readback or
fails closed; it never retries a potentially committed delete blindly.

The detached M46 HTTP laboratory also recognizes original archived
signed run/chunk replay and archived status, subject to the original
service principal digest. It NEVER re-stages archived payloads.
The persistent journal and archive receipts remain immutable.

**Limits:** durable archive growth continues, and a verified 30-cycle
end-to-end publication/GC demonstration is still required. The optional
offline compact method is not a background GC, retention schedule or
Cloudflare remote operation.

### Security and fault model

- Service JWT `catalog:stage` is unable to promote, reconcile, archive or
  operate a PERSONAL database.
- The importer requires `executionTarget:'local-ephemeral'`; identity
  selection and provenance are independently reconstructed from Git.
- PERSONAL decisions, assessments, historical references, events and APP
  overrides remain authoritative; no delete-by-absence.
- No owner ID, SQL, route or capability is accepted from the M46 staging
  client to authorize publication.
- D1 Time Travel is a whole-database restore with potential loss of later
  writes; no automated restore is implemented.
- Unknown delivery, stale CAS, conflicting receipts or runtime/quota
  uncertainty are blocking states.
- No new production route or deployable secret; deployment remains CLOSED.

## Cloudflare Free limits (official documentation, checked 31 Oct 2026)

- D1 Free: 100,000 rows written/day, 5 million read/day; 500 MB per DB,
  5 GB account storage, 50 queries per Worker invocation (a `batch()`
  counts as one D1 query toward this subrequest limit), 100 bind
  parameters/query and 100 KB maximum statement length.
- Workers Free: 10 ms CPU/request, 128 MB memory, 100,000 requests/day.
- D1 batch statements run in one SQL transaction and roll back together
  on a statement failure; a batch does NOT merge billing of row writes.
- Since September 2026 Cloudflare enforces the D1 Free daily read/write
  limits, returning errors until midnight UTC once exceeded.
- References:
  https://developers.cloudflare.com/d1/platform/limits/
  https://developers.cloudflare.com/d1/platform/pricing/
  https://developers.cloudflare.com/d1/observability/find-expensive-queries/
  https://developers.cloudflare.com/workers/platform/limits/
  https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/

Local conservative importer admission: 30,000 write units normally, 60,000
only with explicit authorization, and the separately guarded one-time
bootstrap exception. Journal events are covered by an extra conservative
40-unit bound per incomplete staged attempt, but **real remote total quota
including staging, future v2 writes and GC has not been measured or
reserved**. Local D1 `meta.rows_written` is a measurement, not a remote
quota reservation. Unknown Cloudflare account quota = DENY.

## AC-01—AC-15 acceptance matrix

| AC | Status | Evidence / missing requirement |
|---|---|---|
| AC-01 Provenance | PARTIAL | Trusted Git replay and attestation tested on v1; complete remote v2 handler absent |
| AC-02 Completeness | PARTIAL | v1 fails closed; v2 offline inventory proof, no persistent v2 stage |
| AC-03 Catalog atomicity | PASS locally | Existing D1 publication batch + journal head event in the same batch; test required |
| AC-04 CAS | PASS locally | Existing importer concurrent-publisher regression, v6 recheck |
| AC-05 Personal data | PASS locally | Existing PERSONAL append-only, APP preservation; v6 recheck |
| AC-06 Cross-D1 consistency | PARTIAL | Owner receipt readback and durable journal, failure matrix incomplete |
| AC-07 Full recovery | PARTIAL | D1 journal, retry and loss-of-ack regression; complete matrix not yet proven |
| AC-08 Idempotence | PARTIAL | v1 run/chunk and archive replay; 30-cycle end-to-end pending |
| AC-09 Security | PARTIAL | Detached service/auth, no PERSONAL grant; v2 stage handler unimplemented |
| AC-10 Free-tier accounting | PARTIAL | Conservative local bounds; remote CPU/usage unverified |
| AC-11 Regression | PENDING | Full checks on final PR SHA required |
| AC-12 Cloud safety | PASS | No deployed services, secrets or remote writes |
| AC-13 CI | PENDING | Full checks on final PR SHA required |
| AC-14 Repo hygiene | PENDING | Review changed files and merge base |
| AC-15 Documentation | PARTIAL | This technical runbook plus private deployment runbook |

These statuses are conservative. A green CI alone does not upgrade all
PARTIAL items to PASS. **M47 is not yet ready for merge**.

## Test evidence

Tests cover M46 JWT/HTTP v1 staging, loss-of-reply receipt inspection,
M47 real D1 journal immutability/ordering/conflict, original importer
atomic publication, postcommit PERSONAL reconciliation, v2 offline full
CATALOG inventory verification, and the terminal archive/replay path.
Results must be checked on the **final** SHA, not inherited from M46.

## Follow-up before Gate A can be certified

1. Implement authorized durable v2 chunk receiving, independently trusted
   verification of its full projection, and bounded multi-invocation staging.
2. Demonstrate 30 continuous end-to-end staged publications, reconciliation
   and compaction without losing APP facts or exceeding D1 limits.
3. Complete all specified crash/failure windows, including cross-owner,
   APP concurrency and unknown network outcomes using actual D1 state.
4. Reconcile full staging, journal, index, GC and migration write accounting
   against observed `meta.rows_written`; verify Free CPU and remote limits
   separately before Gate B.
5. Pass complete CI and review final head SHA, permissions and Worker routes.

**Decision: Gate A NOT COMPLETE; Gate B CLOSED. PR #48 must stay DRAFT.**
