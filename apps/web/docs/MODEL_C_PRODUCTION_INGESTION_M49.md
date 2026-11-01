# M49 — Production ingestion transport (Gate B closed)

**Status: locally scoped M49 candidate; remote release blockers transferred to M50 Stage 0.** The PR may merge only after local acceptance and both final CI workflows are green; merge does not authorize the pilot. Neither production Cloudflare, Access service application, D1 remote, DNS, secrets, ingestion nor APP write paths are activated. M48 is merged in `main` (`70925973e8e3e7872d939294954f3ff2b8d90ed4`). Do not label the code as cloud-verified or the remote publication flow complete.

## Boundary and files

- `worker/index.ts` dispatches **only** `/api/model-c/sync/` to the service branch before interactive Cloudflare Access. All other private paths continue interactive RS256 JWT verification before any asset or read. The committed template has `APP_ENV=private` only, so the service branch immediately returns 404.
- `worker/model-c-ingest-v2-production.ts` implements the v2 CATALOG staging receiver using the additive v7 CATALOG tables from M47, with distinct service JWT audience, `sub=''`, expected `common_name`, service-only scope, strict host and no browser Origin/Cookie or owner overrides. It **never imports** Node Git code, trusted publication adapters, PERSONAL writers, or local detached lab harnesses.
- `tools/model-c-m49-service-client.ts` is an **uninvoked, detached coordinator helper**. It validates deterministic packet/chunk digests, posts at most 512 chunks, inspects durable status/receipts after unknown writes and never performs a blind network retry after an uncertain outcome. A separate explicit runtime `gateBApproved` argument is mandatory. The helper itself does not verify pinned Git source provenance or confer publication privileges.
- `worker/model-c-ingest-v2-lab.ts` and the v1 path remain isolated and unchanged. No new migration has been introduced.
- The service branch uses **CATALOG D1 only**. The presence of distinct CATALOG and PERSONAL bindings is checked, but service code cannot query or modify PERSONAL. The interactive application retains the existing APP CAS/event precedence and default-denied writes.

## Denial and configuration

Only a separately authorized future M50 configuration could supply:

- `PRIVATE_INGESTION_GATE=gate-b-approved`
- `PRIVATE_QUOTA_ATTESTED=verified-under-budget`
- `PRIVATE_SERVICE_ACCESS_AUD` — distinct from the interactive audience
- `PRIVATE_SERVICE_ALLOWED_CLIENT_ID` — independently validated service JWT identity
- `PRIVATE_INGESTION_QUOTA_REMAINING` — manually/operator-attested, 100..30,000
- `PRIVATE_INGESTION_QUOTA_VALID_UNTIL` — UTC timestamp no more than five minutes away
- existing private hostname, issuer, Access owner binding, and physical CATALOG/PERSONAL database IDs.

**None of these settings is populated in `wrangler.private.template.jsonc`.** A flag or short-lived quota number does **not** reserve account-wide writes. The M49 CATALOG quota admission now **durably reserves conservative write units** before v2 run/chunk staging, and private APP commands reserve against the same `catalog_write_reservations` ledger already used by the trusted importer. Service run+chunk reservation occurs in the same CATALOG transaction as each staged write. PERSONAL commands reserve in CATALOG before writing PERSONAL; a failed PERSONAL mutation intentionally leaves its reservation charged, because no cross-D1 transaction is claimed. This guards concurrent **Job Watch-owned** spending locally; it does not measure external Cloudflare account consumers, actual rows billed, read allowance, Worker CPU or remote storage. Until authoritative account-wide telemetry and a verified operating budget are available, **Gate B remains CLOSED**.

Default unknown quota is deny; no 60k boost, paid fallback, public Worker route or alternative secret mechanism. Stage requests cap at 512 chunks and 20,000 catalog records; each chunk has the existing 48 KiB canonical record cap and the 56 KiB HTTP body bound. Staging capacity is bounded by existing M47 SQL (8 live runs). Unknown write outcome requires receipt readback, not a blind re-submit.

## Publication remains a separate security authority

Staging does not prove Git commit provenance or completeness. No service JWT may transition the journal into VERIFIED, publish CATALOG HEAD, reconcile PERSONAL or perform retention. M47's independently verified Git/Python importer remains the sole trusted local publisher. This PR does **not** implement a cloud-authorized remote trusted publication/reconciliation controller: it requires a separately designed and tested trusted remote control path or a verified external coordinator that invokes authorized D1 operations without granting `catalog:stage` additional powers.

Any remote publication design must preserve M47 commit/manifest/projection/ledger verification, CAS, atomic CATALOG batch, separate PERSONAL receipts and APP semantics. No claim of distributed CATALOG/PERSONAL atomicity is allowed.

## Fixed M49 acceptance register

