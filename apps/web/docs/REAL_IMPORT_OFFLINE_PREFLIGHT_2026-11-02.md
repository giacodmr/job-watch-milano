# Job Watch — first real data offline preflight (2026-11-02)

**CURRENT OFFLINE STATUS:** `MULTI_DAY_BOOTSTRAP_IMPLEMENTED_AND_TESTED` (offline-only);
`REMOTE_IMPORT_NOT_AUTHORIZED`. The original one-shot bound below is retained
as historical evidence; the **final validated acceptance** is in the last
section of this document.

**Original one-shot preflight status:** `OFFLINE_PREFLIGHT_PASS`, `REMOTE_IMPORT_NO_GO`.

This report records a completed GitHub-hosted, read-only offline Model C preflight.
It is not a remote publication approval or evidence of any remote D1 query,
migration, ingestion, owner initialization, APP mutation, or Worker deployment.

## Exact evidence

- Source commit (existing `main`): `6b46f1e6f6ea3d466cb39f4d27e23f71ed1a8570`.
- GitHub Actions preflight run: https://github.com/giacodmr/job-watch-milano/actions/runs/41502600142
- Result: `success`; `LOCAL_PLAN_VALID`, `PINNED_GIT_OFFLINE_PROJECTION`.
- Source manifest digest: `29be78b3478db345cfabac2e6d7d0dbc0e67efbf0c106af98f7c0d7a87ca8927`.
- Projection digest: `23838f3833e308ddb5e259c1945a700abc3f34a4071f933d97f7ac930c553e13`.
- Snapshot/run ID: `3e9611399418c4ed2c32b84e`.
- Observed snapshot times: 2026-11-02 01:30:40–01:36:49 UTC.
- Direct independent comparison of all 8 input file SHA-256 values
  (`job_watch_run_state.json.source_sha256`) with the downloaded GitHub
  file bytes: **8/8 exact matches**.
- `job_watch_run_state`, `job_watch_healthcheck.snapshot` and
  `daily_worklist.snapshot` have matching operational snapshot metadata.
- The ephemeral-only preflight ran with a *temporary non-production owner namespace*
  generated within the GitHub Actions runner. No live owner identity was
  fetched or exposed. This does not attest production PERSONAL ownership.

## Read-only source inventory

| Batch | Open target jobs | Unknown lifecycle jobs | Companies in batch | Coverage verified | Coverage partial |
|---|---:|---:|---:|---:|---:|
| JW1 | 415 | 15 | 56 | 35 | 21 |
| JW2 | 969 | 5 | 53 | 25 | 28 |
| JW3 | 117 | 0 | 43 | 11 | 32 |
| JW4 | 284 | 1 | 55 | 29 | 26 |
| **Total** | **1,785** | **21** | **207** | **100** | **107** |

These are raw collected inventories, **not** Model C selected-catalog
counts, and 207 is a sum of per-batch company rows. The snapshot remains
`COMPLETE_WITH_WARNINGS` / `NEEDS_REVIEW`, with 5 daily actionable
reviews and 128 historical backlog items in the healthcheck. No
invented lifecycle transitions, fit scores or personal decisions.

## Actual pinned-source preflight output

| Metric | Measured result |
|---|---:|
| CATALOG local schema migrations | 7 |
| PERSONAL local schema migrations | 3 |
| CATALOG local migration rows written | 258 |
| PERSONAL local migration rows written | 111 |
| **Import required write bound** | **111,218** |
| Publication statements | 822 |
| Publication bytes | 3,231,218 |
| Maximum SQL statement bytes | 1,015 |
| Maximum statement parameters | 80 |
| Remote migration cost upper bound | **Not established** |
| Remote execution authorized | **false** |

The bound is a **conservative estimated upper bound**, not observed remote
write consumption. Local migration counts are **not** remote D1 billing
evidence. The existing pilot databases reportedly already have CATALOG v7
and PERSONAL v3; this was **not** rechecked remotely.

