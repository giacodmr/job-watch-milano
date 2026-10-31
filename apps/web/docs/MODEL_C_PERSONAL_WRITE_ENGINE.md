# Model C PERSONAL Write Engine — PR #41

## Status and boundary

This is a **local synthetic laboratory only**, with default-OFF write gate.
It does not implement identity authentication, remote access, UI actions, GitHub synchronization, a remote D1 database, a deploy or automated applications.
`APPLIED` is an explicitly user-recorded status, never an actual application submission.

## Architecture / ADR

The existing PERSONAL imported tables are authoritative for **GitHub provenance**, not for later local user edits.
`personal_heads.revision`, imported event hashes, digests, assessment fingerprints, reconciliation rows and receipts remain unchanged by APP commands. Overwriting `personal_decision_current` would corrupt this contract.

Migration `0003_app_write_engine.sql` adds four APP-owned data structures in **PERSONAL only**:

- `personal_app_job_state`: current per-owner/per-job decision and SAVED override, each with a "touched" bit and a monotonic **local job revision**. Decision `NULL` with `decision_touched=1` is explicit revocation, not an enum member.
- `personal_app_events`: immutable event log, previous/next values, server timestamp, operation id, reason and source `APP`.
- `personal_app_operations`: immutable durable owner+key receipt, hash of the canonical validated command, serialized result and event reference.
- `personal_app_owner_epochs`: owner-wide monotonic cursor invalidation token. Separate from imported revision.

A transactional CHECK guard `personal_app_cas_guard` forces D1 to abort a batch when an upsert's conditional UPDATE affected zero rows. This is necessary because a conditional upsert alone is not a reliable CAS assertion.

### Effective-state precedence

If APP has ever explicitly changed a decision, its nullable decision wins over any imported decision. Otherwise the imported decision is read. Likewise, if APP has ever toggled SAVED, its active bit wins over imported SAVED. APP and imported histories remain distinct. A later import cannot override an APP decision; a future reconciliation/sync protocol must explicitly resolve that priority.

APPLICATION and DISMISSED remain imported references and are not modified. Assessments remain imported, unchanged. Both APP-only catalog identities and existing imported PERSONAL references are included in personal lists and composite overlays. APP-only captures have `null` provenance fields rather than invented GitHub SHAs.

### Optimistic concurrency and atomicity

The first APP command requires `expectedRevision=0`; each accepted command increments the **job-local** APP revision once, regardless of command type. A stale revision returns `409 REVISION_CONFLICT`. Different jobs do not conflict just because they share an owner; owner `appEpoch` advances once per committed command to invalidate list cursors.

One D1 `batch()` transaction contains state upsert with revision predicate, CAS assertion, immutable APP event, idempotency receipt and owner epoch update. An error rolls back everything; tests inject a SQL trigger failure midway through the batch. There are no cross-CATALOG/PERSONAL transactions.

The server first checks CATALOG's currently published checkpoint and the permanent job identity. If an optional observed `catalogRevision` differs, it rejects the command before writing. A CATALOG publication racing after the local PERSONAL commit cannot undo the already committed personal state. Clients must treat subsequent CATALOG changes as a separate read conflict, not an unsuccessful save.

### Idempotency and retries

Each command requires a fresh UUID v4-style idempotency key. The server hashes the command kind and canonical validated fields and stores the resulting response under `(owner_id,operation_id)` in PERSONAL. Same key and canonical command yields HTTP 200 with `replayed=true` and no new event. Same key with different payload returns HTTP 409 `IDEMPOTENCY_KEY_CONFLICT`. A retry after a lost response uses the **same** key. D1 unique constraints and transaction serialization protect competing identical requests; after a failed batch, the writer checks whether a competing attempt committed a receipt before returning a CAS conflict.

A new idempotency key indicates a new user command even if the desired value matches the prior value; it creates a new auditable event and revision. A future UX may choose to suppress semantically unchanged commands client-side.

## HTTP contract for PR #42

Everything below is available only at the local synthetic loopback Worker with `MODEL_C_LOCAL_API=synthetic-only`. `MODEL_C_LOCAL_WRITE=synthetic-only` must additionally be provided explicitly **only** to a local synthetic test runtime. The checked-in Wrangler configuration does not enable this gate.

