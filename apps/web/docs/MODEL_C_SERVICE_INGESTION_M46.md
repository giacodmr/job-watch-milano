# JOB WATCH — M46 service identity and chunked staging (Gate A only)

**State: CODE IMPLEMENTED (branch) / LOCAL TESTS REQUIRED / CLOUD_VERIFIED: NO /
DEPLOYED: NO / SERVICE INGESTION NOT ACTIVATED.**

The only executable integration is `createOfflineServiceIngestionHarness`, imported
directly by local tests. Neither `worker/index.ts` nor the private read-only
Worker entrypoint imports this handler. No private or preview route can enable it
with an environment variable. No Cloudflare account is connected, and no secret,
service token, account/owner ID, DNS, Worker or remote D1 is created.

## Architecture and principal isolation

```
external, in a FUTURE milestone:
  GitHub/Python verified commit → pinned canonical snapshot exporter
  → content + plan digest → Node packet builder → authenticated Access service
  → independently verified Worker principal → per-run D1 CATALOG staging
  → STOP BEFORE PUBLICATION (M47)
M46 reality:
  synthetic packets → locally signed RS256 JWT → offline HTTP Request
  → separate service identity verifier → strict Zod / digest admission
  → isolated ephemeral Miniflare CATALOG schema v5
  → durable synthetic chunk receipt → no catalog_head mutation
```

`verifyServicePrincipal` authenticates a Cloudflare Access application JWT, not
a client-provided service ID, header name, cookie, user ID or owner override. It
pins issuer, audience, RS256, expiry, nbf, hostname and explicit service
`common_name` allowlist. Service JWT claims use `type:'app'`,
`sub:''` and `common_name:<service-token-client-id>`, according to the
Cloudflare Access application JWT documentation. The signed `common_name`
differs from the interactive user's nonempty `sub` and email. JWKS may rotate;
unknown keys fail closed. One principal has one capability: `catalog:stage`.
No capability to read/write PERSONAL, issue browser commands or publish.
The interactive private Worker remains JWT-first read-only and independently
rejects service tokens. Header-only Client ID/Secret pairs are NOT accepted by
this offline Worker: in a real deployment Cloudflare Access would terminate
and validate those and provide a signed assertion. No login redirect is
followed by the packet builder.

## Protocol version 1 and deterministic packets

Wire contract: `job-watch-model-c-ingestion/1`, CATALOG only.

`POST /api/model-c/sync/runs` receives typed scope, SHA-pinned commit,
manifest/projection/plan digests, expected CATALOG revision, schema 5,
total chunk count and a run ID derived from the canonical request.

`POST /api/model-c/sync/runs/{id}/chunks` receives the deterministic
chunk index/count/digest, idempotency key and a strict allowlist of
`company`, `source` and `job` metadata. SQL strings, table names,
owner overrides, arbitrary routing, personal histories and extra fields
are disallowed. The client constructs packets without network access:
`tools/model-c-ingest-offline-client.ts`. Hashes prove consistency of
submitted packet bytes, **NOT provenance from Git**. A future remote
operator must independently verify Git origin/main ancestry, exact projection
proof, run/plan binding and schema before admitting publication.

Each request is capped at **12 KiB**, one chunk at **16 records**, one run
at **64 chunks**, and no more than **8 retained runs** in the local
admission gate. These are project conservative limits, not claimed Free
capacity guarantees. Each service request re-verifies the signed JWT and
checks a synthetic server-only quota gate; no query parameter/header
can assert account usage or bypass quota. Unknown real Cloudflare account
usage must be DENY. The synthetic quota is NOT a remote account-wide
reservation system, and it does not authorize actual cloud ingestion.

## D1 staging and publication boundary

Migration `0005_ingestion_staging.sql` is **additive** to CATALOG v4:
`catalog_ingest_runs`, `catalog_ingest_chunks`, FK, hash/length
constraints, immutable/retain triggers, schema version 5. PERSONAL stays
schema v3. Existing reader/importer/preflight now require catalog v5.

The only staged run state is `RECEIVING`; the database *cannot* set
PUBLISHED in the newly created tables. Chunk receipts and payload JSON
are persisted in D1 but never passed to the visible catalog tables.
`catalog_head` and its checkpoint remain untouched by every M46 handler.
An out-of-order chunk is allowed; status reports missing indices, counts,
verified receipt digests, and whether all chunks are present. Complete
means **received**, not **verified provenance** or **published**.
An identical replay returns `REPLAY`; same key/index with different
digest returns conflict or invalid digest. DB uniqueness protects concurrent
insertions. A lost acknowledgment may hide a committed row; the offline
client inspects durable receipts before retry and never retries blindly.

Old/imported identities, APP decision events and PERSONAL receipts are
never mutated by service staging. **No cross-D1 atomic transaction exists**.
PERSONAL facts need a separate owner-bound authorization and reconciliation
proof in M47+, not a generic service permission.

## Security/error boundary

| Problem | Behavior |
|---|---|
| Missing/expired/fake service JWT | 401 |
| Valid interactive token / owner override / cookie | 403 |
| Strict schema or digest invalid | 400 |
| Unknown endpoint / principal's run | 404 |
| Different run/chunk / stale CATALOG revision | 409 |
| Too large request | 413 |
| Unexpected content type | 415 |
| Local staging capacity exhausted | 429 |
| Unknown server-side budget | 503 |
| D1 failure / uncertain write | 503 with sanitized code; inspect receipt |

The handler emits no request body, SQL, token, owner, stack trace or sensitive
source path in its responses. Any state-changing request is authenticated
before the body is consumed or D1 is touched. Read-only status requires
service authentication and returns only minimal receipt metadata.

## D1 / Workers Free and unverified blockers

Official platform docs checked October 31, 2026:
- https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/application-token/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- https://developers.cloudflare.com/d1/worker-api/d1-database/
- https://developers.cloudflare.com/d1/platform/limits/
- https://developers.cloudflare.com/workers/platform/limits/

D1 Free: 10 databases, 500 MB each, max SQL 100 KB, max bound parameters
100, 50 D1 queries per Worker invocation and 30-second query limit.
Worker Free: 10 ms CPU per HTTP request. A signed JWT check, parsing,
SHA-256 and multiple indexed reads must be **measured on actual account**
before activation. Local/Miniflare does not certify Worker CPU quotas,
time-travel bookmarks, account-wide daily quota or unobserved writers.

Missing before Gate B: verified Cloudflare account and Free plan/quotas,
isolated private Access hostname and strict Service Auth policy, real
service client ID in secure configuration, owner mapping for PERSONAL,
pinned real source ancestry, secure secret custody, atomic import
publication protocol and recovery/restore proof. Cloudflare Access must
deny unprotected assets, workers.dev and preview routes before activation.
No real remote ingestion, migration or Worker write route is authorized.

## Handoff to M47

M47 should build a separately reviewed verification and promotion protocol:
validated inventory hash/lineage, resumable chunk receipt reconciliation,
immutable complete manifest, full trusted identity projection,
single-DB CATALOG atomic head CAS, append-only PERSONAL reconciliation
without a false cross-DB atomicity claim, and verified uncertain-result
recovery. It must remain OFFLINE until a subsequent explicit Gate B.
Do not interpret `complete:true` as permission to publish.

**Decision: GATE A IMPLEMENTED IN CODE — SERVICE INGESTION NOT ACTIVATED.**
