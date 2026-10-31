# M47 — Durable local publication, cross-D1 recovery and bounded retention

**State: IMPLEMENTED LOCALLY IN PART — DO NOT MERGE AS COMPLETED M47.**
**TESTED LOCALLY:** subject to the latest PR #48 CI result (record SHA below).
**CLOUD_VERIFIED: NO; DEPLOYED: NO; ACTIVATED: NO; Gate B CLOSED.**

## Scope and architecture

The existing Node-only `importModelC` remains the sole trusted author of
CATALOG and PERSONAL SQL. The M46 service JWT continues to grant only
`catalog:stage`. It can never initiate publication, PERSONAL writes or GC.
None of these offline modules is imported into either deployable Worker.

Physical databases are separate: CATALOG schema v7, PERSONAL schema v3.
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
migration-hash-locked. Readers/preflights are upgraded to require v7. The
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

**v2 (durable synthetic-local D1 transport, not deployable)** in `shared/model-c-ingestion-v2.ts` adds
complete owner-neutral CATALOG records: companies, ATS sources, vacancy
metadata including nullable/closed lifecycles, confirmed identities,
alias mappings and source/coverage provenance. It preserves deterministic
chunk digests, idempotency keys, inventory digests and replay comparison
against a *trusted, independently computed* projection.

Private user/semantic event payloads are excluded from CATALOG v2. They
must remain inside the separately authorized, owner-bound PERSONAL
pipeline. Do not invent a `catalog:stage` permission to read PERSONAL.

**V2 persistence implemented:** `worker/model-c-ingest-v2-lab.ts`
implements a detached, signed-JWT, synthetic-only D1 HTTP receiver; schema
`0007_v2_ingestion.sql` provides immutable versioned runs, chunks, receipts
and archive. `tools/model-c-v2-stage-attestation.ts` reconstructs persisted
packets, and `tools/model-c-v2-trusted-stage.ts` compares against an
independently verified Git/Python inventory and original trusted plan.
The existing atomic CATALOG importer and journal now support v2 and v1 run
identity explicitly. These changes do not authorize production routes,
Cloudflare traffic, remote quotas or CPU feasibility.

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

## Final completion sprint — implementation, evidence and blockers

**Status vocabulary:** `IMPLEMENTED_LOCALLY` applies to code committed on
PR #48; `TESTED_LOCALLY` applies only after relevant Miniflare/GitHub Actions
test success on the final SHA. `CLOUD_VERIFIED=NO`, `DEPLOYED=NO`,
`ACTIVATED=NO` for the entire milestone. **Gate B CLOSED.**

### V1 / V2 / physical schema

| Feature | V1 unchanged | V2 local-only |
|---|---|---|
| Wire contract | `job-watch-model-c-ingestion/1` | `job-watch-model-c-ingestion/2` |
| Run ID | `ingest:<sha256>` | `ingest-v2:<sha256>` |
| Stored CATALOG | Reduced inventory | Full owner-neutral inventory incl. original source origin, stable identities and aliases |
| Transport | JWT HTTP v1 isolated lab | JWT HTTP v2 isolated lab `model-c-ingest-v2-lab.ts` |
| D1 storage | v5 receipt tables retained by v7 | Separate v7 live/archive receipt tables |
| Journal | One immutable common chain | Same common chain with v2-specific completeness audit |
| Publish authority | Trusted Git/Python importer only | Trusted Git/Python importer only |
| PERSONAL writes | Not granted | Not granted |

Physical CATALOG v7 and PERSONAL v3 remain **separate databases**. The
`0007_v2_ingestion.sql` migration is additive to 0001–0006 (none rewritten)
except journal guard trigger replacement in v7. Hash-locked migration history
preserves v1. A CATALOG transactional publication batch cannot be combined
atomically with a PERSONAL commit. The importer records the actual HEAD,
then performs owner-bound PERSONAL reconciliation and verifies durable
receipts before writing `COMPLETED`.

