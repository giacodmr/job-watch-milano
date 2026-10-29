# UniCredit Avature ATS Coverage Recovery — 29 October 2026

## Outcome: live first-party collector VERIFIED (pre-production)

Source: https://careers.unicredit.eu/en_GB/jobsuche/SearchJobs/

The official UniCredit Group careers portal is an Avature portal with HTML-rendered job results, stable numeric requisition IDs, and explicit total/pagination. The `jobRecordsPerPage=1000` query parameter is ignored; the actual publisher returns **15 per page** and the visible legend `1–15 of 559 results`.

A separate read-only diagnostic fully enumerated **559/559 globally**, no duplicate IDs, in **38 pages**. The Italian subset is **38 postings**; the first-party `JobDetail` page for every Italian requisition has an official `City` field. A displayed country `Italy` alone is *not* used as proof of Milan/Rome.

The new `unicredit_collector.py` adapter exhausts the official 38-page global inventory, validates the total range on *every page*, checks exact ID and first-party URLs, requires 559 unique requisitions, visits *all* 38 Italian official detail pages, and parses the structured `City` field with strict Milano/Roma matching. It then rechecks the original first-page ID/title/URL/order and total. Source drift or missing City evidence causes PARTIAL, preserving only official validated rows already observed. No unverified city inferred from title, country, or description.

**Live smoke:** https://github.com/giacodmr/job-watch-milano/actions/runs/40957376773

- `coverage=VERIFIED`
- `inventory_count=559`
- `pages_exhausted=38`
- `global_ids_unique=559`
- `italian_details_checked=38`
- `italy_explicit_city_matches=35` (Milan and/or Rome)
- `stable_first_page_after_scan=true`
- 11 new UniCredit regression contracts passed.
- Repository CI: **197 tests passed**.

## Examples of observed official roles, not an endorsed priority ranking

| Official requisition | Role | Official location | Original URL |
|---|---|---|---|
| 107011 | Client Risk Management - Corporate Digital Development | Milan | https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Client-Risk-Management-Corporate-Digital-Development/107011 |
| 114748 | Network Development Specialist | Milan | https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Network-Development-Specialist/114748 |
| 87236 | Group Strategy & Benchmarking – Internship Opportunity 2026 | Milan | https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Group-Strategy-Benchmarking-Internship-Opportunity-2026/87236 |
| 112509 | Medior Delivery Lead_SAP BI / Analytics & Avature | Milan / Rome | https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Medior-Delivery-Lead-SAP-BI-Analytics-Avature/112509 |
| 107092 | Graduate Program - Client Solutions - Group Correspondent Banking | Milan | https://careers.unicredit.eu/en_GB/jobsuche/JobDetail/Graduate-Program-Client-Solutions-Group-Correspondent-Banking/107092 |

The 35 geographically in-scope roles include unrelated technical, senior, retail-sales, stage and protected-category-only requisitions; do not classify all 35 as good matches. The user-specified job filters and L.68/99 "preferred vs must" rules are evaluated downstream; source coverage and eligibility are separate.

## Scope and safety

The PR changes `unicredit_collector.py`, `collector.py` dispatcher, the UniCredit entry in `ats_mapping_jw1.json`, 11 targeted regression contracts in `test_unicredit_collector.py`, and read-only public diagnostic/CI scripts. No modification of `job_watch_rules.json`, `companies_job_watch_v2.json` location allowlist (Milan/Rome), candidate decisions, semantic memory, Worker SELECT/APPLY, schedules, or `first_seen_at` for anything not yet collected.

**Important:** Live smoke is read-only. Production coverage is only claimed after merge into `main` and canonical collector workflow commits refreshed `current_jobs_jw1.json` / healthcheck. Historical first_seen is assigned by the existing production pipeline on actual first observation, never backdated.