## Explicit blockers (code checked)

1. **Full bootstrap exceeds the Free-day bound:** 111,218 > 100,000
   D1 account-wide rows written/day, before external workload,
   margin or unknown remote setup. Overflow: **11,218**.
2. **Existing exceptional bootstrap admission:** `model-c-free-bootstrap.ts`
   rejects initial preflight bounds over **95,000**.
   Overflow: **16,218**.
3. **Remote M50 trusted controller:** `model-c-m50-trusted-controller.ts`
   requires operator budget <= **30,000**, and
   `publishM50WithRemoteOperator` explicitly rejects
   `oneTimeFreeBootstrap`. The first import cannot be unblocked
   by simply asserting a larger quota.
4. **Password runtime:** the deployed `APP_ENV=password` path is an
   interactive read-only password gate. The distinct service staging
   controller is gated under `APP_ENV=private`; no service-ingestion
   activation was verified on the password pilot.
5. **Cloudflare authority:** No current live account-wide write
   telemetry, protected remote publisher proof, PERSONAL owner
   initialization or Gate B authorization was supplied. Fail closed.

**Do not** import only selected vacancies while discarding the mandatory
identity/alias ledger; do not substitute synthetic PERSONAL history; do
not silently split one atomic CATALOG publication or journal run across
days without verified contract/recovery semantics. Do not upgrade billing
or increase admission limits in response to this report.

## Next concrete engineering decision

Using the **same pinned real source**, obtain a detailed **by-phase/by-table**
write-bound breakdown from the existing `importModelC` preflight metrics,
then select and prove a Free-compatible first bootstrap strategy that:

- keeps complete identity/alias provenance and immutable Model C semantics;
- respects per-day account-wide Free usage **and** internal durable reservations;
- preserves an atomic CATALOG head/CAS switch and recoverable PERSONAL receipt;
- does not expose a publisher via `catalog:stage` or a password browser session;
- uses read-only offline proof before requesting a narrowly scoped Gate B.

Until this proof exists: `REMOTE_IMPORT_NO_GO`.

## Working boundaries

- New branch: `codex/job-watch-real-import-preflight`.
- Login/routing worktree and `codex/job-watch-password-routing-fix`: untouched.
- `main`: untouched.
- Cloudflare D1 / Worker / secrets: untouched.
- No PR, merge or deployment.


## Multi-day follow-up: verified bound breakdown (2026-11-02)

**Outcome for the current implementation: `MULTI_DAY_BOOTSTRAP_BLOCKED`.**
This is a *bounded result about the implementation currently on GitHub*, not a
revocation of the original multi-day product strategy.

### Offline evidence

- Real-source diagnostic run with per-phase and per-table metrics:
  https://github.com/giacodmr/job-watch-milano/actions/runs/41514685622 — SUCCESS.
- Offline machine-readable single-CATALOG-batch admission assessment:
  https://github.com/giacodmr/job-watch-milano/actions/runs/41515202983 — SUCCESS.
- Both used source commit `6b46f1e6f6ea3d466cb39f4d27e23f71ed1a8570`
  and source manifest `29be78b3478db345cfabac2e6d7d0dbc0e67efbf0c106af98f7c0d7a87ca8927`.
- **Do not reuse a projection proof digest across different implementation
  revisions:** `verifyGitProjection` includes implementation files in its
  proof, and changing the diagnostic CLI changes the projection-input digest.
  The digest is valid for the exact implementation and context that produced it,
  not an interchangeable authority to publish data.
- No Cloudflare D1, Worker, secrets or production owner were accessed by the
  added workflow.

### Conservative import bound, by logical phase

