# PR #39 — Candidature read-only React view

## Reference and visual contract

The exact approved `JOB_WATCH_CANDIDATURE_V2_1_LOGHI_REFERENCE.html`, plus V2.1 desktop/mobile screenshots and `JOB_WATCH_CANDIDATURE_V2_1_BASELINE_300.html`, were recovered from the user's project reference pack and read before implementation. V2.2–V2.4 are rejected baselines. The reference contains **demo-only writes** and **demo-only application stages** which were deliberately **not ported** into operational code.

Design tokens in `src/candidature.css` reproduce V2.1's white canvas, 218px pale sidebar, #dff331 logo accent, muted neutral table, 38px initial avatar, 27px heading, compact rows, underline tabs, right-side overlay drawer and mobile full-screen details. Default body weight is 300 within Candidature only; headings keep intentional heavier hierarchy. No font files, remote font downloads, fake corporate logos, fake KPIs or demo vacancies were added to production.

## Navigation and data flow

- `/candidature`: separate React view with WorkspaceShell, tabbed owner-scoped filters, real keyset pagination, company initials and overlay history drawer.
- `/`: unchanged legacy V1 Opportunità Explorer, with an added navigation link to Candidature.
- Worker `/api/model-c/personal/summary`, `/jobs`, `/jobs/:id`: existing **local synthetic-only** gate stays off by default; never toggled in Wrangler. Browser never sends an owner identifier, credentials or cookies intentionally.
- The PERSONAL reader's bounded page enrichment fetches visible CATALOG company/title/location/URLs in **one batched query** per page, not an N+1 browser request. Noncurrent PERSONAL identities remain readable, with null catalog facts and preserved captures. No cross-database SQL joins.
- PERSONAL query `view` = `all | to_apply | applied | dismissed` filters owner-held decision state and active references; optional `q` searches **captured title only**, `decision` and `reference` are SQL-backed; all applied before paging and count. Cursor includes filter signature and owner/catalog/personal revision. No client-only filter masquerades as global search.
- `PERSONAL_CONTEXT_UNAVAILABLE`, `CONTEXT_CHANGED`, disabled gate and other failures have explicit read-only fallbacks.
- `CURRENT` FIT is color-only, stale/unverified assessment scores are visibly historical.
- `dialog.showModal()` offers native modal focus management, Escape dismissal, focus restore and overlay; mobile width is 100vw.
- Riepilogo and Selezione display actual personal record and historic events; Retribuzione/Documenti explain unsupported fields. No fake editing/saving flows.

## Important product boundary

The current PERSONAL schema does **not** include full application tracking: application notes, recruiters, interview stages, meetings, salaries, reminders, manual external application creation or document URLs. The original reference V2.1 demo included those interactions, but they are not implementable without a future private writer/data contract. This PR does **not** assert those features exist, nor change the Python engine, V1 importer or production auth.

The tab `Inviate` indicates decision APPLIED **or** an active APPLICATION reference, **not** a live selection pipeline. `Da candidare` is based on INTERESTED/TO_REVIEW or SAVED (excluding explicit negative/applied decisions); `Scartate` is based on NOT_INTERESTED or DISMISSED without conflating their semantics.

## Testing and limitations

The extended tests exercise synthetic PERSONAL SQL filtering and CATALOG display enrichment; the Miniflare HTTP test serializes genuine Worker/D1 PERSONAL responses through Zod and renders the **actual React table** with `react-dom/server`. The additional `tests/candidature-browser.test.ts` uses real headless Chrome with an actual bundled React app, local HTTP server, real synthetic Worker and ephemeral D1. It verifies the rendered row, absence of global horizontal overflow at **1440/1280/768/390/320px**, mobile drawer content loading and Escape dismissal, and emits synthetic-only screenshots for visual inspection. It is a browser interaction and screenshot test, **not an automated pixel comparison against the V2.1 reference**; the screenshots still require visual review. Abort/race rendering under rapid browser interactions is not explicitly measured.

Run from `apps/web`: `npm run check`, `npm run worker:check`, the existing local migrations and relevant tests. Cloudflare access remains private/unimplemented. The API remains disabled in the ordinary Worker config; to see synthetic data one must provide approved local-only Miniflare bindings, no remote DB. No deployment, credential, paid service or persistent D1 use is authorized.

Because pixel-based browser QA against the V2.1 reference is an explicit acceptance gate, keep the PR in Draft until verified screenshots of the **running React implementation** at 1440/1280/768/390/320px have been reviewed. Green CI alone cannot approve the visual design.
