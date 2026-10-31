# Model C — Private deployment preparation (NOT an authorization to deploy)

**Status: UNPROVISIONED / NO DEPLOY IN #43.** `wrangler.private.template.jsonc` intentionally omits Cloudflare identifiers, Access application settings and D1 database bindings. It cannot be used as a functional private environment until an explicit, separately reviewed #44 provisioning mandate.

## #44 prerequisites / account preflight

1. Verify ownership and account plan, billing stop controls, actual Workers/D1/Access Free quotas and whether a paid plan or custom domain would be necessary. Do not trigger an upgrade.
2. Create a dedicated, verified HTTPS hostname and Cloudflare Access self-hosted application with the approved single user as the ONLY interactive principal. Audit service-auth rules and deny access through alternative domains.
3. Obtain exact Access team issuer, application audience, stable subject identifier and separately provisioned opaque PERSONAL owner id. Set `PRIVATE_HOSTNAME`, `PRIVATE_ACCESS_ISSUER`, `PRIVATE_ACCESS_AUD`, `PRIVATE_ALLOWED_SUB` and `PRIVATE_OWNER_ID` through authorized server-side environment bindings, never the browser, repository or CI logs. Verify the subject is interactive rather than a service token. Do not use an email as owner id.
4. Inspect `workers.dev`, version URLs, previews, custom domains and route precedence. Disable public alternatives or establish equally strong Access policies. Set `workers_dev:false`, `preview_urls:false`, `assets.run_worker_first:true`.
5. Create **separate** CATALOG and PERSONAL D1 databases only with explicit authorization. Verify their names and IDs, apply versioned migrations with integrity and no rewriting of existing ledger, and establish backup / 7-day Time Travel constraints. Do not use the local synthetic V1 DB as PERSONAL.
6. Define a one-time owner provisioning and audited binding protocol that does not invent imported GitHub provenance. If the owner has no imported PERSONAL head, personal endpoints must stay closed. Do not copy synthetic fixture identities.
7. Calculate initial import writes from a pinned GitHub commit and enforce the account-wide D1 Free quota, including existing jobs and indexes. The local importer is not an authorized remote ingestion endpoint; plan a separate secure Service Auth path before syncing.
8. Conduct a zero-secret dry-run, review generated bundle and all routes, then secure staging smoke tests: unauthenticated HTML/JS/API denied; wrong host denied; a verified user sees only its owner; no remote POST works. Record minimal, redacted responses and CPU/rows counters.
9. Define immediate rollback: disable Access app exposure / Worker route, revert known deploy version and restore/roll back D1 from a verified checkpoint. Never allow rollback to reveal unauthenticated assets or destroy APP event history.
10. Obtain an explicit deployment approval. Do not add deploy to existing GitHub CI. Keep PERSONAL remote writes and GitHub/Python reverse sync separately disabled.

## Required final acceptance for #44

Only after live Access/domain/bindings/owner mapping and quota checks, plus independent authenticated and unauthenticated smoke tests, can the private service be reported live. This file records pending dependencies; #43 never performed cloud setup, migration, deploy or remote write.

---

## Milestone #44 — Gate A implementation and activation decision (31 October 2026)