| Phase | Write units upper bound | Current execution behaviour |
|---|---:|---|
| CATALOG staging (importer-owned SQL stages) | 28,634 | Included in ONE CATALOG publication `db.batch()` |
| CATALOG promotion | 44,190 | Same CATALOG batch |
| CATALOG checkpoint / CAS | 24 | Same CATALOG batch |
| **CURRENT CATALOG SINGLE-BATCH TOTAL** | **72,848** | **Exceeds ordinary 30,000-unit admission by 42,848** |
| CATALOG cleanup | 28,604 | Separate batch after publication/reconciliation |
| PERSONAL append and assertion checks | 5,158 | Separate PERSONAL batch, before CATALOG |
| PERSONAL reconciliation | 4,588 | Separate PERSONAL batch, after CATALOG |
| Reservation | 20 | Separate quota admission SQL |
| Journal on this unstaged preflight | 0 | **Not** a bound for a v2 staged run |
| **TOTAL** | **111,218** | Conservative entire attempt |

All figures above are index/trigger-weighted **planner estimates**. No
remote D1 write metering was performed. The journal bound would differ if
`stagedPublication` were provided.

### CATALOG by-table upper bounds (staging and cleanup both counted)

| Table | Planner rows/units | Bound (includes index weights) |
|---|---:|---:|
| catalog_cas_guard | 2 | 2 |
| catalog_content_revisions | 1 | 1 |
| catalog_ledger_checkpoints | 1 | 1 |
| catalog_runs | 5 | 10 |
| catalog_run_proofs | 1 | 2 |
| catalog_origins | 10 | 30 |
| catalog_stage_companies | 568 | 1,136 |
| catalog_stage_sources | 414 | 828 |
| catalog_stage_vacancies | 11,032 | 33,096 |
| catalog_stage_aliases | 11,072 | 22,144 |
| catalog_chunks | 2 | 4 |
| catalog_import_assert | 2 | 2 |
| catalog_company_identity | 284 | 568 |
| catalog_source_identity | 207 | 828 |
| catalog_vacancy_identity | 5,516 | 22,064 |
| catalog_aliases | 5,536 | 16,608 |
| catalog_company_current | 568 | 1,136 |
| catalog_source_current | 414 | 1,242 |
| catalog_vacancy_current | 436 | 1,744 |
| catalog_head | 1 | 3 |
| catalog_audit | 1 | 3 |
| **CATALOG phase total** | | **101,452** |

These are planner `Step.writes` rows, **not** actual selected vacancies
and not actual remotely metered rows. Large stage table bounds include
insert plus later deletion; they cannot be reassigned to a different
calendar day just by re-labelling the phase.

The existing preflight exposes PERSONAL as a reliable aggregate:
5,158 for append/checks and 4,588 for conservative reconciliation.
It does **not** expose an independently audited PERSONAL per-table
breakdown: do not invent one.

### Why existing v2 chunked staging is NOT proof of multi-day first bootstrap

1. `apps/web/worker/model-c-ingest-v2-production.ts` persists v2 run/chunk
   receipts and can resume by run ID. The receiver uses a shared durable
   reservation path for each run/chunk and rejects unknown account quota.
2. `apps/web/tools/model-c-v2-trusted-stage.ts` independently compares
   stored chunks with a full pinned Git projection and a trusted plan.
3. **However**, `apps/web/tools/model-c-importer.ts` generates separate
   `catalog_stage_*` rows and executes staging + promotion + HEAD in ONE
   `catalog.batch(prepared(catalog,publication))`, lines around 427–435.
   The existence of pre-received v2 packets does not remove these
   importer-owned write steps.
4. `model-c-m50-trusted-controller.ts` rejects budgets >30,000 and
   explicitly disallows `oneTimeFreeBootstrap` in the remote operator path.
5. `model-c-free-bootstrap.ts` refuses a complete initial bound >95,000.
   This is a secondary admission limit, **not** the main finding: even
   postponing cleanup leaves an unchanged single 72,848-unit CATALOG batch.
6. The D1 REST adapter's remote transactional/parity guarantees are still
   unverified on the real host. A successful Miniflare test is not remote
   proof.

### No valid numeric multi-day schedule for this version

