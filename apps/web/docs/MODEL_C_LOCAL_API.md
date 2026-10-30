# PR #38 — Model C local read-only HTTP API

This PR adds the explicit, **disabled-by-default** `/api/model-c/` namespace to
the existing local Worker. No V1 endpoint, importer, schema, production workflow,
Wrangler binding, cloud account, UI or user data has been modified. No deployment.

## Six implemented GET routes

| Route | Reader | Parameters |
| --- | --- | --- |
| `/api/model-c/catalog/snapshot` | `getModelCCatalogSnapshot` | none |
| `/api/model-c/catalog/jobs` | `listModelCCatalogJobs` | `q,companyId,kind,batch,lifecycle,limit,cursor` |
| `/api/model-c/catalog/jobs/:id` | `getModelCCatalogJob` | required positive decimal `revision` |
| `/api/model-c/personal/summary` | `getModelCPersonalSummary` | none |
| `/api/model-c/personal/jobs` | `listModelCPersonalJobs` | `limit,cursor` |
| `/api/model-c/personal/jobs/:id` | `getModelCPersonalJob` | none |

All responses come from existing Model C reader contracts; JSON is not a mock.
The adapter preserves `productionAccess:false`, nulls, snapshot revisions, bounded
lists and history. Published CATALOG checkpoint is mandatory for PERSONAL.
No client-supplied identity is accepted. Errors use `{error:CODE}` and HTTP
400/403/404/405/409/503, without exposing queries or personal data.

## Test-only enablement and identity (NOT authentication)

Existing Worker checks `APP_ENV=local` and request URL localhost/127.0.0.1/[::1].
The new adapter repeats this check and requires
`MODEL_C_LOCAL_API='synthetic-only'` on the **server**. No default Wrangler
setting enables it. PERSONAL also requires `MODEL_C_TEST_OWNER`, a *server-only*
value matching `synthetic-[a-z][a-z0-9-]{0,63}`.
A header, cookie, query or path cannot select the owner; known owner-override
headers are explicitly rejected. Cross-origin requests are rejected.
The feature gate and hostname are **not a production authentication boundary**.
Do not deploy with these switches or bind real/persistent PERSONAL data.

## D1 bindings and reproducible laboratory

`apps/web/wrangler.jsonc` stays unchanged: it contains only the V1 `DB`.
The integrated Miniflare HTTP test loads the actual `worker/index.ts` esbuild
bundle, three independent **ephemeral** D1 bindings (`DB`, `CATALOG`, `PERSONAL`),
and applies the existing schemas using `applySchema` from the Node-only test
harness. It stages/publishes an actual synthetic checkpoint, seeds two synthetic
owners, runs HTTP `runtime.dispatchFetch` and checks responses, isolation and
write-free operation. No cloud bindings or credentials are required.

From `apps/web`, run `npm run check` (entire test suite, TypeScript and build)
and `npm run worker:check` (Wrangler dry-run), or
`npx vitest run tests/model-c-local-api.test.ts`. No separate user-operable
public/local API endpoint is activated in the normal Wrangler config.

Illustrative synthetic-only requests inside the Miniflare laboratory:

```
GET http://localhost/api/model-c/catalog/snapshot
GET http://localhost/api/model-c/catalog/jobs?q=Synthetic&limit=1
GET http://localhost/api/model-c/catalog/jobs/job:111...111?revision=1
GET http://localhost/api/model-c/personal/summary
GET http://localhost/api/model-c/personal/jobs?limit=1
GET http://localhost/api/model-c/personal/jobs/job:111...111
```

The job ID shorthand above is illustrative, not a literal valid ID (64 hex
digits required). Do not use real job keys or owner IDs in examples.

A synthetic receipt is checked against the current CATALOG head and PERSONAL
revision by the existing reader. This is an optimistic cross-DB consistency
check, **not** a distributed transaction or a signed certificate. Cursor tokens
are revision-bound, not authentication credentials.

## Explicitly NOT delivered

No Cloudflare Access/JWT auth, real user login, production deployment, public
Model C API, persistent DB provisioning, real bootstrap, command writer,
GitHub bidirectional sync, frontend integration or UI cutover. Model C remains
isolated from active V1 pages and mutating commands. A future security-reviewed
authenticated transport is required before real PERSONAL data can be exposed.