**State: IMPLEMENTED (on #44 branch) / CLOUD_VERIFIED: NO / DEPLOYED: NO / BLOCKED FOR ACTIVATION.**
The repository is public. Never commit Cloudflare account identifiers, D1 database UUIDs,
Access identities, real PERSONAL owner IDs, environment files, JWTs or operational evidence
that could disclose personal activity.

### Actual evidence and dependency map

* Base `main` at audit: `3e3f99f40d0523479e51fb8a978ce0fd08892985`. Preserve any subsequent main advances.
* Historical PRs #8, #29 and #30 are open; none is a source of deploy authority or
  merged into this work. #43 is already on main, not recreated.
* The linked tools expose GitHub repository read/write/CI, **not an authenticated Cloudflare
  account inventory or Cloudflare D1/Access administration connection**. No trustworthy
  account ID, domain, Workers Free plan, Access plan, D1 utilization, available databases,
  roles, alternate Worker hostnames, remote bookmarks or live access token claims could be
  inspected. Unknown is **not** an assumed zero.
* Dependency order: account identity/plan/permissions → controlled zone/approved exact
  hostname → Access application + verified interactive user/subject/AUD/issuer →
  two genuinely distinct D1 targets with verified versions/ownership →
  exact pinned Git/Python selection + account-wide UTC quota evidence →
  verified remote atomic transport and recovery → read-only Worker config →
  protection-first route activation → live unauthenticated/authenticated tests.
* No real owner provisioning, CATALOG/PERSONAL remote migration, D1 write, Access app,
  zone, DNS, Worker activation, CI deploy workflow or remote mutation was performed.

### Executable, repository-only preflight

From `apps/web`, run `npm run preflight:private` (also checked by
`Web foundation`). The command parses the committed local and private Wrangler
configurations, confirms no remote bindings/routes/account IDs/identity variables were
included in the private template, checks Worker-first SPA asset protection and disables
public Worker URLs. It inventories **CATALOG v4** (four migrations) and **PERSONAL v3**
(three migrations), calculating SHA-256 of each SQL source. Historical migration SQL
must not be rewritten. The command makes **no network requests and no writes**, reads no
credentials, does not claim the D1 database or actual account was verified, and always
reports `BLOCKED_FOR_ACTIVATION` with external blockers until separate live evidence
and Gate B exist. Its `PASSED` only describes repository invariants.

Additional regression changes: every private method is authenticated before method
policy, including rejected POST/OPTIONS; remote importer explicitly rejects a mutating
`executionTarget:'remote'` on normal deltas as well as exceptional bootstrap.
The authenticated Opportunity composite reader may return a verified CATALOG page with
`personalRevision:null` and null PERSONAL overlay when the configured owner's imported
PERSONAL head is absent. **Only** `PERSONAL_CONTEXT_UNAVAILABLE` is eligible; other
errors (wrong scope, schema mismatch, authorization, D1 faults, changing checkpoints)
still fail closed. Candidature APIs remain unavailable without a verified owner context,
not an invented empty register. The UI distinguishes that from legitimate zero matches.
No remote POST is enabled; existing UI capabilities remain server-authoritative.

### Account and hostname preflight — PENDING, read-only Gate A

Before submitting any proposed Gate B operations, collect securely through the normal
Cloudflare account connection/dashboard (not a pasted API token):

1. Account, permissions, actual Workers and Zero Trust plans, billing state and
   whether creating two D1 DBs and one Access app will introduce charges.
2. All owned Cloudflare zones, hostname availability and exact proposed hostname.
   Obtain **specific** user approval for the hostname. `workers.dev` is not accepted
   by the private JWT/config validator; do not weaken the validator.
3. Existing Workers, routes/custom domains, Worker-level/account-level Access rules,
   preview/version URLs and bypass precedence. The selected hostname must have no
   alternate public path. Prefer a single Worker Custom Domain; do not add origin DNS
   placeholders. The hostname must have a valid certificate.
4. D1 database inventory, Free database count (max 10), per-database size (max
   500 MB), total Free storage (5 GB), all workloads, index/migration costs, and
   account-wide rows read/written since **00:00 UTC**, including unsettled usage and
   a bound on analytics delay. Never derive quota from local ledgers alone.
5. Access application self-hosted over the **entire exact hostname**, single
   interactive principal, no Everyone/service token/bypass. Compare application
   AUD, team issuer, observed stable `sub`, token `type` and service-token
   indicators against the existing strict validator using a real redacted
   signed-claim verification, **without logging or committing token bytes**.
   Subject and opaque PERSONAL owner mapping are configured only on the server.

Cloudflare documentation (last reviewed 31 Oct 2026):
[Worker Access](https://developers.cloudflare.com/workers/configuration/cloudflare-access/),
[Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/),
[D1 limits](https://developers.cloudflare.com/d1/platform/limits/),
[D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/),
[Workers Free](https://developers.cloudflare.com/workers/platform/pricing/).
Published limits are **not proof of the actual account's entitlements or remaining quota**.

### First real data bootstrap — NO-GO until a verified transport exists

The existing importer performs pinned Git origin and ancestry validation, manifest
hashing, approved Python projection replay, full identity selection, staging plan,
atomic CATALOG publication, independent PERSONAL append/receipt, replay/recovery and
local reservation accounting. Its `preflightOnly:true` path may be used against an
isolated **local ephemeral D1** to calculate a real plan for a fixed, authentic Git
commit and a verified real PERSONAL context. Do not copy synthetic owner data.

The known **synthetic historical** baseline is 5,454 identities / 5,474 mappings /
151 selected current vacancies, 739 publication statements, 2,704,855 serialized
bytes, 94,173 conservative write bound, 77,145 actual importer writes and
187+80 local setup writes. These numbers do **not** describe the current real
repository, remote D1 usage or authenticated real owner. No real commit preflight,
current selection, actual remote migration cost, account-wide D1 counters or live
performance measurement is available in this milestone.

For any candidate initial snapshot, separately prove both:

```
account-wide observed UTC writes
+ bounded unobserved writes
+ outstanding application reservations
+ setup and migration upper bound
+ computed bootstrap upper bound
+ concurrent workload upper bound
+ safety margin <= verified account daily Free ceiling
```

and

```
existing application liabilities + bootstrap bound <= authorized application ceiling
```

Reuse `assessFreeBootstrapRemoteQuota` for the conservative admission calculation;
a positive result is `READY_FOR_MANUAL_REMOTE_REVIEW`, **never** permission to
execute. Inspect state of both target databases, migration hashes, schema scopes,
provenance, owner mapping, batch/statement limits, CPU/memory budget, replay and
rollback. The existing Node importer has no verified remote transactional transport.
Do not upload its generated SQL through an ad-hoc Wrangler command, expose an
ingestion endpoint, split an atomic publication, or substitute a remote V1 database.

The historical 94,173 bound + 267 measured local setup writes + a 5,000-row margin
already equals **99,440 rows**, before any account usage or other workloads.
This is an illustration of limited headroom, not an actual remote admission estimate.

### Safe Gate B plan (requires separate explicit approval)

Proposed minimal inventory, subject to verified account plan/capacity and hostname:
one exact self-hosted Access application/policy, one approved Custom Domain and
certificate, one private Worker (frontend and API), two new distinct D1 databases
(CATALOG and PERSONAL), five server-side private configuration values, and zero
automatic CI deployments, cron schedules, Paid subscriptions or external services.
The final names, binding UUIDs, zone ownership, location/EU jurisdiction availability,
permissions and any potential charge must be reviewed before approval. Real D1 UUIDs
and real subject/owner identifiers are **not** to be stored in this repository.

Protection-first run order, **only** after Gate B: verify target hostname cannot
serve public assets; create/verify scoped Access and test no bypass; create isolated
D1 targets; verify empty scopes and migration digests; capture Time Travel bookmarks
and safe schema snapshots; migrate in verified order; preprovision owner without
fabricating history; execute separately authorized remote bootstrap only with
proven atomic/idempotent transport and quota; configure protected private Worker
and Custom Domain; activate the route only when denial tests already pass.
If protections cannot be established before routing, STOP.

### Smoke tests and observable evidence — NOT RUN REMOTELY

Record only sanitized outcome codes and counts, never credentials/identity/activity.
Unauthenticated `/`, `/candidature`, `/opportunita`, JS/CSS, all
CATALOG/PERSONAL API, V1, ingestion, unknown paths and alternate hosts must be
blocked by Access before app execution. A valid allowed subject must see the SPA,
CATALOG and verified PERSONAL; an absent PERSONAL head must be explicitly
unavailable, while CATALOG remains consultable. A second signed subject and a
service token must be denied; POST decision/SAVED and unexpected Origin must be
denied. Verify login/logout, response caching, CSP, actual JWT claim shape,
Worker CPU (including Worker-first static assets), cold JWKS, requests, D1 read
and write metrics, snapshot digest, revision consistency, private route aliases
and 401/403/409/503 handling. No credential or personal payload in public CI/logs.

### Recovery, rollback, and free-tier risk

Cloudflare currently documents Free D1 limits of 100,000 rows written/day,
5 million read/day, ten databases, 500 MB per database, 5 GB total account storage
and seven days of Time Travel; Workers Free advertises 100,000 requests/day and
10 ms CPU per invocation. A per-asset RSA verification makes that CPU bound an
important unverified risk. Requests and database usage are account-wide and the
Free D1 write allowance resets at 00:00 UTC; no retry, upgrade or next-day
automation is authorized.

[D1 Time Travel](https://developers.cloudflare.com/d1/reference/time-travel/) is
available for eligible production-backend databases, but a restore **destructively
overwrites live state**. Prior to any remote mutation, obtain and verify bookmarks
for both databases, note schema versions and validated export options, and write
a recovery plan that retains every PERSONAL APP/GitHub event, receipt and
reservation. Do not treat the bounded synthetic backup helper as production
backup. Quiesce writers before any potential restore, and avoid independent
cross-D1 restores that manufacture an inconsistent catalog/personal checkpoint.

The private API recognizes Cloudflare's documented Free D1 daily row
read/write quota error and returns only `cloudflare_quota_exceeded` (HTTP 503).
The React reader shows a specific quota-limited state rather than a false empty
inventory or a generic database outage. This is a local contract test, **not** an
observed Cloudflare outage. No automatic paid upgrade or retry is attempted.
Cloudflare's [September 1, 2026 enforcement notice](https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/)
confirms query failures until midnight UTC without deleting stored records.

Application rollback must disable the protected route (or return fail-closed
503), preserve the Access application and both D1 ledgers, select a known prior
private Worker deployment, and re-run protected smoke tests. Never expose the
local Worker or lift Access protection as a rollback method.

### Activation decision

* **IMPLEMENTED:** remote-target import denial, JWT-first method policy,
  catalog-without-personal fallback (authenticated reads only), corrected UI
  empty/unprovisioned states, repository-only preflight and regression tests.
* **TESTED_LOCALLY:** CI/unit/browser/dry-run evidence is required on the final
  PR commit; do not claim green until the checks actually complete.
* **CLOUD_VERIFIED:** no — no connected/verified account resource inventory.
* **DEPLOYED:** no — no approved Gate B, hostname, Access, D1 or Worker deployment.
* **BLOCKED:** real hostname approval, cloud account/Free quota and Access evidence,
  real interactive token/owner, actual pinned real-source/bootstrap plan,
  safe remote transaction transport and recovery, and explicit Gate B authorization.

**Decision:** `DEPLOYMENT BLOCKED — REMOTE BOOTSTRAP NOT READY`.
A green PR is code readiness only, not a live service. #45 may consider remote
PERSONAL writes **only after** a secured, verified private environment exists,
with CSRF, per-principal authorization, D1 CAS/idempotency, revocation, quota,
retries and recovery independently proved; APP ↔ GitHub bidirectional sync
remains a separate milestone.

## Milestone #45 — Safe D1 bootstrap preparation (Gate A only)

See [Model C Remote Bootstrap M45](MODEL_C_REMOTE_BOOTSTRAP_M45.md)
for the new pinned-commit local preflight CLI, deterministic read-only
plan and digest, per-database offline SQL transport contract, quota
admission binding, Miniflare fault-injection evidence and remaining
Cloudflare proof requirements. None creates remote credentials, D1
bindings, resources, Workers or routes.

The #44 activation decision remains **DEPLOYMENT BLOCKED —
REMOTE BOOTSTRAP NOT READY**. M45 is an offline preparation milestone,
not Gate B approval. There is still no authorized remote importer,
production-owner attestation, live Cloudflare account inventory or
verifiable remote rollback.