A proposed Day 1 staging / Day 2 promotion / Day 3 cleanup plan would
**not** match the code's actual transaction boundaries. In particular,
promotion alone has a bound of **44,190**, already above 30,000. Quota
reservations and all-account telemetry cannot convert that into an
authorized 30,000-unit write.

Do not delete/skip identity records or split the HEAD/CAS commit without a
new tested invariant.

### Narrowest next engineering change (NOT implemented yet)

Use existing V2 durable staging and the existing publication journal, but
add a **revision-/digest-bound CATALOG preparation step** that can run in
bounded, durable chunks, remains invisible to readers until the final HEAD
switch, and safely coexists with full identity/alias provenance, APP
precedence, stale source detection and replay. Then construct the **final
CATALOG atomic batch <=30,000** (including all outstanding promotion,
assertions and journal writes) rather than pretending the existing
72,848-unit batch already supports separate days.

This is **not merely a one-line patch**: the current importer derives
trusted identity state from permanent tables even when no head is
published, and prepopulating them changes selection/replay context. The
prepare/promote boundary and recovery must therefore be implemented and
tested as one focused transaction-safety change. No speculation about
remote readiness or generic new milestones.

Tests for the eventual patch must cover: interrupted preparation and
resume across different UTC days; immutable source/run, no double-counted
receipt; no partial reader visibility; full alias/identity ledger; final
HEAD CAS conflicts and rollback; PERSONAL revision conflicts; lost ACK;
journal recovery; account-wide and internal daily budget fail-closed;
separate service staging and operator publication authority.

### Gate B disposition

**No remote ingestion/publication Gate B is ready for approval.** Before
requesting one, first demonstrate an offline implementation where the
individual durable mutation scopes all fit verified daily allowances,
then gather fresh real Free account-wide telemetry and prove remote D1
operator transaction semantics. Until then, preserve CATALOG v7 / PERSONAL
v3 pilot empty, APP writes and service ingestion off, and €0 budget.

### Actual changes in this branch

- Added aggregate-only CLI fields: `writeBoundsByPhase`,
  `catalogWriteBoundsByTable`, `catalogSingleBatchBound`,
  `catalogAtomicBatchBudgetLimit`, `multiDayBootstrapAssessment`.
- Added runtime invariants checking that summed phases and CATALOG
  table costs reconcile exactly with the total bound.
- Updated the isolated GitHub Actions preflight trigger and added
  targeted existing tests of import, quota, v2 ingestion and D1 REST.
- **No** importer write semantics changed; no PR/merge, Cloudflare
  operation, production owner, real snapshot publication, new importer,
  or authorization escalation.

### Targeted CI verification (completed)

- Run: https://github.com/giacodmr/job-watch-milano/actions/runs/41515309849
- Result: **SUCCESS**, **4 test files passed, 75 tests passed**.
- Suites: `model-c-importer.test.ts`,
  `model-c-free-bootstrap.test.ts`,
  `model-c-m49-production-ingestion.test.ts`,
  `model-c-m50-d1-rest.test.ts`.
- The real pinned Git offline preflight also passed inside this run.
- These existing regression tests verify laboratory importer/journal/quote
  boundaries; **they are not a test of a multi-day bootstrap implementation,
  which does not yet exist**, and do not establish real D1 REST atomicity.

**Final status:** `OFFLINE_PREFLIGHT_PASS`,
`MULTI_DAY_BOOTSTRAP_BLOCKED`, `REMOTE_IMPORT_NOT_AUTHORIZED`.

## Multi-day initial implementation — offline source-based preview (2026-11-02)

The branch now contains a scoped **initial empty-CATALOG only** prepare/publish
path in the existing `model-c-importer.ts`, with an additive CATALOG migration
`0008_phased_initial_preparation.sql`. The migration is **NOT** applied to
remote D1; it adds immutable preparation receipts while keeping the existing
published CATALOG v7 reader contract and `model_c_schema.version=7`. The
remote pilot still has the old seven catalog migrations. The new receipt table
is absent there and intentionally cannot be assumed.