### Field-by-field trusted projection matrix

All fields below originate in the pinned canonical Git/Python snapshot
or independently verified identity ledger. Client hashes prove packet
integrity, **not** source provenance. Canonical comparison of every
persisted V2 record with independently rebuilt trusted packets is required
before `VERIFIED`.

| Snapshot / selection fields | Wire v2 | CATALOG / reader / recovery responsibility |
|---|---|---|
| Company `id,name,configId,tier,priority,careerUrl,membership` | YES | Company identity, display, history |
| Company `sourcePath,sourceSha256` | YES | Origin provenance |
| ATS `id,companyId,sourceKey,family,inventoryUrl` | YES | Source/ATS mapping |
| ATS `coverage,generatedAt,coveragePath,coverageSha256` | YES | Coverage freshness/provenance |
| ATS `sourcePath,sourceSha256` | YES | Source origin |
| Vacancy `jobKey,aliases,upstreamSourceId,companyId,sourceId` | YES | Original keys, mappings, stable reconciliation |
| Vacancy `jobId,selectedKind` | YES | Derived only from trusted identity/selection, CATALOG membership |
| Vacancy `title,location,batch,canonicalUrl,applyUrl` | YES | Reader display and filters |
| Vacancy `lifecycle,fingerprint,firstSeenAt,lastSeenAt` | YES | Lifecycle, history, no delete-by-absence |
| Vacancy `needsAnalysis,analysisStatus,analysisMethod,hardExclusionReason,sortKey` | YES | AI queue/analysis filtering and selection verification |
| Vacancy `workerEligible,technicalStatus` | YES | Eligibility metadata |
| Vacancy `sourcePath,sourceSha256` | YES | Origin |
| Ledger identities `jobId,companyId,originJobKey` | YES | Permanent identity ledger |
| Ledger alias mappings `key,jobId` | YES | Permanent alias ledger |
| `fitScore,reportable,effectiveDecision` | NO | Trusted selection and owner-bound PERSONAL context; not a service grant |
| `semantic`, `user` event rows | NO | PERSONAL append-only events, imported by trusted owner-bound path only |
| `pipeline` rows | NO | Operational pipeline health, not the CATALOG vacancy reader |

The protocol is complete **for the owner-neutral CATALOG reader's inventory**,
not a transport for every field of the entire snapshot. `selectedKind`
is recomputed by trusted selection; staging may never choose an owner.
The reader uses `needsAnalysis` and other vacancy metadata. Missing
trusted source fields must fail before promotion.

### State machine / recovery

```text
[JWT service: catalog:stage] -> D1 CATALOG v7 run / numbered chunks
                 |                |
       no publish/PERSONAL        v
                         durable receipts, resume/replay
                                  |
                            RECEIVING
                                  v
                    COMPLETE [all chunks + hashes]
                                  |
                        trusted Git/Python/plan
                                  v
                              VERIFIED
                                  |
                       owner-bound PERSONAL append
                                  v
                          PERSONAL_PREPARED
                                  |
                  atomic CATALOG D1 CAS+HEAD+journal
                                  v
                          CATALOG_PUBLISHED
                                  |
                PERSONAL receipt+APP-revision readback
                                  v
                      PERSONAL_RECONCILED -> COMPLETED
                                  |
                   future non-current terminal run
                                  v
             immutable archival run/chunk receipts + journal
```

Archive compaction in `model-c-v2-ingest-retention.ts` uses an atomic D1
batch per completed, published, **non-current** run. Archiving does not
remove immutable journal events or receipt digests. Archived replay does
not recreate staged rows. Missing archive evidence and unknown outcomes
must fail closed. Retention archive storage grows with the total count
of historical runs/chunks; unbounded storage sustainability is not claimed.

