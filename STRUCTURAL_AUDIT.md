# Structural audit before refactor — 2026-10-03

Baseline: main 720f974, including the semantic decisions subsequently persisted after PR #4. No user or semantic history will be discarded.

## Root cause analysis

1. job_watch.stage chains subprocesses with check=True. Record reconciliation can abort Amazon, manifest initialization, sync, audit and publication after successful collection. Collector workers isolate network failures, but batch loops and post-worker reconciliation do not isolate malformed jobs.
2. Reconciliation throws ordinary RuntimeError/HTTP errors for absent titles, ambiguous matches and inaccessible listings. An active user choice whose source disappeared has no representable unresolved lifecycle. Recovered rows are only written after the entire batch succeeds.
3. Input/preflight scans mix global trust failures with batch stores, derived files and optional stages. A bad JW1 file can block JW2-4. Runtime integrity requires every Amazon city VERIFIED: PARTIAL becomes a process failure even though ordinary PARTIAL sources are tolerated.
4. Audit, certify and validate_certified_run each implement completion. Manual semantic/autonomous/priority flags and timestamp copies add independent authorities. Initializing resets all flags, including non-applicable priority checks. A zero-work daily can remain false without a useful action explaining why.
5. Valid source output is published only after every later validator succeeds. A commit race resets generated files and reruns, but can discard the consumed semantic patch. No local process lock or crash-safe registry transaction exists; Actions serialization alone does not protect two local invocations or stale queued checkouts.
6. Workflow static checks find literal .py references but miss unittest module selectors, dynamic stages and invalid status declarations. Future refactors can leave stale references. Collector has active layered adapter overrides, so removing those blindly would break supported ATS; simplify wrapper plumbing separately from adapter behavior.
7. Source FAILED/UNKNOWN and missing active decisions are mixed with semantic blockers. Historical backlog is correctly separated in some metrics, but completion flags obscure that separation. Old CLOSED rows can disappear from later source inventories; history must be retained.
8. Snapshot tokens use timestamps, not source content. A source/rules change between patch validation and multiple writes is not checked at commit. JD caches and user-choice backfills also write without a transaction.

## Previous state machine

collect -> reconcile -> Amazon -> initialize false flags -> sync -> enrich -> worklist -> audit -> certify -> two validators -> publish. Every thrown error aborts all following steps. Completion is an AND of data checks and mutable manifest claims; collection success is unrelated to semantic daily completeness.

## Authorities, readers and writers

| Domain/files | Authority and writer | Readers |
|---|---|---|
| rules, batches, company union, ATS mappings | maintained configuration | collector, sync, preflight, worklist, certification |
| current_jobs_jw* | collector plus first-party reconciliation | sync, audit, worklist snapshot, certification |
| amazon_target_check | priority collector | JW2 overlay, JD enrichment, snapshot, certification |
| user_job_decisions | explicit user choices; sync only backfills known fingerprints | reconcile, sync, worklist, certification |
| semantic_decisions_jw* | validated exact-fingerprint reviews | sync; never derived from a completion flag |
| surfaced_jobs_jw* | actual user-visible reporting history | sync, worklist, audit |
| semantic_jd_cache_jw* | enrichment cache, fingerprint-bound | worklist, semantic review |
| discovery_candidates | manual staging, not automatically verified | autonomous discovery/maintenance |
| analysis_results, semantic_queue | derived by sync | worklist, audit, certification |
| daily_worklist | derived actionable projection | reviewer, enrichment, patch validation |
| daily_updates | transient snapshot-bound command | entry point consumes validated updates |
| old run_state | manual claims plus copied source timestamps | three different certification implementations |
| audit, healthcheck | derived audit/certification | user, workflow, validators |

All snapshot, registry, cache, run-state and derived writers mutate persistent JSON. Prior FULL requires all open jobs analyzed/reported; DAILY requires actionable delta analyzed/reported, search evidence and priority verification. Historical STILL_OPEN backlog alone does not block DAILY. Fingerprint changes invalidate prior review and NOT_INTERESTED suppression; APPLIED monitors updates without returning to apply-now. Rejection reasons are feedback, not hard filters.

## New responsibility boundaries

Global rules/universe/user-store trust -> isolated collection with atomic per-batch checkpoint -> isolated record/source reconciliation -> independent priority inventory -> snapshot identity from source contents/rules -> transactional review patches -> per-batch semantic projection -> worklist -> metrics -> ONE deterministic certifier -> publication even on scoped errors. Static preflight is strict CI; runtime guards classify errors and continue unaffected stages. Source losses retain UNKNOWN, never claim CLOSED without verified absence. Explicit search evidence is an input in daily_activity; manual completion booleans are retired through a one-time archived migration.

States: PENDING -> COLLECTED -> NEEDS_REVIEW -> COMPLETE/COMPLETE_WITH_WARNINGS. New snapshot or changed fingerprint returns to COLLECTED/NEEDS_REVIEW. GLOBAL_FATAL_ERROR alone produces BLOCKED_GLOBAL. Batch failures expose recovery tasks and do not block unrelated batches. Local/source failures degrade coverage and create maintenance warnings. FAILED/NOT_RUN priority requires retry; PARTIAL can certify with warnings once valid actionable work is handled.

Failure taxonomy: LOCAL_RECORD_ERROR(record), SOURCE_ERROR(source), BATCH_ERROR(batch), GLOBAL_FATAL_ERROR(global). Every error carries stage/code and applicable batch/company/job_key, plus concrete remediation. Pipeline stage reports describe execution; final health describes coverage AND functional work, never equates a green Action with complete semantic work.
