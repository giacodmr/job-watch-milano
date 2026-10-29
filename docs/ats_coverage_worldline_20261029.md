# Worldline ATS Recovery — 29 October 2026

## Status: targeted official jobs recovered; source remains PARTIAL

Worldline careers: https://jobs.worldline.com/viewalljobs/ publishes **65** results, paginated 50 + 15. The page is server-rendered without usable job detail links, and the standard generic SuccessFactors collector returned no observed target jobs.

Read-only investigation of first-party JavaScript on https://jobs.worldline.com/search/ discovered the official legacy search `POST https://jobs.worldline.com/services/recruiting/v1/jobs` (visible in `j2w.searchManager.min.js`). The endpoint accepts `keywords`, `locale`, `location`, `pageNumber` and `sortBy` and returns job title, ID, structured locations, marketing brand and role family. The rendering script builds an original publisher URL `https://jobs.worldline.com/job/{unifiedUrlTitle}/{id}-en_US`.

**Important non-reconciliation:** the API says `totalJobs=221`, but its first 221 returned rows have **155 distinct IDs** in one smoke, 170 in another, and the first-page order changes between requests. The API also includes other brands (PAYONE, ANZ Worldline, MeTS). Neither the 221 count nor the 65 corporate count can be proven to refer to the same exhaustive current published set. Do not certify either as complete and do not classify all 221 as new jobs.

## Safe targeted collector

`worldline_collector.py` obtains the first-party corporate count, reads a bounded API snapshot, deduplicates IDs without pretending a complete inventory, excludes any record not exactly branded `Worldline`, and requires structured `jobLocationShort` entries exactly `Italy-Milan` or `Italy-Rome`. It then fetches the official detail page and verifies publisher host, numeric requisition ID, and title parity **before** recording a job. It returns `coverage=PARTIAL` by design with a clear reason, the official corporate inventory count of 65 and audit measurements for API count/unique IDs.

Live check (GitHub Actions `ATS Worldline - Official SuccessFactors Contract`, see PR #22):

- Corporate source visible results: **65**
- First-party public search API: **221 rows, 155 unique IDs observed** in run
- **11** Milan/Rome official job details individually checked and retained, no duplicate requisition IDs.
- Result `coverage=PARTIAL`, not VERIFIED.
- 9 targeted regression tests and general repo validation green.

Examples from validated first-party links:

| Role | Location | Official source |
|---|---|---|
| Business Development Manager | Milan / Rome | https://jobs.worldline.com/job/Business-Development-Manager/305176-en_US |
| Internship - Business Development (M/F) | Milan | https://jobs.worldline.com/job/Internship-Business-Development-%28MF%29/305812-en_US |
| Internship - Agents Network Support (M/F) | Rome | https://jobs.worldline.com/job/Internship-Agents-Network-Support-%28MF%29/305776-en_US |
| Internship - Sales Enablement (M/F)) | Rome | https://jobs.worldline.com/job/Internship-Sales-Enablement-%28MF%29%29/305775-en_US |

These are official observed openings, **not** recommendations or complete Worldline results; the user must decide eligibility, seniority and interest after the semantic evaluation.

## Controls and next technical debt

Exact Italian-city matching prevents `Romania` from being mistaken for `Roma`. Brand filtering excludes PAYONE and affiliates. Malformed or inaccessible official detail pages are not emitted as fabricated jobs. Source remains PARTIAL in every run so absence of a row from the unstable API cannot be treated as a certified absence from the publisher. Future work should reconcile the dynamic SuccessFactors React widget's published inventory to `viewalljobs` and the legacy `recruiting/v1/jobs` endpoint.

No changes to `job_watch_rules.json`, `companies_job_watch_v2.json`, company geography, existing candidate decisions, semantic memory, schedules, Worker SELECT/APPLY or historical first_seen fields. Canonical collection is the only writer for first_seen.
