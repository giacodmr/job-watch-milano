# Milestone #42 — PERSONAL Actions UI / PR #43

Based on merged milestone #41 (42cc64ef). This milestone's sole GitHub PR is #43; GitHub PR #42 was closed as a duplicate.

## Contracts

Read-only capability discovery already exists: GET /api/model-c/personal/capabilities; the UI is read-only unless the server confirms writeEnabled=true. Decision changes use POST /api/model-c/personal/commands/decision with kind DECISION, jobId, catalogRevision, expectedRevision, operationId, decision and reasonSummary. Saved changes use POST /api/model-c/personal/commands/saved with kind SAVED, jobId, catalogRevision, expectedRevision, operationId and active. Decision revocation is null. APPLIED is a declaration, not an ATS application.

Each command binds the published CATALOG revision and the job-local APP revision, not the imported PERSONAL revision. The server returns HTTP 200 with a durable receipt; retry with an identical operationId and payload is idempotent. A new user intention uses a new UUID. No browser-simulated persistence.

The shared PersonalActions drawer component supports independent decision and SAVED state, an explicit APPLIED confirmation, protected pending state, conflicting-revision refresh, and a read-only fallback when the capability is missing or false. An uncertain transport outcome is preserved in per-tab sessionStorage solely for same-key retry, not as persisted application state.

After a confirmed write, the drawer re-reads its server detail and the page refreshes list/summary/overlay while preserving the open drawer. A personal list cursor is discarded after an APP owner revision changes. Imported provenance, assessments, CATALOG and GitHub receipts are untouched.

## Security

All actions remain local synthetic-only: APP_ENV=local, loopback runtime, MODEL_C_LOCAL_API=synthetic-only, default-disabled MODEL_C_LOCAL_WRITE=synthetic-only, server-owned synthetic owner. There is NO public write authentication, remote D1 write, deploy or bidirectional GitHub sync.

For development, Vite rewrites Origin only after verifying the incoming Origin is exactly the trusted local Vite origin (http://127.0.0.1:5173). The Worker still enforces strict target Origin. The browser test HTTP proxy follows the same rule. Never rewrite arbitrary or absent Origins or relax the Worker restriction.

## Verification

Contract tests validate field names, strict schemas, exact retries, conflict mapping and uncertain outcomes. Real headless browser tests exercise React -> local HTTP proxy -> Worker -> ephemeral D1 -> authoritative GET for decisions, applied confirmation, filtering, saved APP-only jobs, retry/concurrency and 409 recovery. Existing browser layout, importer and schema tests remain mandatory.

Merge gates: npm run check, repeated local migrations, npm run worker:check, Web foundation and Validate Job Watch both green on the identical final PR HEAD. No deployment.

## Handoff for the next milestone

The next milestone must treat production identity as a separate authorization project: verified identity tokens, owner mapping, tenant isolation, CSRF/origin policy at the actual domain, permission checks, real D1 migrations/backup/restore, operational quotas and rollback. A later separate project must explicitly design bidirectional APP-to-GitHub/Python synchronization, including conflict handling and provenance. None of this is delivered by the local synthetic UI milestone.
