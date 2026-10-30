# Model C PR #36 — Read-only catalog services (inactive)

Base main: `122ad9a54937c1825335bbd1c4e08805f0aa1c91` (#35 squash).

This PR introduces `worker/data/model-c-catalog.ts`, an **unwired**, pure D1 read service.
No active route, binding, personal-data adapter, UI, migration or importer changes.
Model C and the existing V1 API remain separate and inactive.

## Supported read surface

- `getModelCCatalogSnapshot(db)`: only a PUBLISHED CATALOG head, observed/content-origin commit and confirmed ledger/content revisions, current vacancy count and bounded company list.
- `listModelCCatalogJobs(db, filters)`: parameterized literal substring search, company/kind/batch/lifecycle filters, bounded keyset pagination over job_id, total and snapshot metadata. Cursors bind the CATALOG sync revision, run ID and exact filter signature; stale/mismatched cursors fail closed.
- `getModelCCatalogJob(db, id, expectedRevision)`: current-only job details, limited aliases and provenance. Archived permanent IDs are **not** returned as current vacancies.

All operations use only the CATALOG database, verify its schema scope/version (4), read only the published checkpoint, and check for head movement before answering multi-query results. Boolean flags remain nullable. No direct Python decision, fit score, personalized review or user state is inferred from CATALOG. The ordinary Reader V1/Worker routes remain unchanged.

## Explicitly out of scope

PERSONAL owner authentication, personal references/decisions and cross-DB receipt comparison. These require a separately reviewed **owner-bound** reader: do not merge PERSONAL by job ID, treat PENDING or mismatched receipts as VERIFIED, or expose private facts through shared CATALOG endpoints.

No Cloudflare remote bindings, production authentication or activation. This PR makes no claim about measured remote D1 quota, live performance, completed frontend integration or API readiness.

## Test gates

Synthetic ephemeral Miniflare D1 only: no-head/staging invisibility, published read, provenance, aliases, literal filters, invalid/stale cursors, wrong DB scope, missing-current identity and read-only behavior. `npm run check` and `npm run worker:check` must pass on the PR head. No merge until independent review.

Next, after green tests/review: implement PERSONAL owner-bound reads and receipt verification, then a separately authenticated, explicitly enabled API adapter and only then UI.
