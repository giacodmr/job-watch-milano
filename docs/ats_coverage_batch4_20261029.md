# ATS Recovery Batch 4 — 29 October 2026

## Persisted baseline before batch

`job_watch_healthcheck.json` generated `2026-10-29T20:20:05Z`: **94 VERIFIED / 113 PARTIAL / 0 FAILED / 0 NOT_CHECKED** across 207 sources. The Dojo recovery from batch 3 is now verified in persisted production (`inventory_count=24`, 0 retained under unchanged Milan/Rome filter). Revolut is VERIFIED with 57 retained roles (`315` global requisitions); Mollie is PARTIAL because its first-party corporate listing and Ashby board disagree at this snapshot.

## Checkout.com (JW1): implemented and tested

Official corporate `https://www.checkout.com/jobs` links to the checkout.com Ashby board under `https://jobs.ashbyhq.com/checkout.com/form/talent-communities`. The corresponding public posting API is `https://api.ashbyhq.com/posting-api/job-board/checkout.com`.

The corporate Webflow page is client-side populated; it is **not** a reliable source of vacancy counts. New `checkout_collector.py` instead checks that the *first-party corporate site* links to the expected Ashby posting publisher, validates each ID as UUID, checks that official `jobUrl` and `applyUrl` paths refer to the same ID and board, checks location and listing status, rejects duplicate or malformed records, filters `isListed=false` records out of advertised jobs, and compares two complete public API snapshots. Only after parity does it apply the user's unchanged Milan/Rome geography filter.

Read-only public smoke: **169 Ashby postings, 169 advertised `isListed`, all ID/path metadata verified, two identical snapshots; 0 matches in the mapped Milan/Rome geography. Coverage VERIFIED in the smoke.** This is source-coverage recovery, **not** new suitable job opportunities. Requires production collection to become a persisted 95th VERIFIED source, and remains subject to live board drift.

Evidence: GitHub Actions ATS Batch 4 public smoke (see PR #20 checks).

## UniCredit: official pagination contract resolved, implementation pending

`https://careers.unicredit.eu/en_GB/jobsuche/SearchJobs/` returns server-side HTML with **559 advertised active global jobs**, stable official `JobDetail/.../<numeric-id>` URLs, a clear range legend `1 - 15 of 559 results`, and `jobRecordsPerPage=15&jobOffset=15`, `30`, etc. Requested `jobRecordsPerPage=1000` is ignored and still delivers 15, so a complete adapter must visit **38 separate page offsets** (0 through 555) and reconcile exactly 559 unique requisition IDs. The list's `job-info-icon_world` mostly shows country (e.g. Romania/Serbia) rather than city. A future implementation must independently verify Milan/Rome membership for Italian jobs and must not certify precise geography from `Italy` alone. This batch deliberately **does not** promote UniCredit to VERIFIED.

## FinecoBank: not yet complete

`https://about.finecobank.com/it/careers/diventa-un-dipendente/` returns Next.js HTML but `__NEXT_DATA__.props.pageProps` has only `_nextI18Next`, with **no server-rendered jobs, job IDs, or verified total**. No exhaustive public contract identified. Remains PARTIAL.

## Scope and safety

Only `checkout_collector.py`, collector dispatch, `ats_mapping_jw1.json`, `test_ats_coverage_batch4.py`, and read-only CI/diagnostic files are modified. The existing Job Watch schedules, rules, company location filters, candidate decisions, user memory, source snapshots, and Worker SELECT/APPLY are untouched. No fake `first_seen_at`; production collection assigns it only to retained official jobs. An exhausted source at Milan/Rome may return 0 valid jobs and still be VERIFIED if the worldwide official publisher is demonstrably exhaustive.
