# Job Watch Model C — Milestone #45 offline bootstrap and transport gates

**Status (2026-10-31): IMPLEMENTED on PR branch; CLOUD_VERIFIED: NO; DEPLOYED: NO; REMOTE BOOTSTRAP: BLOCKED FOR ACTIVATION.**

This milestone adds no Cloudflare client, remote transport credential, D1 remote binding,
ingestion endpoint, scheduling, Worker mutation or change to the private JWT boundary.

## Chain of custody

```
verified pinned Git SHA, origin/main ancestry
  → approved isolated Python exporter and allowlisted manifest
  → verified proof and full identity ledger selection
  → importModelC(preflightOnly:true, executionTarget:'remote')
  → conservative CATALOG/PERSONAL write estimates, without remote writes
  → separately measured isolated local schema migrations
  → sanitized planning report; remote quota and semantics remain unknown
  × explicit DENY: no authorized remote transport
```

`npm run preflight:bootstrap:local -- --commit <40-char SHA>` (from `apps/web`).
Use only a complete SHA which is an ancestor of the checked-out `origin/main`
in the authorized `giacodmr/job-watch-milano` repository.
No implicit network fetch, no collectors and no modification of Git source files.

The command requires `JOB_WATCH_PRIVATE_OWNER_ID` via a *private environment
variable* for a genuine owner-context calculation; do not put the value on
the command line or in CI logs. If it is absent, output is explicitly
`REAL_DATA_PREFLIGHT_NOT_EXECUTED`. An environment value alone does not
prove its owner mapping is cloud-verified. Never substitute a synthetic owner
to claim a real import. Invalid SHA, wrong origin, tampered files and
unapproved ancestry are rejected by `verifyGitProjection`.

The CLI creates CATALOG and PERSONAL only as **ephemeral Miniflare D1** targets,
applies existing migration files, passes the pinned SHA into the already
verified importer `preflightOnly:true`, computes signed provenance/manifest
proof and write estimates, then disposes both databases.
No CATALOG/PERSONAL application data, decision texts, emails, owner ID, SQL
or token are output. Print only aggregated counts and digests. The output
has separate observed *local* migration write counts and deliberately
reports `remoteMigrationUpperBound:null`: do not treat measured local
migration writes as a remote-account-certified upper bound.

The CLI is deliberately restricted to an **initial empty-target** preflight;
it does not independently approve incremental/replay remote execution.
The existing local importer tests cover replay and incremental behavior.
A future reviewed transport must reprove these on the real remote target.

## Offline decision contracts

- `tools/model-c-remote-plan.ts` creates a deterministic `job-watch-remote-plan/1`
  report with no owner or raw SQL, source digest, per-DB schema budget,
  import bound, ordered dependencies and a report digest. It **requires**
  explicit migration upper bounds at least as large as the independently
  measured local schema writes; no plan is valid with missing costs.
- `tools/model-c-free-bootstrap.ts` remains the sole conservative
  account-wide D1 quota admission rule (100,000 Free writes/day).
  `evaluateRemoteQuotaForPlan` rejects mismatched provenance, altered
  import bounds and undercounted migrations. Incomplete, stale, sampled
  or unknown Cloudflare account telemetry fails closed. A positive verdict
  is `READY_FOR_MANUAL_REMOTE_REVIEW`, **not** an execution capability.
- `tools/model-c-transport-readiness.ts` checks explicit SQL count,
  UTF-8 byte and binding limits offline, verifies the DB schema scope,
  and can submit a `D1Database.batch` **only** if target is
  `local-ephemeral`. `remote` throws before touching any binding.
  Responses with uncertain delivery require a fresh checkpoint and receipt
  inspection; never blindly retry.
- Both CATALOG and PERSONAL have individual transaction boundaries.
  **There is no cross-D1 atomic transaction.** PERSONAL append, CATALOG
  publication, PERSONAL reconciliation and joint checkpoint validation
  must remain distinct phases, with no false `CONFIRMED` after a partial
  failure. Staged CATALOG data must not be visible before its head CAS.
  The current importer implements this choreography *locally* and has
  fault-injection tests; it must not be assumed to transfer automatically
  to a remote REST transport.

## Current coverage and gaps

Existing `model-c-importer.test.ts`, `model-c-free-bootstrap.test.ts`
and `model-c-private-access.test.ts` exercise genuine ephemeral D1 for:
initial import, replay, delta, bad source, stale ancestry, PERSONAL ledger
preservation, transaction rollback, write ceilings, CAS and isolation.
New `model-c-remote-readiness.test.ts` proves per-DB D1 rollback,
scope enforcement, remote-deny gate, source-bound quota admission,
unknown-result retry classification, deterministic plan, schema limits
and ownerless CLI refusal. A mock or Miniflare passing does not mean
Cloudflare remote behavior is verified.

**Unresolved before Gate B:**
1. Verify real Cloudflare account, plan, D1 inventory and Free usage/limits
   (account-wide UTC writes/reads plus uncertain concurrent writes).
2. Verify real owner via an authenticated interactive Access subject;
   account secrets and identifiers must remain outside public Git.
3. Secure a dedicated hostname/Access first; verify no bypass via
   workers.dev, preview, alternate routes and assets.
4. Provide an approved, independently tested remote transport preserving
   SQLite batch atomicity/CAS and idempotent recovery; neither a raw REST
   query batch nor an ad-hoc Wrangler SQL file is accepted without proof.
5. Create separate CATALOG/PERSONAL remote schema budgets including index,
   migrations, other workloads, reservations, retry and margin.
6. Confirm Time Travel/bookmark/recovery policy and *non-destructive*
   rollback for each physical D1, including cross-DB version consistency.
7. Run canary/smoke only under separately approved Gate B; verify 401/403,
   protected assets, consistent read-only views, owner segregation and
   cost/CPU/row-read limits.

Cloudflare documented 2026 limits (not evidence of this account):
[D1 limits](https://developers.cloudflare.com/d1/platform/limits/),
[D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/),
[D1 binding transaction semantics](https://developers.cloudflare.com/d1/worker-api/d1-database/),
[D1 write-timeout ambiguity](https://developers.cloudflare.com/d1/observability/debug-d1/),
[Workers Free limits](https://developers.cloudflare.com/workers/platform/limits/).
D1 Free: 100,000 written rows/day, 5 million read rows/day, 10 databases,
500 MB per database, 7-day Time Travel. Worker Free: 100,000 requests/day,
10 ms CPU/invocation. D1 max SQL statement length 100 KB, 100 bound
parameters, 30-second per-query limit. These are Cloudflare published
limits; code deliberately applies tighter offline review ceilings.

## Release status

`LOCAL_PLAN_VALID` means the local preflight contract passed. It never
means `CLOUD_VERIFIED`. `REMOTE_SEMANTICS_UNVERIFIED`,
`REMOTE_QUOTA_UNVERIFIED` and `REMOTE_EXECUTION_NOT_AUTHORIZED`
remain mandatory blockers.

**Decision: GATE A IMPLEMENTED — REMOTE BOOTSTRAP BLOCKED FOR ACTIVATION.**
No remote D1 writes, migrations, Worker deployment, Access policy, DNS,
GitHub→D1 sync, APP→GitHub sync or Paid plan changes are authorized.