The staged preparation is bound to independent pinned Git/Python verification,
the trusted projection, deterministic groups and immutable receipts. Its
`catalog_prepared_chunks` receipts atomically accompany group SQL mutations
and shared CATALOG write-budget reservations. Preparation uses existing
`planCatalog` SQL: big set-based identity/alias statements are restricted to
stable exact job/alias keys, never shrinking `LIMIT/OFFSET`. An initial
unpublished run may append immutable ledger identities but **cannot populate
the user-facing current tables or advance CATALOG HEAD** until the final
single `importModelC` transaction.

**Remote execution for this new path is deliberately denied** by both the
Node importer and the M50 trusted controller. Only local ephemeral D1
tests and read-only real-Git planner output are currently authorized. This
code has not passed live Cloudflare REST D1 semantics or GitHub migration
acceptance, and must not be deployed as an active publisher.

### Actual pinned snapshot planner output

Source SHA: `6b46f1e6f6ea3d466cb39f4d27e23f71ed1a8570`.
Source manifest: `29be78b3478db345cfabac2e6d7d0dbc0e67efbf0c106af98f7c0d7a87ca8927`.
The projection digest is an **implementation-specific** hash and changes as
source-controlled importer/preflight diagnostics change. Always use the digest
printed by the exact deployment candidate; do not reuse old values.

| Logical UTC day | Mutations planned | Conservative bound |
|---|---|---:|
| Day 1 | Prepare receipt groups 0,1,2 | **25,518** |
| Day 2 | Prepare receipt groups 3,4,5 | **25,262** |
| Day 3 | Prepare receipt groups 6,7,8 | **18,144** |
| Day 4 | Final CATALOG + PERSONAL append/reconciliation + reservation | **13,906** |
| Day 5 | Deferred CATALOG staging cleanup | **28,624** |
| **Total** | Phased SQL excluding independent v2 service staging | **111,454** |

The new conservative total is **236 higher** than the old unphased
111,218 bound because multi-day receipts/reservations have their own cost;
that is expected, not an effort to make the original number fit by omission.
The baseline prep bound is **68,924**, in nine receipt groups; original
CATALOG single-batch bound **72,848** is no longer the cost of the final
atomic transaction in the proposed offline path.

- Selected catalog rows: **218**.
- Complete vacancy identity ledger: **5,516**.
- Complete alias mapping ledger: **5,536**.
- Final CATALOG atomic bound alone: **4,140**.
- PERSONAL append/checks: **5,158**.
- PERSONAL reconciliation: **4,588**.
- Ordinary budget: **30,000/day**, reserved account-wide on CATALOG.
- Old `model-c-importer.ts` atomic path remains unchanged for normal
  incremental deltas and all existing imports.
- **NOT accounted for:** independent remote v2 service staging,
  remote Free account-wide live usage, D1 transport/transaction parity,
  additional remote migration costs, host-specific failure/retry reserve.

This is a **theoretical SQL planner schedule backed by real Git/Python
snapshot and local D1 index weights**, not proof of successful five-day
remote import. It makes no claim about a specific real calendar date; actual
operator reservations must use the current UTC quota day, except explicit
synthetic day simulation on local ephemeral databases.

### Publication and recovery invariants

- No public row visibility before `catalog_head`, verified through existing
  v7 CATALOG reader gating; dedicated acceptance tests exercise no-HEAD.
- Immutable receipt = run ID, group ordinal, plan digest and reserved bound;
  a previously committed group is not re-inserted or charged a second time.
- A missing receipt with irreversible preparatory rows requires operator
  recovery; never adopt a partially modified ledger as the initial baseline.
- Publication uses the existing importer PERSONAL append, single CATALOG
  batch/CAS/HEAD and post-CATALOG reconciliation and journal (when v2 staged).
- Cleanup may occur after a completed publication and must require another
  conservative D1 daily reservation. If v2 staged, journal must be COMPLETED.