| AC | State | Local evidence / missing proof |
|---|---|---|
| 01 Deployable transport | PENDING CI | Worker bundle and private Wrangler dry-run |
| 02 Service-only JWT | PENDING CI | Distinct Access audience/client, strict hostname, interactive denial |
| 03 Durable stage/replay | PENDING CI | Actual local Miniflare CATALOG v7 create/chunk/status/replay/conflict |
| 04 Provenance and completeness | PARTIAL | Trusted M47 importer unchanged, but remote verified publication adapter absent |
| 05 Cross-D1 reconciliation | PARTIAL | M47 local regression retained, remote controlled reconciliation absent |
| 06 Recovery | PARTIAL | Local v2 durable readback plus M47 regression; no end-to-end remote cold restart |
| 07 Free-tier safety | PARTIAL | Default-deny, atomic local CATALOG reservations shared by v2 staging, importer and private APP; no authoritative Cloudflare account-wide observation |
| 08 Private security | PENDING CI | Worker import graph, service/user isolation, disabled public and APP endpoints |
| 09 Regression | PENDING CI | Full pre-existing M47/M48 Vitest + browser, typecheck, build, migrations and dry-runs |
| 10 Documentation | PASS scoped | This runbook and M50 Gate B handoff; production operator steps need confirmation |
| 11 Final CI | PENDING | Both workflows must pass on final HEAD |

Do not upgrade PARTIAL cells merely because CI is green. M49 can merge after complete local (A) acceptance; AC04–AC07 remain explicit M50 Stage 0 release blockers. Gate B stays CLOSED.

## Actual Free-tier policy (official docs checked 1 November 2026)

- D1 Free: 100,000 rows written/day, 5,000,000 read/day; 500 MB/database and 5 GB/account. Free daily limits enforced at midnight UTC reset since 1 September 2026.
- Workers Free: 100,000 requests/day, 10 ms CPU/request. Other D1 per-invocation limits apply.
- Job Watch **internal** ordinary admission budget is 30,000 write units/day across all databases and account consumers; 60,000 never automatic.
- Local `meta.rows_written` and synthetic tests do not attest remaining remote quota, CPU usage or storage.

References: https://developers.cloudflare.com/d1/platform/pricing/ , https://developers.cloudflare.com/d1/platform/limits/ , https://developers.cloudflare.com/workers/platform/limits/ , https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/

## Non-negotiable stop line

No deployment, D1 remote operations, Cloudflare API provisioning, account changes, Access/DNS setup, secrets or billing in M49. Only a new explicit M50 authorization, independent quota checks, trusted publication implementation, and staged smoke approval can open Gate B.


## M49 local scope freeze and explicit release debt (1 Nov 2026)

**Gate A / merge requirements (A):** final TypeScript typecheck and build, tests including M47/M48 regressions, service JWT and interactive Access isolation, D1 v7 run/chunk/replay, shared conservative CATALOG reservation including PERSONAL pre-reservation, idempotent APP behavior, private Worker graph, local migration, standard/private Worker dry-runs, private preflight, and both final-HEAD CI workflows green. The D1 batch contract is reject-on-failure; a batch rejection cannot grant a PERSONAL write. No unknown result is promoted to success.

**Implemented but locally incomplete for the pilot (B):** AC04 independently authorized Git/Python remote trusted publisher (M50 Stage 0 deliverable: pinned-source proof, trusted principal, atomic CATALOG publish/CAS and verified receipt); AC05 controlled PERSONAL reconciliation (Stage 0 deliverable: owner-bound reconciliation and preserved APP precedence); AC06 ambiguous-ACK recovery (Stage 0 deliverable: restart/lost-ACK simulation and durable receipt readback); AC07 quota admission (Stage 0 deliverable: validated shared write admission under concurrency and an explicit fail-closed operator budget procedure). These remain **PARTIAL and RELEASE-BLOCKING**, not PASS, even if M49 merges.

**Cloudflare-only evidence (C):** independently verified actual Free account plan and live available quotas (including other consumers), D1 remote behavior, Access and hostname enforcement, production CPU/latency/storage, backup/rollback and real deployment. No Cloudflare-only criterion is PASS in M49. Gate B = CLOSED.

**M50 Stage 0 exit:** record a bounded test matrix proving trusted provenance cannot be forged by the stage principal; CATALOG commit and rollback under conflict; PERSONAL receipt reconciliation and APP priority; lost-ACK plus process restart recovery; shared ledger concurrent admission and deny-unknown quota. GO only when all are proved locally, then **request separate user authorization** to start Cloudflare Stage 1. NO-GO on any concrete integrity/security failure. No additional SaaS, ATS, UI, scoring or hardening requirements without evidence.

**Merge-policy correction:** the previous instruction to keep M49 DRAFT until *remote* AC04–AC07 were fully resolved conflated local merge with production authorization. It is superseded by this scope freeze. Keep original PARTIAL markings for the missing remote capabilities; do not backfill them as PASS. The changes do not permit an accidental runtime activation.