- `GET /api/model-c/personal/capabilities` → `{writeEnabled: boolean,productionAccess:false}`.
- `POST /api/model-c/personal/commands/decision`
- `POST /api/model-c/personal/commands/saved`

All POSTs require `Content-Type: application/json`, `Origin` equal to the loopback request origin, no query string, a valid server-side `MODEL_C_TEST_OWNER` and a JSON body no larger than 4096 bytes. The browser cannot choose an owner. No permissive CORS or client credentials. POST requests always use `Cache-Control: no-store`.

Decision example:

```json
{"jobId":"job:<64 lowercase hex>","decision":"INTERESTED","expectedRevision":0,"idempotencyKey":"xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx","catalogRevision":1,"reason":"optional"}
```

Use `decision:null` to revoke. Other allowed statuses: `TO_REVIEW`, `APPLIED`, `NOT_INTERESTED`.

SAVED example:

```json
{"jobId":"job:<64 lowercase hex>","action":"activate","expectedRevision":1,"idempotencyKey":"xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx"}
```

To remove SAVED use `action:"deactivate"`. Decision and SAVED are independent but share the job-local revision.

201 new command / 200 replay body:

```json
{"status":"saved","replayed":false,"eventId":"app:<uuid>","jobId":"job:<64 lowercase hex>","appRevision":2,"decision":"INTERESTED","saved":true,"decisionSource":"APP","savedSource":"APP"}
```

Expected errors: invalid command 400, origin and arbitrary owner 403, disabled gate 403, unsupported content type 415, too-large body 413, missing job 404, stale CATALOG or APP revision 409, idempotency mismatch 409, unavailable context/DB 503. No private payloads or SQL errors are disclosed in error bodies.

PR #42 should: read capabilities before offering mutative controls; obtain `appRevision` from PERSONAL row (0 for imported-only) and current `catalogRevision`; generate a distinct UUID for every intentional action; reuse the key and immutable payload after network errors; on 409 refetch detail, show the new state, require user reconfirmation and use a **new** key on the new attempt; after 201/200 refresh PERSONAL detail, summary/list, and composite Opportunities page. Never infer that a successful POST was already synced to GitHub.

## Readers and cursor semantics

PERSONAL summary, filtered list, detail and batch overlay return effective decision, SAVED, `appRevision`, `decisionSource`, `savedSource`, `appEpoch` and imported provenance. Detail exposes imported `decisionEvents`, APP `appEvents` and independent assessment history. Batch overlay queries are batched (no per-row PERSONAL queries).

A PERSONAL cursor includes owner digest, imported personal revision/digest, published CATALOG checkpoint, filters and APP epoch. If a mutation changes APP epoch, old cursors return `409 CONTEXT_CHANGED`. Opportunità composite propagates the APP epoch as well.

## Schema compatibility and importer

The PERSONAL schema is version **3** after additive migration 0003. Reader and importer both explicitly require v3. No old migration is changed, and migration ledger hashes are retained. Schema v2 is intentionally rejected by v3 readers and importer until the additive migration is applied. Importer's input tables and digest still refer exclusively to imported state; APP tables are not imported or included in GitHub hashes. A later import still replays the imported projection without mutating APP facts.

The importer remains responsible for CATALOG publication and its receipts. An APP event is **never** a `VERIFIED` GitHub receipt and never increments imported `personal_heads.revision`.

## Verification

Required: `npm run check`, `npm run worker:check`, integration tests with real Miniflare Worker/D1, schema migration replay, import/replay regression, concurrency, rollback injection, owner isolation, filtered cursors and security gates; both GitHub workflows must be green before merging. No remote bootstrap or deploy is authorized.

## Limitations / future sync

There is no production identity or permission model, no cross-database transaction, no GitHub/Python reverse sync, no UI mutations, no attachment/notes/interview features and no remote writes. A future explicit reconciliation protocol must avoid treating APP overrides as imported events or changing their provenance. The local synthetic gate is a security *test boundary*, not production authorization.
