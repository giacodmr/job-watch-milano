# ATS Coverage Recovery — Batch 3 (29 October 2026)

## Production baseline before changes

On `main`, `job_watch_healthcheck.json` generated `2026-10-29T12:15:30Z`, the 207 monitored company sources have:

| State | Count |
|---|---:|
| VERIFIED | 93 |
| PARTIAL | 114 |
| FAILED | 0 |
| NOT_CHECKED | 0 |

This includes persisted **56 verified Revolut jobs** (first seen `2026-10-29T12:04:35Z`) and **10 Mollie jobs** (VERIFIED); Nexi is PARTIAL because 4 Italian Oracle requisitions lack city-level evidence.

## Dojo corporate — new official collector

Corporate official careers page: https://dojo.careers/jobs

Public Greenhouse publisher: https://boards-api.greenhouse.io/v1/boards/dojo/jobs

The company's official `Astro` server-rendered `Jobs` component contains the initial 10 vacancies of its *corporate* job board; its canonical URLs and order match the Greenhouse board. Public Greenhouse publisher serves **24 postings** and declares `meta.total=24`.

New code (`dojo_collector.py`): strict first-party Astro decoding, compare the visible initial page size/ordering/IDs/titles/official URLs with full Greenhouse `jobs`, validate numeric meta.total, deduplicate and require stable IDs and location metadata, open **all 24 corporate official job-detail pages** to verify each title and first-party ID (not only jobs that match geography), then rerun the first-party and publisher snapshot to ensure stable IDs and counts. Fail closed on any discrepancy.

**Live smoke:** https://github.com/giacodmr/job-watch-milano/actions/runs/40946340967

- corporate initial 10 job records reconcile against complete Greenhouse publisher 24/24
- 24/24 first-party detail pages with matching official ID and title
- second board snapshot stable, `coverage=VERIFIED` in read-only test
- **zero jobs after retaining only the user's EXISTING Dojo location policy** (`companies_job_watch_v2.json` permits Milan and Rome; no silent change to London).

Separate field-sales board: https://boards-api.greenhouse.io/v1/boards/dojoitaly/jobs returns 84 postings (public Greenhouse). Sample titles are `Agente di Commercio` and locations including country-only Italy. This is separate from the mapped `dojo.careers/jobs` corporate board and is **not** merged into corporate employment or falsely certified as part of this exact source. Future work, if needed, must first establish whether it contains ordinary employee roles in Milan/Rome and handle country-only geography safely.

## PayPal — discovery and remaining blocker

Mapped first-party board: https://careers.pypl.com/search-results/

This page returned HTTP 200 but exposes 0 safe, stable job-detail links in server HTML; its filtering/content loader is dynamic. Its profile login links to Eightfold, and https://paypal.eightfold.ai/careers is an official branded page but is itself JavaScript-rendered without enumerable public job IDs in its HTML. No independently evidenced authorized complete positions API or count/ID contract was found during this batch. **Remain PARTIAL, 0 validated jobs.**

Next investigation: decode only first-party public client-side networking and official search endpoint parameters; require stable UUID/job IDs, locations, pagination and total before enabling the adapter. Never use candidate login, scrape behind authentication, infer completeness from HTTP 200 or mix web-search snippets into official `VERIFIED` inventory.

## Worldline — remaining blocker

Mapped official SuccessFactors board https://jobs.worldline.com/viewalljobs/ exposes two pages and displayed total **65**, but its server-rendered HTML has **zero stable job-detail links**. `https://jobs.worldline.com/search/` includes the SuccessFactors widget loader and exposes corporate `apiURL` config, but this is not yet an evidenced usable, paginated public job-record contract. **Remain PARTIAL, 0 validated jobs.**

Next: identify verified public widget response and job detail IDs, then test complete 65/65 reconciliation. No guessed endpoints or job URLs.

## Files changed and verification

- `dojo_collector.py`: strict corporate first-party/Greenhouse cross-check and official detail verification for 24 global roles.
- `collector.py`: Dojo-specific dispatcher.
- `ats_mapping_jw1.json`: documented first-party corporate scope and exact Greenhouse publisher, distinguishing independent Italian field-sales board.
- `test_ats_coverage_batch3.py`: 9 regressions (ID/URL mismatches, duplicates, pagination, details, publisher drift, geography).
- `tools/ats_diagnostic_batch3.py` and `.github/workflows/ats_probe_batch3.yml`: first-party, PayPal, Worldline public endpoint diagnostics and live read-only Dojo smoke.

Repository CI: **178 tests passed** https://github.com/giacodmr/job-watch-milano/actions/runs/40946341041

All current-job snapshots, semantic memories, salary rules, selection states, user choice lists, geographic company allowlists, and Worker SELECT/APPLY logic are left unmodified. Production coverage must be checked only after serial GitHub Actions Collector runs and publishes the result to main.