- Source/owner/APP context divergence fails closed, rather than mixing a
  different source/projection with existing preparation receipts.
- The service staging JWT is not an operator publication capability.

### Remaining acceptance gates

1. Complete targeted GitHub Actions importer regression with the **3,000**
   identity synthetic multi-day test; original 700 identity fixture was small
   enough to fit one preparation group, so it did not test cross-day resume.
2. Add/verify lost-ACK recovery and forged/changed prepared payload tests.
3. Validate a v2-staged local end-to-end run via the M50 controller. No
   remote `M50_REMOTE_OPERATOR_GATE_CLOSED` bypass is permitted.
4. Validate the migration alongside all existing D1 read, command, backup and
   schema guards, including newly increased migration-file count.
5. Obtain a fresh remote quota observation and a narrow **new** Gate B for
   remote migration and staging; remote D1 batch semantics and operator
   publication authority remain independently unverified.

Until these pass: **`MULTI_DAY_BOOTSTRAP_PARTIALLY_IMPLEMENTED`**,
`REMOTE_IMPORT_NOT_AUTHORIZED`.

---

## FINAL OFFLINE ACCEPTANCE — verified 2026-11-02 (supersedes earlier open test items)

**Acceptance status:** `MULTI_DAY_BOOTSTRAP_IMPLEMENTED_AND_TESTED` for
**ephemeral local D1 only**. **Remote status:** `REMOTE_IMPORT_NOT_AUTHORIZED`.
No remote DB writes, Worker deployment, new owner, private APP writes,
secrets, Access activation, PR, or main merge occurred.

### Grounded CI evidence

