# JOB WATCH — M50 Stage 0 local acceptance and pilot decision

**Freeze:** only AC04–AC07 inherited from M49. No new ATS, UI, authentication provider, database schema, Worker route or scoring change.

**Starting baseline:** M49 squash `37cc76b55f27ee36ea330c9f78876eaaa420f19f`; the branch must be compared to actual `main` before merge. This page does not amend M49's original acceptance.

## Implementation boundaries

- `tools/model-c-m50-trusted-controller.ts` is a **detached Node-only local operator controller**. It accepts pinned Git source, a staged v2 run, a precomputed trusted plan, CATALOG/PERSONAL D1 bindings and an owner already trusted by the operator, **not** a JWT or an HTTP request.
- It runs the existing M47 independent Git/Python replay + proof/manifest/ledger selection and checks the staged receipts, plans and CAS preconditions via the existing importer. It then executes the existing importer locally. The prior CATALOG atomic batch and journal, PERSONAL append and reconciliation remain unchanged.
- The controller requires distinct databases, a pinned Git commit and an internal daily write ceiling at most 30,000. Default is `local-ephemeral`. An explicit `publishM50WithRemoteOperator` entrypoint additionally requires an exact runtime capability bound to two independently created operator-owned REST D1 adapters; a staging JWT or forged capability fails before querying. The REST factory requires separate Gate B approval, Free quota attestation, a bounded **same-day remaining-write allowance** and a short-lived runtime capability. The importer rejects budgets exceeding that attested amount. All approvals/credentials are absent in the repository.
- Unknown write acknowledgements return `REQUIRES_OPERATOR_RECOVERY`, accompanied by **read-only** durable journal and PERSONAL receipt observations if available. They are never silently treated as a success or retried. A subsequent human-authorized invocation independently revalidates Git and the immutable run before executing recovery.
- The M49 shared CATALOG reservation trigger serializes importer-shaped and PERSONAL APP reservations with v2 ingestion reservations. The controller's existing importer reserves a conservative all-phase bound before mutating PERSONAL/CATALOG. This is **not** measured account-wide Cloudflare spending.

## Evidence / AC acceptance

| AC | Local acceptance requirement | Remote gap |
|---|---|---|
| AC04 trusted publisher | Node-only Git/Python provenance, staged v2 proof, immutable trusted plan, CATALOG CAS+journal and rollback; operator-only REST D1 adapter encodes typed values explicitly; complete trusted publication has a real-D1 simulated-REST test. No public SQL proxy or service-to-publisher promotion route. | **Cloudflare-only**: remote REST `batch` rollback/typed-value parity, API token resource privileges, and real quota attestation must be observed separately. No remote calls have occurred. |
| AC05 PERSONAL | Single trusted owner, PERSONAL append, immutable APP event preference and receipt-based reconciliation after CATALOG publication; existing 30-cycle integration regression retained | Real separate D1 databases and remote consistency unverified. |
| AC06 recovery | Simulate lost acknowledgement after actual local CATALOG commit, read-only inspection, explicit operator recovery and immutable replay; existing persistence/restart regression retained | Remote cold restart, acknowledgement loss and production receipts unverified. |
| AC07 quota | Simultaneous importer-shaped/APP reservations through shared transactional CATALOG ledger, refusal at the write ceiling, deny unverified budget, M49 staging reservations; no paid fallback | Cannot attest actual Free plan, other-account consumers, CPU, reads, storage or remote migration cost without Cloudflare account authorization. |

**Do not equate a green CI with live pilot readiness.** The detached Node adapter now targets Cloudflare's **official D1 REST** API, never an application route. Cloudflare documents a `{batch:[{sql,params}]}` REST envelope but specifies `params:string[]`. The adapter rewrites trusted internal SQL placeholders for number (CAST of a REST-bound string) and null (literal SQL NULL), refuses multiple statements and unsupported values, sends every D1 batch in a **single** REST request and fails closed on incomplete/malformed responses. Local tests execute that envelope against actual Miniflare D1. The operator API token must be independently created; *account-level D1 Write permission can exceed the intended two-database boundary*, and the exact token scope must be checked by the user before any real connection.

The Cloudflare REST service's transactional rollback, prepared-type parity and billing behavior **are NOT independently confirmed** by local simulation. These remain Cloudflare-only Gate B tests, so AC04 is PASS **local compatibility** but not live certified; generic public SQL proxies and service JWT promotions remain prohibited.

**No network/provisioning during M50 Stage 0.** The adapter factory merely prepares a client and does not contact Cloudflare. In this branch all tests use an injected synthetic transport. Real invocation is denied unless Gate B, Free account check, verified operator quota amount/day, distinct UUIDs and valid short-lived attestation are explicitly provided at runtime. Initial remote bootstrap requiring exceptional 95k writes remains disallowed by the importer.

## GO / NO-GO semantics

- **Local Stage 0 acceptance:** GO only if every targeted regression, 295+ Vitest tests, browser tests, typecheck, build, two D1 local migrations, standard/private Worker dry-runs, private preflight, and both final PR CI are successful, with zero new security bypass. Local PASS evidence does not become remote PASS.
- **Pilot authorization request:** with local PASS, separately authorize **read-only** Cloudflare account/plan/token-scope inspection first. Real REST rollback/typed semantics must then be verified with an explicitly authorized isolated disposable synthetic D1 after capacity/preflight review and only if €0 risk is demonstrated. Until Cloudflare-specific tests pass: **NO-GO for production data ingestion or APP writes**.
- **Remote Stage 1 infrastructure:** never started from this PR. The first permitted Cloudflare authorization can be limited to *read-only* account verification and an isolated private UI pilot, with distinct subsequent permissions for D1/ingestion/writes.

## Stop conditions

`GATE_B=CLOSED`, `CLOUD_DEPLOYED=NO`, `REMOTE_WRITES=NO`, `PAID_RESOURCES=NO`, authorized spend **€0/month**. Unknown account quota/plan, unauthorized hostname, missing typed D1 batch equivalence, identity confusion, failed rollback or unverifiable outcome require NO-GO. No real IDs, credentials or token material should be stored in source control.

## Evidence log

Final-HEAD CI evidence and AC local status will be recorded in PR #51 after checks finish. M50 local tests never connect to the remote Cloudflare API. Avoid claiming a live service plan, resource-scoped credentials, or remotely verified transaction semantics.
