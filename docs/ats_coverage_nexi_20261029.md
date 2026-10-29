# Nexi ATS Recovery — 29 October 2026

## Status: 1 important first-party Italy role recovered, source remains PARTIAL

Official Nexi board: https://fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs

The Oracle Recruiting Cloud Candidate Experience `CX_1` endpoint returns **85/85 unique global requisitions** (consistent published `TotalJobsCount`), but for four Italian roles both listing cards and structured per-ID Oracle CE JobDetail still report only `PrimaryLocation: Italy`, `PrimaryLocationCountry: IT`, with no secondary location.

The official documented detail resource `/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?finder=ById;Id=...,siteNumber=CX_1` can return each requisition's publicly published `ExternalDescriptionStr`. The collector checks official provider host/site, exact stable requisition ID and title, and the role-specific wording (not the company address, generic Milan mentions or internal JD) before assigning a city.

Read-only Nexi Oracle public evidence:
- 3174 — **Graduate Program IT & Technology - Italy**: Italy country-only; no proof of Milan/Rome role location.
- 3847 — **Product Manager - ECR (Electronic Cash Register)**: the *official external JD* explicitly states **“In this role based in Milan”**; documented role-specific evidence. Official job link: https://fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/3847
- 4027 — **Opportunità Nexi Group - Categorie Protette (Legge 68/99)**: Italy country-only; pipeline/talent-pool posting with no target city proof; no eligibility assumed.
- 4065 — **SME Field Sales Specialist (Verona-Vicenza-Padova)**: explicit title/description outside the target perimeter; Oracle structured metadata still Italy-only, so remains unproven for full geographical certification.

## Implementation

New `nexi_collector.py`: `confirmed_target_city(raw,selected_host,site)` returns Milan/Rome only when the public Oracle detail is exactly matched by **ID and title** and (1) the detail structured location names Milan/Rome, or (2) `ExternalDescriptionStr` includes an explicit expression such as `In this role based in Milan`, `this position is based in Rome` or `Location: Milano`. It never uses mere mention of headquarters, customer markets, general corporate locations or ambiguous country metadata.

The existing global `collector.py` Oracle inventory enumeration remains unchanged; only the Nexi-specific, country-only Italian branch enriches candidates from their official public details. All other companies, location policy and downstream eligibility rules are unchanged.

**Live read-only test**: https://github.com/giacodmr/job-watch-milano/actions/runs/40963219694

- Oracle global count: **85/85** unique requisitions.
- `coverage=PARTIAL` because **3** country-only postings remain unresolved.
- Official first-party, role-specific verified Milan opening: **Product Manager - ECR (ID 3847)**.
- **9** new unit tests passed: explicit role city, false-positive headquarters, generic location mention, ID/title parity, country/host failure, and global count with partial result.
- Repository-wide validation successful.

## Scope, memory and publishing

This is a genuine partial coverage recovery, **not** a forced status flip to VERIFIED. An unresolved Italian country-only requisition is not silently categorized as outside Milan/Rome. Do not pre-mark as interested, applied or eligible without the normal semantic decision logic. The user explicitly excludes some companies (e.g. Campari, KPMG, Life Sciences), no changes to any company decisions or exclusions.

No changes to `job_watch_rules.json`, `companies_job_watch_v2.json`, allowed_locations, user statuses/decisions, historical `first_seen_at`, semantic queues, workflow schedules or existing automation rules. Canonical `Collect Job Watch vacancies` must be run after merging to persist the source and first_seen for newly observed requisition 3847.
