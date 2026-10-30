# Model C PR #34 — SQL compaction and bootstrap admission

Base: main `1133c6aed1f94de6fec38f541b9869dac4543367`, squash merge of PR #33. Branch `codex/model-c-bootstrap-capacity`. Only the inactive Node importer, synthetic tests/laboratory and documentation change. No schema migrations, Python engine, UI, active API/reader/V1 importer, bindings, workflows, cloud or persistent databases change.

## PR #35 update

This page records #34 behavior under ordinary 30,000/60,000 ceilings. [MODEL_C_FREE_BOOTSTRAP.md](MODEL_C_FREE_BOOTSTRAP.md) documents the explicit initial-only 95,000 exception: the exact baseline is now actually published locally (94,173 reserved / 77,145 actual), with a zero-write ordinary replay. No SQL/staging optimization or paid quota is introduced. Remote account quota and activation remain unverified/disabled.

## Historical #34 result and readiness

The complete 5,454-identity / 5,474-mapping / 151-current-vacancy Git/selection/bootstrap plan now contains **739 statements and 2,704,855 serialized bytes**, down from **22,025 and 6,986,391** in PR #33. It fits the unchanged 8,000-statement / 8 MiB application limits. The baseline is constructed solely from synthetic data, with one company/source; its source cardinalities are asserted by the real selector before admission.

**The full baseline is still NOT bootstrap-ready.** Its verified conservative write-admission bound is **94,173**, above both 30,000 ordinary and 60,000 explicitly authorized daily allocations. The CI test attempts the complete import with the authorized ceiling and verifies refusal before reservations, PERSONAL append, staging, permanent IDs, current rows, head/checkpoint or audit. No part is published. Actual importer writes and committed budget reservation are both **zero**. This is a required bound, not a measured 94,173-row synchronization bill.

A second, substantial fixture **does publish**: 3,000 identities, 3,020 aliases and the same 151 selected vacancies. Its **428-statement / 1,517,448-byte** atomic publication succeeds with **42,788 actual writes and 52,455 reserved**, under the explicitly authorized 60,000 ceiling. The test compares the complete persisted ledger's canonical digest, exact current selection, permanent counts, PUBLISHED run, revisions/checkpoint, audit and FKs. Unobserved historical identities never appear in current. Replay writes zero rows; a subsequent minimal delta succeeds. A late head-trigger error rolls back all catalog mutations/revisions/origins/stage/permanent data while retaining the prior confirmed catalog and conservative spent reservation.

The SQL statement blocker is eliminated. Admission of the full documented baseline is blocked by the existing write policy, not hidden by a threshold increase or a partial publication.

## Implementation and invariants

- Typed staging rows are grouped by their exact column shape into multi-row `INSERT ... VALUES`, with at most **80 parameters** and **65,536 bytes of SQL** per statement. Nullability, provenance and all stage triggers/FKs remain effective per inserted row. Origin insertion and company/historical-source identity insertion are grouped too.
- New source/vacancy identities and aliases use set-based `INSERT ... SELECT` from the same sealed staging. Previously confirmed identity rows are excluded rather than updated; aliases remain immutable and inserts never silently overwrite collisions.
- Each current table uses one set-based UPSERT over its changed staged payloads. IDENTIFY_ONLY/REMOVE cannot enter the UPSERT. Functional comparison still excludes provenance, so unchanged current rows retain their origins, including separate source-config/coverage proofs.
- Vacancy REMOVE is set-based over explicit staged REMOVE rows. Company/source removals remain explicit verified old IDs, grouped within the parameter limit and ordered after vacancy changes. Permanent IDs and aliases are never removed.
- Exact stage cardinality assertions, complete chunk marker/seal, ownership/composite FKs, CAS, final head count checks and trigger-generated PUBLISHED/audit remain in the **same single `db.batch()` transaction**. No staging is committed separately. An injected missing alias inside a multi-row INSERT is caught by cardinality validation and rolls everything back.
- Git replay/hash/projection proof, full trusted ledger, Python matching, retained decisions/UNRESOLVED_PERSONAL, single-owner rejection, independent revisions, PERSONAL append/receipt/recovery all retain PR #33 behavior. No new scheduling or multi-day protocol exists.

`inspectCatalogPlan` is a read-only Node diagnostic used by the importer and boundary tests. It checks the existing overall limits plus the stricter per-statement bounds before any reservation or mutation. It does not execute caller-provided SQL. Process memory samples are diagnostic only.

## Write accounting

Compaction preserves all logical row effects. Each aggregated step carries the **number of affected rows**, not 1 per SQL statement. The conservative estimator multiplies row-touch units by `1 + PRAGMA index_list(table).length`, allows replacement effects for UPSERT, and explicitly includes existing trigger writes. Stage cleanup sums inserted row cardinalities across multi-row statements; it must not count the number of INSERT statements.

`requiredBound` is computed before admission. `reservedBound` becomes nonzero only after the shared daily reservation commits. A failed reservation is not reported as reserved allowance. As before, committed reservations are not reclaimed after failure; there is no uncertain budget release on retry.

The full baseline bound is reproducible from `writeBounds` and the per-table `writeUnits` in [MODEL_C_IMPORTER_METRICS.json](MODEL_C_IMPORTER_METRICS.json):