After an uncertain 503, read the durable run/chunk status, HEAD, journal
and PERSONAL receipt **before any retry**. A run at `COMPLETE` has not
been Git verified. A run at `CATALOG_PUBLISHED` may still have PERSONAL
pending. Restart the trusted importer against the original pinned Git
commit, plan and authorized owner, not an invented new run. If APP
revision changed, recalculate and reconcile idempotently. Do not
blindly delete staged runs or reconstruct cross-DB atomicity.

### 30-cycle and fault-injection tests

New `tests/model-c-m47-continuous.test.ts` executes 30 Git commits on
one synthetic repo and one pair of Miniflare databases, with real Python
snapshot verification, service JWT v2 staging, importer, PERSONAL,
journal, readers, archive and replay. It tests a lost PERSONAL receipt,
APP decision, historical archived replay and overlapping duplicate
chunk delivery. The test prints `M47_CONTINUOUS_30_CYCLES` with one
object per cycle, including record/chunk counts, revision before/after,
journal/personal status, active/archived count, importer write accounting
and retention `meta.rows_written`, duration, and replay.

**Certification condition:** the test must actually pass CI on the
final SHA. Merely adding the test is not evidence of 30 executed cycles.
The complete 19-point failure-injection matrix and all PERSONAL
categories/assessments are not independently demonstrated by this
test yet. A green CI cannot substitute for missing acceptance proofs.

### Writes and Free-tier

Local importer `ImportMetrics` separates bounded statement cost from
observed D1 write rows. Staging v2 appends one run + journal trigger
and a row per chunk; retention archives one run + one receipt per
chunk and deletes the original payload rows. SQL indexes, triggers,
migration writes, PERSONAL, reconciliation and remote usage
must be budgeted separately. The 30-cycle test records importer
measured writes and local retention `meta.rows_written`; these
are **not** an account-wide Cloudflare bill or remaining quota.
Workers Free 10ms CPU and remote D1 quota are unverified. Unknown
quota = DENY; the normal project ceiling is 30,000 write units,
60,000 only on explicit authorization. An initial bootstrap exception
does not grant recurring extended budget. See the official links above.

### AC-01–AC-16 — provisional, final SHA certification required

| Criterion | State | Concrete implementation / remaining evidence |
|---|---|---|
| AC-01 provenance | PARTIAL | V2 trusted-stage compares independent Git replay; final CI needed |
| AC-02 completeness | PARTIAL | V7 immutable full chunks and trusted canonical inventory; full matrix pending |
| AC-03 CATALOG atomicity | PARTIAL | Importer D1 single batch + journal head guard; v2 test verdict pending |
| AC-04 CAS | PARTIAL | Existing CAS guard / concurrency regressions; v2 contention not exhaustive |
| AC-05 PERSONAL | PARTIAL | APP revision stability + existing immutable history; all categories pending |
| AC-06 Cross-D1 | PARTIAL | Owner receipt + independent checkpoint reader; additional crash windows pending |
| AC-07 Recovery | PARTIAL | Post-commit PERSONAL loss + rollback tested; full matrix pending |
| AC-08 Replay | PARTIAL | Versioned archive receipts and HTTP replay; continuous CI pending |
| AC-09 Security | PARTIAL | Detached signed JWT + capability restriction; deeper import graph audit pending |
| AC-10 Free | PARTIAL | Local SQL bounds; actual quota/Worker CPU unverified |
| AC-11 Regression | PARTIAL | All existing tests must pass final SHA |
| AC-12 Cloud safety | PASS in repository work | No remote resources created, migrated or deployed in this sprint |
| AC-13 CI | PARTIAL | Final `Web foundation` and `Validate Job Watch` need SUCCESS |
| AC-14 Hygiene | PARTIAL | Existing PR #48 branch only, diff to be reviewed |
| AC-15 Documentation | PARTIAL | This report and private runbook; insert final measured run log |
| AC-16 Continuous | PARTIAL | New executable 30-cycle test; result must be actually observed |

**Handoff:** Do not deploy, merge or start M48. Gate B remains CLOSED.
If complete local proofs cannot be established, Gate A stays PARTIAL
and PR #48 stays DRAFT.
