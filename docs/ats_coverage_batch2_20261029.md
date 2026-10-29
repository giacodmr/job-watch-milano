# ATS Coverage Recovery — Batch 2 (29 October 2026)

## Production baseline before changes

Source: `main` `job_watch_healthcheck.json`, generated `2026-10-29T07:09:18Z`.

| Coverage | Count |
|---|---:|
| VERIFIED | 92 |
| PARTIAL | 115 |
| FAILED | 0 |
| NOT_CHECKED | 0 |

Mollie now has 11 jobs persisted with first_seen_at `2026-10-29T01:44:38Z` but remains PARTIAL because the first-party board (51 UUIDs) and Ashby public postings (53 UUIDs) disagree. This is a source coverage warning, not zero jobs.

## Revolut (JW1, Tier A): implemented recovery

Technical discovery: https://www.revolut.com/careers/ is an official server-rendered Next.js page. Its `__NEXT_DATA__.props.pageProps.positions` contains a complete list of public positions. Its independently rendered `We have N open positions` heading and `widgetData.careers-teams-widget.total` give a 3-way count contract.

New `revolut_collector.py` plus dispatch in `collector.py`:
- Parse the first-party embedded JSON without scraping dynamically loaded subsets.
- Require heading count = widget total = positions length, unique valid UUIDs and title/location presence for the worldwide inventory.
- Filter the fully enumerated inventory only after reconciling global count and records, with the existing geographic allowlist.
- Verify each retained official requisition URL using the stable first-party UUID-only detail path, requiring embedded detail UUID + title to match the board.
- Respect per-detail pacing and shared bounded requests/retries; rerun the complete inventory and demand identical UUID sets and totals.
- Preserve individually validated jobs as PARTIAL on transient detail or second snapshot failure. Never treat 200 alone as completeness.

Read-only live smoke ([GitHub Actions 40868594618](https://github.com/giacodmr/job-watch-milano/actions/runs/40868594618)): **321/321 global requisitions; 56 target-location requisitions, all with verified first-party URLs and matching detail UUIDs; second snapshot 321/321 and stable; coverage VERIFIED on that execution.** This is not proof of persisted production state until the normal Collector publishes and healthcheck is read back.

## Nexi (JW1): mapped to official Oracle, partial geographic proof

The Nexi first-party corporate country selector links to Oracle Recruiting Cloud Candidate Experience `CX_1`, host `fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com`. The existing Oracle adapter already implements public `recruitingCEJobRequisitions` with `findReqs`, `limit`, `offset`, unique requisition IDs and total count.

Read-only test: **85/85 global requisitions enumerated** on the official Oracle API; **4 Italian requisitions have country-only locations**; **0 have Milan/Rome locations sufficiently established in the public metadata**. Evidence: https://github.com/giacodmr/job-watch-milano/actions/runs/40868594618. Several country-filtered Italian requisitions expose `Italy` rather than city-level metadata. The observed `0 target jobs` is **not** a proof there are none.

Safety intervention: Nexi Italy-only requisitions are explicitly counted as geographic unknowns and force **PARTIAL**. Do not silently promote to VERIFIED based on 85/85 if city metadata is insufficient. Do not alter the user's geographic filters to include all of Italy. Next step: identify public detail city/location evidence or reconcile Nexi Oracle `GeographyId` against a documented official, public city-code source, checking only qualified records.

## Worldline (JW1): still PARTIAL, actionable diagnosis

On `https://jobs.worldline.com/viewalljobs/` the SuccessFactors public page returns **Results 1–50 of 65** (page 2: **51–65 of 65**). Both pages are accessible (HTTP 200) but contain **zero job-detail URLs in the first-party server-rendered HTML**; the current safe parser cannot validate even one stable requisition. `/search/` uses an additional JS widget loader; HTTP 200 and a total alone are not sufficient.

The scope is not certified. Next concrete change: inspect only public SuccessFactors widget/network data, establish an actual count/ID/location contract for all pages, add strict paginated adapter + fixtures; never invent missing URLs from a search engine.

## Changed files and validations

- `collector.py`: Revolut dispatch, Oracle Italy country-only ambiguity guard.
- `revolut_collector.py`: new official first-party inventory and detail verification adapter.
- `ats_mapping_jw1.json`: Nexi Oracle CE official board; Revolut first-party Next.js board.
- `test_ats_coverage_batch2.py`: 10 regression contracts (162 total repository tests validated in [GitHub Actions 40868594619](https://github.com/giacodmr/job-watch-milano/actions/runs/40868594619)) (Nexi and Revolut), including count mismatch, duplicate UUID, invalid detail UUID, unstable inventory, and country-only Italy.
- `tools/ats_diagnostic_batch2.py` and `.github/workflows/ats_probe_batch2.yml`: read-only live source contract diagnostics and smoke.

Guardrails: `job_watch_rules.json`, `companies_job_watch_v2.json`, decisions, job memories, source snapshots, semantic surfacing, Worker SELECT/APPLY and existing scheduled workflows are untouched by this PR. No paid services, authentication bypasses or third-party vacancy links.

## Reporting guidance

Do **not** conflate 56 Revolut target roles observed during an official live smoke with 56 net-new relevant opportunities: compare against persisted identity/memory and let normal collection assign `first_seen_at`. Dates not supplied by the official feed are left absent. Once merged, run the normal `job_watch.py collect --publish` pipeline through the serialized GitHub Actions writer, then verify `current_jobs_jw1.json`, `job_watch_healthcheck.json` and source/memory reconciliation.