| Component | Conservative admission bound |
|---|---:|
| Staging, origins and chunk marker | 27,325 |
| Permanent ledger and current promotion | 39,462 |
| CAS, run/proof/revisions, seal/assertions, head/audit | 24 |
| PERSONAL append/assertions | 8 |
| Receipt/reconciliation/assertions | 18 |
| Cleanup, including indexes | 27,316 |
| Reservation bookkeeping allowance | 20 |
| **Total required** | **94,173** |

`writeUnits.rows` means bounded row-touch units: inserted/deleted rows and conservative replacement units, combined across applicable operations. It is not a measured D1 counter. For example, the trace has all 5,454 permanent vacancy inserts, 5,474 permanent alias inserts, and 10,908 stage-vacancy units (5,454 insert + 5,454 cleanup); batching does not collapse any of them to one. Index counts come from the actual unchanged D1 schema. Both the 30,000 and 60,000 ceilings remain unchanged.

Actual 3,000-identity synchronization costs, from successful `meta.rows_written` results in the single publication batch and the separate PERSONAL/cleanup batches:

| Phase | Actual writes |
|---|---:|
| Reservation | 5 |
| Staging/origins/chunk | 15,055 |
| Permanent/current promotion | 21,675 |
| CAS/checkpoint/run/proof/seal/audit | 18 |
| PERSONAL | 8 |
| Receipt/reconciliation | 4 |
| Cleanup | 6,023 |
| **Complete bootstrap** | **42,788** |
| Replay | 0 |
| Subsequent minimal delta, all phases | 36 |

Schema creation, fixture seed and reads are excluded. `staging + promotion + checkpoint` equals the existing `publication` total; those diagnostic phase counters must not be added to `publication` a second time. The broader/minimal/alias/REMOVE/unchanged/PERSONAL/V1/recovery scenarios retain separate measured costs in the JSON. The failed full-baseline batch has no actual synchronization cost to extrapolate; the test fails at admission, before any mutative batch.

## Runtime limits and memory evidence

The pinned local Miniflare/workerd D1 runtime accepts queries with 80/100 bound parameters and rejects 101. It accepts statements of 65,536/100,000 ASCII bytes and rejects 100,001. The importer stays below those boundaries: the complete baseline's largest statement has **80 parameters and 1,015 SQL bytes**. Total bound parameters across the plan are 56,810; the per-statement cap is applied independently to each query.

The runtime also executes an **8,000-statement read batch** successfully, with zero writes. This is a local batch envelope probe, not proof of an 8,000-write-query CPU/memory budget. Boundary tests retain rejection of 8,001 statements and a greater-than-8-MiB serialized plan, independently of parameter count. No app threshold is raised.

These observations match the primary [D1 limits documentation](https://developers.cloudflare.com/d1/platform/limits/) (100 parameters / 100,000 SQL bytes per individual batch statement). The same page states that a batch counts as one invocation query. Transaction rollback follows the [D1 batch contract](https://developers.cloudflare.com/d1/worker-api/d1-database/#batch), and is independently tested with missing staging data, late SQL errors and concurrent CAS here. No remote request is made by these tests.

The metrics record Node `heapUsed`/RSS snapshots at planning and before/after the read-batch probe, plus the actual V8 heap limit. These include test/runtime overhead and are neither causal per-import allocation nor a peak-memory certification. The D1 authorizer does not expose `sqlite_version()` locally; package/lockfile/runtime pins are the reproducibility source. Workerd child peak memory, production Worker memory and remote CPU remain unmeasured. No cloud readiness is inferred from local acceptance.

## Minimal next step for the remaining blocker

Further SQL compaction alone cannot remove the bounded row/index effects: the permanent ledger is still copied into indexed staging and then cleaned up. There is no authorization to exceed 60,000 or to spread current publication across transactions.

A follow-up should review the write representation, with a narrow goal of avoiding redundant staging/cleanup of immutable identity/alias data (while preserving proof-bound complete ledger validation and one atomic final CAS), or an equivalent index/storage optimization preserving every uniqueness/ownership/FK invariant. Recompute a conservative bound and measure the exact baseline before accepting such a change. This is a separate contract/schema review if the typed staging representation changes; this PR does not silently remove checks or assume that a tighter bound will fit.

If that still requires staging across days, the pending-run/revision-allocation conflict identified in PR #33 must be solved explicitly with invisible resumable staging, complete proof/chunk validation and separate daily reservation before a single final publication. No such architecture is implemented here. Until that review succeeds, the full baseline remains **NO-GO**, even though small and 3,000-identity fixtures are published correctly.

## Validation

`npm ci`: PASS. `npm run check`: **117 tests in 10 files**, TypeScript strict and build PASS. This includes 26 importer cases, two runtime limit probes and all prior V1/schema/restore/selection regressions. `node tools/model-c-import-lab.mjs` reruns importer plus runtime probes and emits synthetic-only measurements. `npm run worker:check` is dry-run only. V1 migration CLI replay is checked twice in a disposable fixture directory; no workspace/persistent database is touched. Final laboratory and CI results are recorded in the PR at its exact head. `git diff --check` must remain clean.
