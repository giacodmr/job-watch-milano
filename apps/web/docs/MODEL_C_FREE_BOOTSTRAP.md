# PR #35 — Free one-time initial bootstrap

Base main: `e315419ee042ac0743c98564f165975618753bcf` (#34 squash). Branch `codex/model-c-free-bootstrap`. The initial application quota blocker is closed locally, with the existing staging and atomic importer unchanged. No Python, UI, V1 reader/importer, active route, binding, production workflow or remote execution is introduced.

## Local result

The exact synthetic fixture (5,454 identities, 5,474 aliases/mappings, 151 selected vacancies) is **actually PUBLISHED** on ephemeral D1 with:

- Conservative required/reserved bound: **94,173**, below the new exceptional **95,000** ceiling.
- Actual importer writes: **77,145**, including reservation, PERSONAL, publication, receipt and cleanup.
- Publication plan: **739 statements / 2,704,855 bytes**, unchanged from #34 and below 8,000 / 8 MiB.
- Exact persisted ledger digest, every ID/mapping, selective current payloads, PUBLISHED run, revisions, checkpoint, audit, FK integrity and stage cleanup verified.
- Ordinary replay after publication: **zero writes**, with one run/audit and the same content revision/origin. The newly verified projection-input digest can differ between initial-bootstrap and confirmed-ledger contexts; this does not manufacture a content revision or duplicate publication.

Actual phases are recorded in [MODEL_C_IMPORTER_METRICS.json](MODEL_C_IMPORTER_METRICS.json): reservation **6**, staging **27,325**, permanent/current promotion **38,853**, checkpoint/run/proof/CAS/audit **18**, PERSONAL **8**, receipt **4**, cleanup **10,931**, total **77,145**. Empty schema/setup is measured separately: CATALOG **187**, PERSONAL **80** writes. Those 267 setup writes are neither part of the import counter nor an upper bound for future remote schema work.

## Explicit API and restrictions

The trusted Node-only API accepts:

```ts
{
  bootstrap: 'empty-target', // or the existing verified v1 source context
  oneTimeFreeBootstrap: true,
  executionTarget: 'local-ephemeral',
  budget: { day: '<current UTC day>', availableRows: 95000 },
  // existing source repo/full commit, owner, etc.
}
```

The explicit flag must be a boolean. The existing empty-target authorization or confirmed V1 migration context is still required. Git/repository/ancestry/manifest/byte hashes/Python replay/projection proof and the complete PERSONAL context are verified before reservation. The importer recomputes the bound for the actual input; **94,173 is a fixture result, never a hardcoded allowance**.

The exception is available only before any CATALOG head exists. Both the initial Node check and an SQL guard on the extraordinary reservation reject a published head; the reservation batch also asserts revision 0 atomically. The permanent head retain trigger prevents reopening this initial window through the application. A flag supplied after publication is rejected even for an identical replay. Replay must omit the exception, and remains zero-write.

Ordinary ceilings remain **30,000**, or **60,000** with `extendedAuthorized:true`. Supplying 95,000 without the special authorization is invalid. Supplying more than 95,000 with it is also invalid. A delta can never use the exception. No caller-facing active endpoint exposes these administrative flags. `executionTarget` is a trusted local test/adapter attestation, not authentication or a way for a browser to select a connection.

## Minimal additive SQL migration

Existing 0003 tables have hard CHECK limits of 60,000. Migration **CATALOG 0004** therefore adds a small immutable `catalog_initial_bootstrap_reservations` ledger and `catalog_write_totals` view, without rebuilding, deleting or rewriting the ordinary budget tables/history. It replaces the ordinary reservation guard with the same check against the combined daily total. CATALOG schema is now 4; PERSONAL schema is unchanged at 2. Previous migration files remain immutable.

The new ledger retains attempt ID, UTC day, whole bound/ceiling, verified observed commit, manifest digest and projection digest, even if publication later fails. The SQL trigger requires no head, the current SQLite UTC day, and combined existing charges plus the new bound within the requested ceiling (at most 95,000). The ordinary guard includes extraordinary charges too. The 20-write bookkeeping allowance already covers the new reservation's actual 6 writes; the accounting is not reduced.

`catalog_write_days.charged` retains its original ordinary-only meaning. **Use `catalog_write_totals.charged` for combined application liabilities. Neither is account-wide Cloudflare consumption.** The original table CHECK ceilings remain unchanged. All reservations are append-only; no refunds, historical cleanup or quota-reset API exist.

## Errors, retries and recovery

“One-time” means the initial publication window, not permission to discard failed attempts. Each attempt reserves its entire bound. A prior failed reservation stays charged, and a retry must fit the current day's remaining allocation. Read-only admission checks avoid known-exhausted write attempts; SQL repeats the check atomically for races. A successful head closes the exception permanently for that database.

The tests inject a late publication SQL error, verify complete catalog rollback (no identities/current/origins/revisions/run/head/audit/stage publication), retain the committed reservation, reject a retry with insufficient remaining allocation, and allow a newly authorized attempt only while the combined total fits. PERSONAL append can remain durable/PENDING, following the existing no-distributed-transaction contract. No fact/event is deleted or overwritten; the existing historical V1/UNRESOLVED_PERSONAL regression also runs under this exceptional first import.

For the full fixture, reserving 94,173 leaves only 827 of the exceptional 95,000 application allocation. A failed large attempt generally cannot be retried that UTC day. **No fallback increases the cap or releases the previous reservation.** After a published large bootstrap, the ordinary 30,000/60,000 daily guards also see its 94,173 liability and refuse new mutative work that day. If receipt/cleanup fails after publication, preserve the confirmed catalog and PENDING work; an ordinary recovery may require the next UTC quota window and freshly reviewed allocation. Existing source/receipt/cleanup idempotency is retained. Retrying an entire rolled-back publication on a later day is a new atomic attempt, not multi-day staging; all earlier attempt history remains recorded. No scheduler or automatic midnight retry is added.

## Read-only preflight and future remote safety

`preflightOnly:true` with the exceptional flag performs the real Git/context validation and planning, returning `PREFLIGHT`, provenance digests, plan dimensions, complete `requiredBound`, and existing combined local reservations, **without writes**. It always returns `remoteExecutionAuthorized:false` and initially `QUOTA_VERIFICATION_REQUIRED`.

`assessFreeBootstrapRemoteQuota()` is a pure assessment over that preflight plus trusted external evidence. It requires:

- Verified Workers Free account plan and full-account D1 usage from **00:00 UTC of the current day**, covering every database without incomplete/unreliable results.
- Fresh collection/coverage timestamps (within five minutes; this is a conservative application policy, not an analytics SLA), plus an explicit upper bound on unobserved/lagged writes.
- Explicit upper bounds for schema/setup and other workloads, and an explicit safety margin. Missing values do not silently become zero.
- Existing application reservation liabilities, added conservatively to observed account usage rather than substituted for it. This may double-count already billed writes and intentionally errs toward rejection.
- Independently verified remote batch/parameter/body/CPU/memory conditions, recovery plan and quiesced competing writers.

The reviewed upper bound is:

`observed account writes + unobserved-write upper bound + prior application reservation liabilities + import bound + setup upper bound + other-workload upper bound + safety margin <= 100,000`.

The application allocation separately requires `prior current-day liabilities + import bound <= 95,000`. Bad/stale/partial/unavailable account evidence returns **QUOTA_VERIFICATION_REQUIRED**. Exhausted free quota returns `FREE_QUOTA_INSUFFICIENT`; missing operational checks return `REMOTE_ACTIVATION_REVIEW_REQUIRED`. Even a complete, sufficiently funded assessment returns only **READY_FOR_MANUAL_REMOTE_REVIEW**, never an execution permit. This helper does not fetch, authenticate or certify caller-supplied analytics: evidence must come from a trusted service/operator, not a browser or an asserted local counter.

There is no Cloudflare client, credential, live account query, remote binding or bootstrap command in this PR. An attempted exceptional import without the explicit local-ephemeral target returns **QUOTA_VERIFICATION_REQUIRED**; remote execution remains disabled even if somebody separately constructs a positive assessment. Future activation needs a separately authorized, verified transport and actual account-wide evidence. There is no Paid fallback.

Primary sources: [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/) documents the 100,000 Free daily writes, 00:00 UTC reset and the need to count DDL/index effects. [D1 analytics](https://developers.cloudflare.com/d1/observability/metrics-analytics/) describes account/per-database metrics and GraphQL access. A last-24-hours database chart or local reservation sum alone does not prove complete current-UTC-day account usage.

## Validation and readiness

Local `npm run check`: **124 tests / 11 files PASS**, TypeScript strict/build PASS. Importer cases include actual full bootstrap, preflight, absent authorization, insufficient/oversized budget, wrong/absent execution target, missing proof, exception-after-head rejection, replay, failed-attempt liabilities, rollback and prior #34 regressions. Four pure quota assessment tests cover coverage/reliability/freshness, setup/workload/margin accounting, local liabilities, insufficient quota and independent remote/recovery checks.

The synthetic-only laboratory reruns importer, runtime and quota tests and emits actual phase costs. Worker validation is dry-run only. V1 migration CLI is checked twice in a disposable directory, then removed; only ephemeral D1 receives Model C migrations. CI and final head are recorded in the PR.

**Ready for independent review and local synthetic bootstrap. Remote activation remains NO-GO until account-wide quota, real-input bound, setup/workloads/margin, batch/resource limits and recovery conditions are verified and separately authorized.** No merge, deploy, provisioning, real bootstrap, persistent database write, history deletion or staging optimization is performed.
