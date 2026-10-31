# Job Watch — Milestone 48: Private Cloudflare runtime and controlled pilot

**Status:** Local readiness implementation in PR #49. **Gate B CLOSED.** No Cloudflare account access, remote D1 creation, Access configuration, DNS, secrets, billing, deployment or remote writes were authorized or performed.

## 1. Delivered architecture

M48 builds on merged M47 (`d0e51b2c19d43c62d6059c102eabf99ab684d16c`). The **single deployable Worker** entrypoint is `worker/index.ts`. Its `APP_ENV=private` router verifies a Cloudflare Access **interactive RS256 JWT on every request**, including SPA assets. Identity is matched against a server allowlisted JWT subject, issuer and audience; PERSONAL owner comes exclusively from `PRIVATE_OWNER_ID`. Headers, cookies, query strings and payloads cannot select a PERSONAL owner.

The existing `worker/private-runtime.ts` and data modules provide CATALOG snapshot/jobs/detail, owner-bound PERSONAL summary/jobs/detail, and composite opportunities list/detail. React `src/Opportunita.tsx`, `src/Candidature.tsx`, `src/JobDetail.tsx` and their browser-only typed API clients consume these paths. Local Miniflare reads use two separate physical D1 databases with CATALOG schema 7 and PERSONAL schema 3. There is no production sample user or synthetic data fallback.

The APP writer is shared with the local lab solely at the transactional D1 implementation layer, `worker/data/model-c-personal-write.ts`. A **separate private trusted-principal adapter** accepts the verified interactive JWT principal, never a client-provided owner and never an unrestricted synthetic local owner. It reuses transactional APP version/CAS, immutable events, idempotency-key replay, imported fact precedence and durable read-after-write behavior. A confirmation is returned only after `personal.batch()` resolves; lost-ack retry uses the same operation ID and returns the stored durable receipt.

## 2. Default-denied private write transport

`POST /api/model-c/personal/commands/decision` and `.../saved` are supported in the Worker code **but not activated by the committed configuration**. Both **server-owned** settings are required:

- `PRIVATE_APP_WRITE_GATE=gate-b-approved`
- `PRIVATE_QUOTA_ATTESTED=verified-under-budget`

They are intentionally **absent** from `wrangler.private.template.jsonc`; this file also has no real D1 binding, Cloudflare Access identity or account ID. Neither setting is an attestation by itself. A future separately approved operator must first verify the *actual* current account-wide quota, Access/owner binding and safety budget before setting them. If either is absent, the private router remains read-only and all mutation methods are denied.

Even when both are set in isolated local tests, the Worker still requires verified interactive Access JWT, exact configured hostname, same-origin `Origin`, valid JSON content type, a bounded 2 KiB body, permitted route and kind, no user/owner override headers, two different D1 bindings, strict payload validation and the D1 CAS/idempotency checks. No remote ingestion route or service token is reachable through this interactive private router. The M46/M47 service-token receiver is a **separate offline laboratory** and is not quietly exposed as a production endpoint in this milestone.

Browser `PersonalActions` reads `GET /api/model-c/personal/capabilities` before rendering mutation controls. Its existing pending-operation retry reuses the same operation ID and refreshes PERSONAL after a verified response. Until Gate B, it receives `writeEnabled:false` and remains read-only.

## 3. Configurations and preflight

- `wrangler.jsonc`: local V1 Worker `APP_ENV=local`; remote D1 prohibited.
- `wrangler.private.template.jsonc`: buildable private Worker **deployment template**, purposely unprovisioned. `workers_dev:false`, `preview_urls:false`, `assets.run_worker_first:true`, no credentials, remote D1 IDs, routes or write flags.
- `tools/private-gate-preflight.mjs`: no network, no Wrangler deploy, no credentials. Checks flags are omitted, migrations are additive/versioned, and reports `GATE_B_REQUIRED` separately from successful local code readiness. `npm run preflight:private` does not authorize activation.
- `npm run worker:check:private`: dry-run bundling only; never deploy.

The private runtime is **deployable code**, not an authorized or configured deployment. Physical CATALOG/PERSONAL D1 IDs, actual Access issuer/audience/subject, owner mapping, current quota/CPU, separate DNS hostname, rollback procedures and live smoke must be reviewed and populated only under Gate B.

## 4. Security matrix and negative tests

| Boundary | Local evidence |
|---|---|
| Missing, wrong-issuer, forged, expired or service JWT | HTTP 401/403 or deny before any D1 read/write |
| Alternate host / workers.dev / public SPA asset | Access fail-closed; no unauthenticated bypass |
| Owner override header, wrong Origin, unexpected method | Denied by private policy |
| Mutation flags omitted or only one set | Denied; capabilities read-only |
| Wrong JSON kind/Content-Type/oversize | Strict 400/415/413; no D1 mutation |
| Valid Access principal and two local Gate B flags | Owner-bound D1 command; atomic commit |
| Repeated operation ID with same payload | Durable idempotent replay, exactly one APP event |
| Reused key with altered payload | 409 `IDEMPOTENCY_KEY_REUSED` |
| Stale per-job CAS | 409 `REVISION_CONFLICT` |
| Other PERSONAL owner | D1 rows untouched, never exposed by read model |
| Unknown/insufficient actual Cloudflare remote budget | DENY; no remote authority |

## 5. Acceptance criteria (fixed)

1. A real Worker entrypoint compiles for private config (dry-run only).
2. CATALOG → authenticated Worker → React read client and PERSONAL overlay use actual local D1.
3. Strict service-vs-interactive separation, Access user/owner isolation and negative auth tests.
4. APP writes prepared through private route under **test-only Gate B settings**, while production remains disabled; transactional CAS/idempotency unchanged.
5. No legacy/public alternate routes and assets Worker-first.
6. Both local schema migrations and Worker dry-runs succeed.
7. M47 regression suite remains green.
8. Gate B provisioning dependencies are documented explicitly.
9. Both CI workflows pass on final M48 HEAD.

## 6. Gate B dependencies (not local blockers)

Before any remote pilot, separately authorize and verify: Cloudflare Free account/plan and shared daily read/write availability; internal budget normally 30,000 writes/day with unknown quota DENY; 10 ms Worker CPU/request and 50 D1 subrequests per Worker invocation; 500 MB per D1 database and 5 GB per Free account; distinct remote CATALOG/PERSONAL bindings; migration/restore and rollback; Access app/issuer/audience/subject and service-token boundary; correct non-public hostname and zero alternate routes; real service-to-service catalog ingestion architecture; application smoke; response/data security and request observability policies.

**Stop line:** Gate B CLOSED; no actual Cloudflare calls, account changes, D1 remote operations, secrets, DNS, deployment or paid-tier upgrades. Remote first writes require a fresh explicit mandate.
