# PayPal Eightfold ATS Recovery — 30 October 2026

## Outcome: VERIFIED for configured Milan/Rome scope (NOT worldwide)

PayPal's official branded career board is https://paypal.eightfold.ai/careers?domain=paypal.com, backed by public Eightfold **PCS-X**. The tenant's `robots.txt` explicitly permits `/careers` and `/api/pcsx`. No login, paid API, access-control bypass or 429 workaround is required.

- Official location-filtered JSON: `GET https://paypal.eightfold.ai/api/pcsx/search?domain=paypal.com&location=Italy&query=&start=0&num=10`.
- First-party official detail: `GET https://paypal.eightfold.ai/api/pcsx/position_details?domain=paypal.com&position_id=<id>`.
- First-party sitemap: `https://paypal.eightfold.ai/careers/sitemap.xml?domain=paypal.com`.
- The company in `companies_job_watch_v2.json` explicitly allows **Milan and Rome only**. London is not authorized for PayPal.

**Verified target-scope contract:** two stable full country/city snapshots returned `Italy count=4`, `Milan count=4`, `Rome count=0`. All four Milan IDs matched the Italy entries of the first-party job sitemap, with no extra Italy URL or missing active ID. Each of the four first-party job-detail API calls returned the same ID, title, work location, public URL and a nonempty job description. No server pagination within these location counts (4 jobs, maximum 10 per page).

This is sufficient to certify **the user's explicitly authorized Milan/Rome target geography only**. PayPal's global PCS-X search reported **312** postings in the initial inspection, while the official sitemap contained **317 job-related URLs**, including variants not recognized as canonical job paths (308 matched the strict canonical format in the full collector run). Global ID/count parity has NOT been established, and the collector must never claim global completeness based on this subset.

Live read-only verification: https://github.com/giacodmr/job-watch-milano/actions/runs/40980158787

- `coverage=VERIFIED` in **Milan/Rome only** scope.
- `inventory_count=4` **Italian target-scope inventory** (not a global total).
- Two complete stable Italy/Milan/Rome snapshots.
- Official Italy sitemap ID parity and all four detail URL/ID/title/location checks.
- 10 dedicated regression tests plus general repository validation passed.

## Official eligible-city openings (not necessarily desirable matches)

| Posting ID | Title | Official URL |
|---|---|---|
| 274922258239 | Developer/Agency Commercial Lead | https://paypal.eightfold.ai/careers/job/274922258239 |
| 274922258257 | Senior Account Manager, SMB | https://paypal.eightfold.ai/careers/job/274922258257 |
| 274922258337 | Sr Enterprise Sales, New Logos | https://paypal.eightfold.ai/careers/job/274922258337 |
| 274922258393 | Sr Account Representative, Large Enterprise | https://paypal.eightfold.ai/careers/job/274922258393 |

All four roles are based in **Milan, Milano, Italy**, and are mainly sales/commercial. Do not automatically recommend them as Strategy / Business Operations / Consulting roles, mark them INTERESTED, or infer eligibility/salary. Existing user decisions and semantic matching remain authoritative.

## Implementation and safeguards

`paypal_collector.py` directly retrieves public company-hosted JSON with bounded request size, requires published exact per-location `count` parity, unique stable numeric IDs, two matching snapshots, country-to-city ID union, all Italian job IDs matched to the official sitemap and per-job first-party details. Publisher errors, access blocks, drift, missing details, unexpected city locations or mismatched IDs cause fail-closed `PARTIAL`; no fabricated global certification.

No modifications to `job_watch_rules.json`, `companies_job_watch_v2.json`, allowed_locations, user preferences, candidate decisions, historical `first_seen_at`, semantic memory, schedules or worker SELECT/APPLY actions. Production timestamps are assigned only by the canonical collection writer following merge.
