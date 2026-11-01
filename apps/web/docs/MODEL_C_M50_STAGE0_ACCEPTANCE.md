# JOB WATCH — M50 Stage 0 local acceptance and pilot decision

**Freeze:** only AC04–AC07 inherited from M49. No new ATS, UI, authentication provider, database schema, Worker route or scoring change.

**Starting baseline:** M49 squash `37cc76b55f27ee36ea330c9f78876eaaa420f19f`; the branch must be compared to actual `main` before merge. This page does not amend M49's original acceptance.

## Implementation boundaries

- `tools/model-c-m50-trusted-controller.ts` is a **detached Node-only local operator controller**. It accepts pinned Git source, a staged v2 run, a precomputed trusted plan, CATALOG/PERSONAL D1 bindings and an owner already trusted by the operator, **not** a JWT or an HTTP request.
- It runs the existing M47 independent Git/Python replay + proof/manifest/ledger selection and checks the staged receipts, plans and CAS preconditions via the existing importer. It then executes the existing importer locally. The prior CATALOG atomic batch and journal, PERSONAL append and reconciliation remain unchanged.
- The controller requires distinct databases, a pinned Git commit and an internal daily write ceiling at most 30,000. It cannot flip a Cloudflare runtime gate. Its only execution target is `local-ephemeral`.
- Unknown write acknowledgements return `REQUIRES_OPERATOR_RECOVERY`, accompanied by **read-only** durable journal and PERSONAL receipt observations if available. They are never silently treated as a success or retried. A subsequent human-authorized invocation independently revalidates Git and the immutable run before executing recovery.
- The M49 shared CATALOG reservation trigger serializes importer-shaped and PERSONAL APP reservations with v2 ingestion reservations. The controller's existing importer reserves a conservative all-phase bound before mutating PERSONAL/CATALOG. This is **not** measured account-wide Cloudflare spending.

## Evidence / AC acceptance

| AC | Local acceptance requirement | Remote gap |
|---|---|---|
| AC04 trusted publisher | Node-only Git/Python provenance, staged v2 proof, immutable trusted plan, CATALOG atomic CAS+journal and full rollback; no service-to-publisher promotion route | There is **no deployable privileged remote D1 transport** yet. Must be designed and checked under Gate B using independently restricted operator capability. |
| AC05 PERSONAL | Single trusted owner, PERSONAL append, immutable APP event preference and receipt-based reconciliation after CATALOG publication; existing 30-cycle integration regression retained | Real separate D1 databases and remote consistency unverified. |
| AC06 recovery | Simulate lost acknowledgement after actual local CATALOG commit, read-only inspection, explicit operator recovery and immutable replay; existing persistence/restart regression retained | Remote cold restart, acknowledgement loss and production receipts unverified. |
| AC07 quota | Simultaneous importer-shaped/APP reservations through shared transactional CATALOG ledger, refusal at the write ceiling, deny unverified budget, M49 staging reservations; no paid fallback | Cannot attest actual Free plan, other-account consumers, CPU, reads, storage or remote migration cost without Cloudflare account authorization. |

**Do not equate a green CI with live pilot readiness.** Local completeness is a necessary but not sufficient prerequisite. In particular AC04 remains **PARTIAL for remote publication**; no path exists today that lets this Node controller mutate remote D1 in a verified atomic, least-privilege manner. Cloudflare REST query supports batches but does not by itself prove the required parity of typed numeric/null bindings, transactions and receipts with the Worker D1 binding. A generic remote SQL proxy or staging JWT promotion is prohibited.

## GO / NO-GO semantics

- **Local Stage 0 acceptance:** GO only if every targeted regression, 295+ Vitest tests, browser tests, typecheck, build, two D1 local migrations, standard/private Worker dry-runs, private preflight, and both final PR CI are successful, with zero new security bypass. Local PASS evidence does not become remote PASS.
- **Pilot authorization request:** only after a deployable, independently authorized **remote** trusted publication/reconciliation path is implemented and verified against local compatibility fixtures, or a narrowly scoped plan for validating it remotely is separately approved **without writes**. Until that exists: **NO-GO for production data ingestion or APP writes**.
- **Remote Stage 1 infrastructure:** never started from this PR. The first permitted Cloudflare authorization can be limited to *read-only* account verification and an isolated private UI pilot, with distinct subsequent permissions for D1/ingestion/writes.

## Stop conditions

`GATE_B=CLOSED`, `CLOUD_DEPLOYED=NO`, `REMOTE_WRITES=NO`, `PAID_RESOURCES=NO`, authorized spend **€0/month**. Unknown account quota/plan, unauthorized hostname, missing typed D1 batch equivalence, identity confusion, failed rollback or unverifiable outcome require NO-GO. No real IDs, credentials or token material should be stored in source control.

## Evidence log

Populate with final HEAD, CI workflow URLs, counts and explicit AC PASS/PARTIAL/FAIL. Avoid reporting completed remote semantics unless observed on the actual account after separate user authorization.
