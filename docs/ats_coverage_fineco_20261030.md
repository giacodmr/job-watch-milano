# FinecoBank ATS recovery — 30 October 2026

## Live result: VERIFIED — official employee careers source

Official careers page: https://about.finecobank.com/it/careers/diventa-un-dipendente/

The FinecoBank corporate career page SSR HTML contains an empty `PositionAccordion`. The first-party Next.js JS bundle explicitly calls `GET https://public-api.finecobank.com/v1/public/career/work-with-us/jobs`; another chunk maps the returned `positions.jobs` directly to the complete set of accordion job sections. A configured first-party API base `https://public-api.finecobank.com` is exported by the same official Next.js app bundle.

The endpoint's entire **unpaginated** public JSON `jobs` array returned exactly **7 postings**, with seven unique immutable-looking numeric IDs, work city `Milano`, function, experience level, timestamp, and *official company-owned* `https://finecobank.intervieweb.it/jobs/<slug>-<id>/it/` application links. Two repeated full API snapshots were byte-consistent and returned the same ID/title/location/URL metadata.

The new `fineco_collector.py` checks both complete frontend-arrays, stable unique numeric IDs, explicit work-location label, exact first-party public API host, exact company Intervieweb URL/ID parity, and fetches **all 7** official Intervieweb pages to validate response host/path and actual page title. Unsupported locale/job domains or ambiguous country-only locations fail closed; **VERIFIED** is scoped to this official *employee positions* page, not external job aggregators, financial-adviser recruitment, independent subsidiaries, or other companies.

Live source smoke: https://github.com/giacodmr/job-watch-milano/actions/runs/40978988718

- `coverage=VERIFIED`
- `inventory_count=7`
- `unique_stable_ids=7`
- `stable_full_snapshots=2`
- `target_detail_pages_checked=7`
- `complete_frontend_array=true`
- 10 new Fineco tests and repository validation passed.

## Official source postings, all Milan (not an eligibility ranking)

| ID | Title | Official job link |
|---|---|---|
| 156714 | Senior AI Engineer | https://finecobank.intervieweb.it/jobs/senior-ai-engineer-156714/it/ |
| 156616 | Digital Analytics & MadTech Specialist | https://finecobank.intervieweb.it/jobs/digital-analytics-madtech-specialist-156616/it/ |
| 139250 | Addetta/o Reclami - Tempo Determinato | https://finecobank.intervieweb.it/jobs/addettao-reclami-tempo-determinato-139250/it/ |
| 138582 | Coordinamento operativo e di controllo AML | https://finecobank.intervieweb.it/jobs/coordinamento-operativo-e-di-controllo-aml-138582/it/ |
| 128062 | Senior Application Security & DevSecOps | https://finecobank.intervieweb.it/jobs/senior-application-security-devsecops-128062/it/ |
| 122753 | Compliance Specialist - Trasparenza e Tutela Clienti | https://finecobank.intervieweb.it/jobs/compliance-specialist-trasparenza-e-tutela-clienti-122753/it/ |
| 118249 | International Project Manager – German Market | https://finecobank.intervieweb.it/jobs/international-project-manager-german-market-118249/it/ |

Digital Analytics & MadTech Specialist and International Project Manager are likely closer to the user's stated career goals, but compensation, language requirements and seniority have not yet been classified. Source coverage is distinct from user eligibility or a recommendation.

No changes to `job_watch_rules.json`, `companies_job_watch_v2.json`, Milan/Rome geography, existing statuses/decisions, semantic memory, historical `first_seen_at` or worker schedules. The canonical collector is the only writer authorized to persist new observations and assign first_seen.

## Source limitations

Only the first-party official employee portal's complete jobs array is certified, not LinkedIn postings or Indeed positions which may differ in count due to syndication and publishing schedules. A changed Next.js frontend API contract must be checked on future source-coverage diagnostics; never extend the `VERIFIED` claim beyond the exposed employee board. 
