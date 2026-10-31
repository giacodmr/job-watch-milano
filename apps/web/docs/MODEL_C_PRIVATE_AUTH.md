# Model C — Private Cloudflare Access authentication (milestone #43)

## Security design / ADR 0002

**Selected:** verify the Access application JWT using the maintained `jose` package before dispatching any API, SPA route, or static asset. Verification requires RS256 signature from the team's published JWKS, the exact configured issuer, expected audience, `exp`, `iat`, `sub`, and applicable `nbf`. The JWKS client has a five-minute cache and a short fetch timeout; missing or unavailable JWKS fails closed.

**Why not ctx.access?** Cloudflare's current documentation explains that `ctx.access` is available on directly Access-authenticated Workers, but the internal router of Workers Static Assets does not propagate it to the user Worker. Because Job Watch serves its entire React SPA and assets through a Worker-first route, relying solely on `ctx.access` would deny authenticated assets or force a gap in its local in-Worker security checks. No duplicate verification modes are implemented. Reference: https://developers.cloudflare.com/workers/configuration/cloudflare-access/

The old LOCAL_SYNTHETIC branch is unchanged: `APP_ENV=local` plus loopback plus separate default-off write gate. PRIVATE uses `APP_ENV=private`, but that flag alone grants nothing. All of these must be valid:
- exact https hostname `PRIVATE_HOSTNAME` (no ports, alternate hostname or workers.dev)
- `PRIVATE_ACCESS_ISSUER` = verified https team origin ending `.cloudflareaccess.com`
- `PRIVATE_ACCESS_AUD` = Access application AUD
- `PRIVATE_ALLOWED_SUB` = exact allowlisted, stable, interactive user subject
- `PRIVATE_OWNER_ID` = corresponding preprovisioned PERSONAL owner, never a synthetic fallback
- physically distinct `CATALOG` and `PERSONAL` D1 bindings
- valid RS256 Access JWT on **every request**, including HTML/JS/CSS/SPA and routes such as /api/health

The only initially supported principal is one explicitly configured subject. The browser cannot choose any owner; email/IP/cookie claims are never used as keys. Tokens indicating a service principal are rejected. The server constructs `AuthenticatedPrincipal` only after signature and all claim checks, then injects the trusted owner into the PERSONAL and composite readers. Missing PERSONAL owner head is a hard reader failure, not auto-registration. This is deliberately a one-user mapping; a multiuser mapping requires a separate reviewed migration and authorization policy.

## Private route policy

- GET /api/model-c/catalog/snapshot, jobs, jobs/:id — authenticated CATALOG read
- GET /api/model-c/personal/summary, jobs, jobs/:id — authenticated owner-scoped PERSONAL read
- GET /api/model-c/opportunities/jobs, jobs/:id — authenticated composite read using **the same** owner
- GET /api/model-c/personal/capabilities — always `writeEnabled:false`, `productionAccess:false`; the #42 frontend is read-only
- SPA and assets — authenticated; `Cache-Control: private, no-store`; CSP, nosniff and referrer policy
- All other /api including V1, /api/commands and ingestion — 404
- ALL non-GET/HEAD requests — denied. No remote APP write path exists.
- Cross-origin and client owner override headers — forbidden.
- Uniform error JSON for authentication/configuration failures; no JWT, email, SQL or secrets logged.

There is no remote fallback to `MODEL_C_TEST_OWNER`, no remote local adapter invocation, and no use of Cloudflare Access cookies as proof without signature validation.

## Local synthetic verification

Security tests generate RS256 keys and JWTs with `jose` and verify via locally generated JWKs, without cloud calls. Tests include invalid/missing/forged tokens, wrong issuer/audience, expiry, future not-before, unknown key, service identity, invalid settings, wrong host, cross-origin, no remote POST, isolated D1 owner reads, no imported synthetic owner leak, no asset bypass and local runtime regressions.

`wrangler.private.template.jsonc` is deliberately incomplete and **must not be deployed**. No remote D1 identifiers or Access app exist in the template. `wrangler.jsonc` remains the existing local configuration.

## Limits and residual risks

- Cloudflare Access app, hostname protection and service policy are **not provisioned**; actual revocation latency, JWT/JWKS performance, CPU costs, account quotas, domain coverage and real IdP subject values cannot be certified locally.
- A signed Access JWT is independently verified even if an attacker can hit the Worker through an unexpected route; hostname is separately restricted.
- A valid previously issued JWT may remain valid until its Access expiration even after upstream policy revocation; do not cache authenticated principals across requests.
- Authorization here is deliberately narrow: **read-only, single-owner**. Future expansion must introduce audited enrollment/revocation and tenant isolation without client-supplied owner IDs.
- No private runtime deployment, remote ingestion, remote writes, or GitHub/Python reverse sync is included.

## Handoff for #44

Before any deployment: inspect actual Cloudflare account Free quotas, establish Access application on one dedicated hostname, explicitly allowlist its user subject, disable all unprotected alternate URLs, install real separate D1 bindings only through authorized provisioning, plan verified snapshot import against D1 Free daily write budget, preflight backup/time-travel/rollback, configure secrets privately, then deploy behind Access and run both authenticated/unauthenticated end-to-end smoke tests. The remote APP write gate remains **OFF**.
