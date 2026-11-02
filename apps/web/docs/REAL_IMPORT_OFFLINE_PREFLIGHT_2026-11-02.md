# Job Watch — first real data offline preflight (2026-11-02)

**Status:** `OFFLINE_PREFLIGHT_PASS`, `REMOTE_IMPORT_NO_GO`.

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
