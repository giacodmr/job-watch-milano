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