1. [Final 10-suite integrated D1 regression](https://github.com/giacodmr/job-watch-milano/actions/runs/41532123024)
   — **SUCCESS; TypeScript PASS; 116/116 tests PASS**.
   Includes the 3,000-identity cross-day bootstrap, stable source/receipt
   resume, lost preparation ACK, unchanged HEAD prior to CAS publication,
   no premature cleanup/extra quota debit on replay, PERSONAL, migration,
   real Miniflare v2 HTTP staging -> phased prepare -> local M50 -> journal
   COMPLETED, remote prepared-publication denial and **30 consecutive
   v2 catalog revisions** with recovery and APP precedence.
2. [Final pinned real-data source/projection preflight](https://github.com/giacodmr/job-watch-milano/actions/runs/41533190555)
   — **SUCCESS; LOCAL_PLAN_VALID; 78/78 regressions PASS (4 suites)**.
   This second run validates current implementation files and the real
   pinned snapshot; the tests partially overlap with the 116-test run,
   so **do not add the counts together as unique tests**.
3. Snapshot/source commit (unchanged):
   `6b46f1e6f6ea3d466cb39f4d27e23f71ed1a8570`.
   SHA-256 manifest:
   `29be78b3478db345cfabac2e6d7d0dbc0e67efbf0c106af98f7c0d7a87ca8927`.
   **New implementation-specific projection digest:**
   `b754ae5efc5ec64d0eb2537f28e1d5d0db69079bdea6211de9a5725fcc71c47f`.
   This new proof supersedes older projection digests when using this exact
   implementation revision; proof must be revalidated if tools/shared files
   change again.

### Measured conservative schedule — source-pinned planner, not remote telemetry

| Logical UTC day | Mutation scope | Upper bound | Spare capacity vs 30,000 |
|---|---|---:|---:|
| Day 1 | Prepared CATALOG groups 0–2 | 25,518 | 4,482 |
| Day 2 | Prepared CATALOG groups 3–5 | 25,262 | 4,738 |
| Day 3 | Prepared CATALOG groups 6–8 | 18,144 | 11,856 |
| Day 4 | CATALOG HEAD/CAS + PERSONAL + reconciliation | 13,906 | 16,094 |
| Day 5 | Explicit CATALOG cleanup | 28,624 | 1,376 |
| **Total** | **Planner phases only** | **111,454** | |

Selection: 218 catalog vacancy rows, **all 5,516 identity records**
and **all 5,536 aliases**. The preparation path uses nine receipt groups
with conservative bound 68,924; final CATALOG atomic portion is 4,140.
The original 111,218 estimate is the **unphased** path and is not the
sum of the new guarded multi-day schedule. Daily numbers are **planning
upper bounds** and are not remotely metered writes.

**Outside this 111,454 budget:** v2 HTTP/service ingestion staging on the
remote D1, any additional quota already consumed by other account workloads,
actual remote migration units, live host transaction parity, and unexpected
operator recovery costs. For a v2 staged publication the journal can add an
extra bounded amount; the no-staged-source CLI schedule reports zero journal.
These must be admitted in a separate, account-wide real quota assessment
without increasing the 30,000-unit daily admission.

### Verified behavior and one targeted fix

- In the first integrated run, **115/116 PASS** exposed an actual defect:
  the normal replay consumed the future deferred cleanup. The importer now
  excludes runs with `catalog_prepared_chunks` from automatic cleanup and
  requires explicit `cleanupModelCInitial` with its own quota reservation.
  The subsequent integrated run was **116/116 PASS**.
- Existing v2 transport and trusted M50 controller are exercised
  end-to-end on ephemeral D1; no duplicate service publisher or generic
  SQL endpoint was created.
- The catalog receipt sidecar is **migration 0008**. It was verified as
  additive on a populated v7 CATALOG: `model_c_schema.version` remains 7,
  all existing run/ledger rows remain identical, receipt update/delete are
  denied, replay of migration is a no-op. Remote pilot has **not** received
  0008 and must not be assumed to have the sidecar.
- Remote M50 `preparedInitial` execution is still explicitly denied even
  when a separate operator capability is presented. This is intentional;
  offline acceptance **is not** a remote Gate B grant.
- No claims are made about remote D1's actual atomic HTTP behavior,
  credentials or quota observation.

### Next *single scoped* Gate B proposal (NOT AUTHORIZED / NOT EXECUTED)

**Gate B — additive CATALOG receipt schema migration only**, not data import.

1. **Read-only operator prechecks:** verify real Cloudflare Workers Free plan,
   account-wide D1 written rows for the current UTC quota day, correct EU
   database `job-watch-pilot-catalog`, `model_c_schema.version=7`,
   exactly 7 recorded CATALOG migrations, absence of
   `catalog_prepared_chunks`, no published CATALOG HEAD and no application
   data. If data/status changed, **stop**.
2. **Requested authorization (separate):** one hash-locked execution of
   `0008_phased_initial_preparation.sql` on **CATALOG only**, with at most
   **500 conservative account-wide write units and 12 follow-up SQL reads**.
   These caps are proposed safety limits, not measured remote costs.
   Stop **before execution** if remote accounting/statement budgeting cannot
   establish those caps. Never blind-retry a migration of uncertain outcome.
3. **Read-only postchecks:** eight hash-locked `model_c_migrations` receipts,
   unchanged v7 logical schema version, new empty receipt table, zero
   `catalog_head`, unchanged PERSONAL v3, D1 FK/integrity checks, no Worker
   change, and verified Free plan with €0 cost.
4. **Explicit exclusions:** no v2 ingestion, source import, owner
   initialization, PERSONAL writes, APP commands, deployments, Access/Zero
   Trust activation, key/secret changes, new databases, paid upgrade or
   remote initial publisher enablement.
5. **Recovery:** on unknown response, inspect immutable migration receipts
   and schema read-only first; do not repeat DDL until outcome is proven.

**Only after this Gate and independently verified v2 staging quota and
remote D1 operator semantics** may an operator prepare a second,
separately authorized data bootstrap Gate. The current Worker password
runtime does not itself confer `catalog:stage` or publication privileges.

**Decision:** offline bootstrap work is closed. No more generic hardening
or new milestone. The next user decision is whether to authorize the
precisely scoped schema-only Gate B above.
