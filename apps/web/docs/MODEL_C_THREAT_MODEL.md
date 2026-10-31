# Model C — Private runtime threat model

## Assets, boundaries and non-goals

Protected assets: signed-in SPA pages, JS/CSS, CATALOG metadata, PERSONAL decisions/SAVED and APP history, imported provenance and job identity, owner mapping. Trust boundaries: untrusted request -> Access JWT signature validation -> exact hostname/config checks -> explicit principal-to-owner mapping -> owner-scoped D1 queries -> response. The Worker and the Access-protected hostname are a single security boundary only after remote configuration verification.

No production mutation, ingestion, signup, multiuser tenant management, cloud provisioning, domain setup or deployment is authorized in milestone #43.

## Threat, defense and evidence

| Threat | Defense | Automated evidence |
|---|---|---|
| Spoofed or malformed Cf-Access-Jwt-Assertion | RS256 via jose against team JWKS | Missing, malformed, forged and unknown-kid cases |
| Valid token for different Access application | Explicit expected audience | Wrong AUD test |
| Token from another tenant | Exact issuer and approved team hostname | Wrong issuer test |
| Expired / premature token | JWT exp, iat, nbf validation | Expired and future nbf tests |
| Incorrect Access application service-policy | Explicit single-user sub allowlist; reject service hints | Unknown subject / service claim tests |
| Personal owner theft via email/header/query | Server-owned owner mapping; no browser owner choice | Cross-owner and override tests |
| Unknown/unprovisioned owner | PERSONAL reader rejects unknown head | Isolated D1 owner test |
| Alternate workers.dev/preview/HTTP host | Exact HTTPS host check; workers_dev/preview_urls false | Wrong host/scheme and static config checks |
| Public static assets or SPA | run_worker_first true and authentication before ASSETS.fetch | Root, JS, CSS, SPA unauthorized tests |
| Missing configuration/JWKS | Fail closed, no local fallback | Incomplete settings, missing DB, invalid key tests |
| CSRF and remote mutations | No remote mutation routes; restrictive Origin and method | POST, OPTIONS and cross-origin tests |
| Sensitive logs | No JWT, email, payload or SQL logging | Code-level review |
| Cross-CATALOG/PERSONAL scope contamination | Distinct bindings; TrustedOwner only after JWT validation | Distinct-binding/owner isolation tests |

## Residual risks

No live Cloudflare account configuration, Access audience, domain aliases or D1 mapping has been inspected. The template is not a deployable release. App access revocations may take up to existing token validity, so keep Access session lifetime short and recheck policy centrally. The single-user owner mapping is configuration-bound, and a first owner must be provisioned and validated without copying synthetic test identities. D1 quota/CPU and JWKS cold fetch behavior require actual guarded deployment measurements. Further non-mutating security audit required before enabling remote writes.
