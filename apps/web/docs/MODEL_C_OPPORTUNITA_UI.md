# PR #40 — Opportunità Model C read-only explorer

## Routing and product boundary

- `/opportunita` is the Model C React Explorer with the exact Candidature #39 workspace visual foundation.
- `/candidature` remains the #39 read-only PERSONAL tracker.
- `/` remains the legacy V1 explorer, unchanged.
- WorkspaceShell now takes a `section` to set the active tab, breadcrumb and skip-link text. CSS extends `candidature.css` with a small scoped `opportunita.css`.
- The normal Wrangler config does **not** enable Model C. All APIs remain under the PR #38 `APP_ENV=local`, local host, server-only `MODEL_C_LOCAL_API=synthetic-only` gate; no real authentication or deploy.

## Read-only data contract

`GET /api/model-c/opportunities/jobs` composes **one published CATALOG page** with a **bounded, owner-filtered PERSONAL batch**:

1. CATALOG `listModelCCatalogJobs` applies `q` across title/company/location, `companyId`, `kind`, `batch`, `lifecycle` and `needsAnalysis=true|false` server-side before counting/keyset paging (up to 100).
2. `getModelCPersonalOverlays` reads current pointers, decision events, assessment current and references for **only those page IDs** in a single bounded query, plus batched metadata/ref lookups. SQL is scoped by trusted server owner. The overlay is **null**, not invented, for vacancy without owner facts.
3. The private response contains `{snapshot,items:[{...job,personal}],total,nextCursor,personalRevision,productionAccess:false}`. No PERSONAL information enters CATALOG endpoints.
4. A final published snapshot check detects cross-request CATALOG head changes. PERSONAL reader checks its own revision, context digest and CATALOG head before and after batch. Optimistic checks, not distributed transactions or cryptographic attestation.

`GET /api/model-c/opportunities/jobs/:id?revision=1` returns the actual CATALOG detail and alias list, a bounded PERSONAL overlay, and complete PERSONAL detail/events if the owner has a corresponding reference. An absent PERSONAL reference is `null`. Both flows are private under the synthetic-only gate.

## UI and semantics

- Tabbed filters: all, NEW, UPDATED, needsAnalysis true. The latter means Python technical flag, **not** semantic suitability or an AI recommendation.
- Search by role/company/location, company filter from published snapshot (first 500 may be truncated), kind, batch, lifecycle, and keyset pagination with previous-cursor stack.
- Table: company monogram, job title/location, lifecycle, technical needs-analysis, real decision/reference, fingerprint-aware PERSONAL FIT, last **observation** (not publication date).
- Drawer: summary/official links, analysis and FIT freshness, CATALOG alias/provenance, PERSONAL event history when present.
- A `NOT_INTERESTED` row remains visible as catalog history/inventory, with its true decision displayed. No static blacklist or UI-generated rankings.
- No fake buttons for save, apply, interview, salary or follow-up; no localStorage persistence or new personal write.

## Compatibility and limitations

V1's historical CLOSED jobs, full assessment/coverage/decision summaries, source health and advanced V1 predicates are not all present in Model C CATALOG. The new explorer shows only published **current** identities; historical captured PERSONAL jobs remain in Candidature. Full semantics parity requires read/projection work and some upstream fields. No fabricated data fills missing semantics.

CATALOG keyset sorting remains by permanent job ID; no implied descending date, semantic relevance or FIT order. New needsAnalysis filter is a bounded SQL predicate with cursor signature. Worker auth is **not** production ready and no runtime configuration, persistent D1, GitHub/Python engine or cloud deployment is changed.

## QA

The existing `tests/candidature-browser.test.ts` now tests **both** pages in a single Chrome+React+Worker+ephemeral D1 laboratory across 1440/1280/768/390/320 viewport widths, including drawer data and ESC. See GitHub Web foundation CI logs for visual screenshots and verify manually against the approved V2.1 structure.

The Model C HTTP test suite additionally verifies CATALOG filters, private overlay composition, no database writes, two synthetic owners plus an owner with no references, remote gate, metadata and real rendered OpportunityTable. Normal tests, strict TS, migrations, build and Worker dry-run must pass on the final head before merge.
