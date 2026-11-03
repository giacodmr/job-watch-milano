# Job Watch — private remote initial bootstrap (operator runbook)

This runbook operates **only** from a trusted Mac checkout. It is not part of the
online password Worker or its public API. Cloudflare D1 migration
`0008_phased_initial_preparation.sql` has already been applied via Wrangler;
do **not** reapply it.

## Preconditions

- A fixed `main`-ancestor **collector snapshot SHA** with complete source files.
  Never silently use the historical 2 November snapshot.
- An **unchanged operator code checkout** for the full five-day run. The pinned
  projection proof hashes local `apps/web/shared` and `apps/web/tools`.
- Worker remains password-only, APP writes and service ingestion disabled.
- D1 CATALOG version 7 / 8 migrations and PERSONAL version 3 / 3 migrations;
  no HEAD, prior runs or foreign owner at first preparation.
- A separately authorized operator-only Cloudflare D1 token with **Write**
  access to exactly the intended account. Keep the token in the Mac environment,
  never in git, prompt text, console history, source files or logs.
- Account-wide Workers Free D1 write usage and headroom freshly checked for
  **the current UTC day**. Operator daily admission limit remains 30,000 write
  units, inclusive of independent v2 staging, importer reservations, retries,
  other workloads and a safety margin.
- Real D1 REST batch rollback previously verified by the operator. Do not
  repeat synthetic production writes merely to retry that completed proof.

## Operator environment (local, never committed)

Required environment variable **names**:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
JOB_WATCH_CATALOG_D1_ID
JOB_WATCH_PERSONAL_D1_ID
JOB_WATCH_PRIVATE_OWNER_ID
JOB_WATCH_INITIAL_PLAN_FILE
JOB_WATCH_IMPORT_REMOTE_GATE_B=approved
JOB_WATCH_FREE_PLAN_CONFIRMED=true
JOB_WATCH_ACCOUNT_QUOTA_VERIFIED=true
JOB_WATCH_REST_ATOMICITY_VERIFIED=true
JOB_WATCH_TODAY_WRITE_BUDGET
```

The plan file must be an **absolute path outside the repository** in a
private, user-owned directory. It is created once with mode 0600 and must be
retained securely across all days. `JOB_WATCH_TODAY_WRITE_BUDGET` must be a
positive integer no larger than 30000, updated based on live account-wide
usage and outstanding reservations. Do not treat this value as a platform
enforced quota circuit breaker.

The export and importer use the repository's Python source and a pinned
Git SHA. Set `JOB_WATCH_PYTHON` only if a non-default interpreter is needed.

## Commands

From `apps/web`, install with the existing lockfile and **do not change
dependencies or update the checkout while the run is active**.

```bash
npm run operator:bootstrap:remote -- plan <PINNED_SOURCE_SHA>
npm run operator:bootstrap:remote -- stage <PINNED_SOURCE_SHA>
npm run operator:bootstrap:remote -- prepare <PINNED_SOURCE_SHA>
npm run operator:bootstrap:remote -- publish <PINNED_SOURCE_SHA>
npm run operator:bootstrap:remote -- cleanup <PINNED_SOURCE_SHA>
```

Order and controls:

1. **plan:** single read-only pinned-source Git/Python preflight, plus local
   private plan file creation. Check projected complete ledger and source digest.
2. **stage:** creates the immutable v2 run and up to 20 verified chunks per call,
   with receipt read-back. Repeat until `STAGED_NOT_PUBLISHED`. Preserve the
   same source SHA, plan file, token scope and operator identity. Each call has
   a new short-lived runtime capability; never automatically retry an uncertain
   write.
3. **prepare:** creates one receipt-verified preparation group per call. Execute
   as many groups per UTC day as account-wide remaining budget admits. Repeat
   over days until `PREPARED`. No vacancy is visible before the final HEAD.
4. **publish:** only after ALL groups, within the final-day budget; atomic
   CATALOG HEAD publication with PERSONAL append/reconciliation and journal
   readback. The controller returns `REQUIRES_OPERATOR_RECOVERY` instead of
   blindly retrying any uncertain publication.
5. **cleanup:** on a separately budgeted day after `COMPLETED`. Requires
   `JOB_WATCH_BOOTSTRAP_RUN_ID` set to the exact verified immutable
   `ingest-v2:...` run ID. Never run cleanup before a published HEAD or a
   completed journal.

`JOB_WATCH_STAGE_CHUNKS_PER_CALL` optionally sets 1–20 stage chunks.
The run may span several days; refresh account usage, operator attestation,
quota budgets and credentials as needed before each stage or group.

## STOP conditions (readback only)

- Wrong database, missing migration 0008, unexpected owner, CATALOG HEAD change.
- Source manifest/projection or immutable packet/plan digest mismatch.
- Stage receipt conflict, incomplete trust verification, Git source drift.
- Insufficient account-wide Free headroom or stale quota attestation.
- Unexpected REST write error/unknown ACK. Inspect read-only receipts and do
  **not** resend the uncertain operation automatically.
- Any `REQUIRES_OPERATOR_RECOVERY`, incomplete reconciliation or journal
  transition failure.

The remote operator is intentionally **not** exposed as a Worker route.
No real import is authorized simply by merging this code; the locally supplied
gate and D1 token are independent execution requirements.

## Pilot acceptance

After `COMPLETED`, verify CATALOG HEAD, expected selected vacancy count,
complete identity/alias ledger, PERSONAL receipt, zero pending references,
and actual protected `/opportunita` data. Measure account-wide D1 rows
written before each following UTC day.

The November 3 snapshot preliminary counts (89 selected vacancies, 5573
identities, 5592 aliases; 110670 estimated phased write units) exclude remote
staging and other traffic. They are not promises for future collector snapshots.
