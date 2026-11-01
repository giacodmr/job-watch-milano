# JOB WATCH — M50 HANDOFF (NOT AUTHORIZED)

## Entry conditions

M48 merged, PR #49 M49 reviewed/merged **only after AC04/05/06/07 are genuinely resolved** and both final CI workflows pass. Gate B is CLOSED until the user separately authorizes concrete Cloudflare actions. Do not infer authorization from this document or the existence of deployment scripts.

## Operator / owner checklist

| Sequence | Requirement and verification | Responsible | Explicit approval | Potential cost |
|---|---|---|---|---|
| 01 | Owner opens/verifies Cloudflare account and current Workers Free plan; screenshot of billing settings, no credentials in GitHub | USER | YES | €0 only if Free is confirmed |
| 02 | Check live D1 account-wide rows read/written remaining, Worker CPU and requests, D1 storage; written operator attestation timestamp + daily remaining budget | USER + operator | YES | €0 read-only telemetry |
| 03 | Verify live Free quotas, request and D1 limits against official documentation, confirm zero paid fallback | Operator | YES | €0 |
| 04 | Decide hostname/private domain and DNS requirements; assess domain ownership, renewal or registrar charges | USER | YES | MAY COST — stop if nonzero |
| 05 | Create separate CATALOG/PERSONAL remote D1 only after approving exact names/IDs; confirm no new resource charge under Free | Operator | YES | Conditional Free |
| 06 | Review migration plan, schema hashes, backups, 30-day Time Travel limitations and roll-forward/restore of both D1 independently | Operator | YES | Conditional Free |
| 07 | Configure single-user Cloudflare Access app and strict owner mapping, with no workers.dev or preview route | USER + operator | YES | Verify Free availability |
| 08 | Configure distinct path-scoped Access service app with its own audience/client ID and service principal; test service denied on interactive paths | USER + operator | YES | Verify Free availability |
| 09 | Store JWT/config secret values via protected deployment mechanism, never commit tokens or personal identifiers | USER + operator | YES | €0 expected |
| 10 | Implement/certify remotely authorized trusted Git/Python publication and PERSONAL reconciliation before writes; no service-only promotion grant | Developer + operator | YES | Depends on architecture |
| 11 | Implement durable shared quota admission / confirm authoritative account usage across APP, staging, journal, migration, retention and other consumers; UNKNOWN_REMOTE_QUOTA=DENY | Developer + operator | YES | Conditional Free |
| 12 | Approve exact Worker config/hostname and perform private read-only deploy, then verify no unauthenticated asset access | USER + operator | YES | Conditional Free |
| 13 | Read-only smoke: Access identity, owner isolation, CATALOG/PERSONAL query, no side route or secret exposure | Operator | YES | Within verified quota |
| 14 | Authorize 1 small pinned Git snapshot run; stage, independent trusted verification, publish CATALOG CAS and reconcile PERSONAL | USER + operator | YES | Within verified quota |
| 15 | Verify receipts/HEAD/immutable APP event history and operator readback after an injected lost acknowledgement | Operator | YES | Within verified quota |
| 16 | Separately authorize temporary APP command gate, test 1 DECISION and 1 SAVED with CAS, idempotency, retry and readback | USER + operator | YES | Within verified quota |
| 17 | Inspect usage, errors, CPU, storage, Access logs (without PII/token logging); document rollback and disable all gates if uncertain | Operator | YES | €0 target |

**Stop conditions:** account plan is not Free, unapproved cost, quota missing, CPU unknown, unpaid hostname unavailable, Access principals not isolated, trusted publisher incomplete, anomalous D1 state, failed rollback rehearsal or absent user authorization.

## M50 copy-ready operational prompt

JOB WATCH — CLOSE M49 & START M50 PRIVATE CLOUDFLARE PILOT.

1. Operate on giacodmr/job-watch-milano, pull the actual HEAD and PR #50 status. Review M49 scope and AC01–AC11 against final commit CI. Do not mislabel remote publication, quota admission or restart as verified merely because local staging tests pass. Fix blockers on existing M49 branch; merge only if locally complete, otherwise leave DRAFT and report exact blockers.
2. Before any remote tool action, present the Gate B checklist to the user. Obtain explicit approval for the exact Cloudflare account, Free-plan scope, resource creations, DNS/hostname, Access apps, D1 databases, secrets handling and deployment stage. Ask the user to do only login/registration/identity confirmation actions that genuinely require them. Do not request secret material in chat or place it in source control.
3. Verify current official Cloudflare Free limits and the **actual** account-wide remaining quota, Worker CPU, storage, queries and other consumers. Cap internal ordinary writes at 30k/day, no automatic 60k and no paid fallback; unknown quota is DENY. Implement reliable shared admission if still outstanding.
4. Before any writes, require independently trusted Git/Python publication controller with pinned commit/manifest/ledger/projection evidence, atomic CATALOG CAS+journal, PERSONAL reconciliation and idempotent recovery. Never allow the catalog:stage service principal to promote or touch PERSONAL.
5. After explicit per-stage approval, provision distinct D1 databases and secure private Access hostname/app/service identity; apply additive migrations with verified backup and rollback procedures. No workers.dev, previews, public fallback or insecure service routes.
6. Stage 1: verify infrastructure without ingestion. Stage 2: private Access read-only smoke. Stage 3: authorize a small pinned verified catalog ingestion; inspect durable receipts and quota. Stage 4: reconcile and verify PERSONAL with APP precedence unchanged. Stage 5: separately enable APP DECISION/SAVED for a minimal approved smoke; verify CAS and idempotency, then disable or retain only by explicit approval. Stage 6: operational verification of quota, alarms, CPU, retention, privacy and rollback.
7. After each stage, stop on unknown outcome, unexpected resource cost or failed security/consistency checks. Present exact SHA, workflow results, resource IDs privately, receipts, observed rows read/written, plan cost, blockers, GO/NO-GO and the next action requiring explicit user consent. No implicit production rollout.

**Current authorization:** NONE. This document is a handoff, not permission to provision or deploy.
