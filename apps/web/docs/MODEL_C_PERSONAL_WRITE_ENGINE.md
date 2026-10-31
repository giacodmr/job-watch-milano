# PR #41 — Model C PERSONAL Write Engine (synthetic local only)

## Architectural decision

PERSONAL v1/v2 contains provenance-stamped, immutable GitHub-imported facts, current pointers, receipts and imported head revisions. **Do not write to or rewrite them.** V3 adds independent APP-owned structures:

- `personal_app_jobs`: owner-scoped captured **CATALOG** metadata, permitting new APP-only personal references without modifying `personal_job_refs`.
- `personal_app_events`: append-only DECISION/SAVED events; nullable decision is an explicit revocation tombstone, not a fifth decision value. The event origin is APP, not a forged GitHub commit.
- `personal_app_current`: per-(owner,job) optimistic revision and independent overrides for decision and SAVED; does not automatically conflate SAVED/INTERESTED/APPLIED/APPLICATION.
- `personal_app_heads`: owner-wide revision for invalidating PERSONAL list cursors and optimistic read consistency. Imported `personal_heads` stays unchanged.
- `personal_app_operations`: durable (owner,operationId) idempotency key, canonical command SHA256 and committed response.
- `personal_app_assert`: CHECK constraint + self-clearing trigger executed at the beginning of **one D1.batch() transaction**, testing the actual current per-job revision and operation absence before inserts.

The schema migration is **additive** `0003_app_commands.sql`, version PERSONAL 3, migration SHA tracked by the existing ledger. Existing importer still reads and hashes **only** imported `personal_* v2` facts; its version guard changes from 2 to 3, not its write plan or provenance/reconciliation logic. A new import does not overwrite the APP override.

## Atomicity / concurrent commands

`executePersonalCommand` requires a trusted server-supplied synthetic owner, an exact published CATALOG vacancy at `catalogRevision`, an existing imported PERSONAL head, and an expected **per-job APP revision** (0 for first write). It reads the imported state without modifying it, then runs a single D1 batch:

1. SQL CAS assertion (current revision and idempotency key absence).
2. APP reference capture (INSERT ... ON CONFLICT DO NOTHING).
3. Immutable APP event.
4. APP current pointer/revision (enforced by a trigger).
5. Increment owner-wide APP revision.
6. Durable idempotency record and response.

A failed assertion or downstream insert rolls back **all statements**; a concurrent loser gets 409 REVISION_CONFLICT. Competing identical-key requests: one commits, the other reads the durable response and returns `replayed:true`. Reusing a key for another payload returns 409 IDEMPOTENCY_KEY_REUSED. A replay is detected **before** the obsolete-revision check and is safe after a lost HTTP response. Server timestamps are observational only, not a cross-system precedence or authentication mechanism.

No distributed transaction is claimed between CATALOG and PERSONAL: CATALOG is validated before the batch, remains untouched, and subsequent CATALOG changes can make reconciliation pending. A committed PERSONAL transaction is never rolled back retroactively by a post-write catalog read.

## HTTP contract for PR #42

Both endpoints are POST, on the existing /api/model-c namespace:

- `POST /api/model-c/personal/commands/decision`
- `POST /api/model-c/personal/commands/saved`

Required runtime:

- `APP_ENV=local`
- hostname localhost, 127.0.0.1 or ::1
- `MODEL_C_LOCAL_API=synthetic-only` (existing read gate)
- **additional**, default-disabled `MODEL_C_LOCAL_WRITE=synthetic-only`
- `MODEL_C_TEST_OWNER=synthetic-...` from **server env only**
- physical CATALOG and PERSONAL D1 bindings
- POST `Origin` exactly equal to request origin and `Content-Type: application/json`
- <= 2048-byte body; unknown body fields rejected; no CORS credentials or cross-origin writes

Example decision JSON:

```json
{"kind":"DECISION","jobId":"job:<64 lowercase hex>","catalogRevision":1,"expectedRevision":0,"operationId":"00000000-0000-4000-8000-000000000001","decision":"INTERESTED","reasonSummary":null}
```

Use `decision:null` for a revocation tombstone. **APPLIED represents an explicit user declaration**; it does not submit any application externally.

Example SAVED JSON:

```json
{"kind":"SAVED","jobId":"job:<64 lowercase hex>","catalogRevision":1,"expectedRevision":1,"operationId":"00000000-0000-4000-8000-000000000002","active":true}
```

Success:

```json
{"status":"saved","replayed":false,"productionAccess":false,"eventId":"app:<uuid>","operationId":"<uuid>","jobId":"job:<hex>","jobRevision":2,"decision":"INTERESTED","saved":true}
```

Retries return the committed response with `replayed:true`. Error responses: `{error:"REVISION_CONFLICT"}` 409; `IDEMPOTENCY_KEY_REUSED` 409; `CATALOG_CHANGED` 409; `JOB_NOT_CURRENT` 404; `invalid_payload` 400; `invalid_json` 400; `body_too_large` 413; `invalid_content_type` 415; gate-off `not_found` 404; remote/owner/origin blocked 403; a database error `WRITE_TRANSACTION_FAILED` 503. All command responses use `Cache-Control: no-store`.

The read-only **GET /api/model-c/personal/capabilities** endpoint responds with `{writeEnabled:boolean,productionAccess:false}` behind the existing local read gate, reflecting the additional server-side write gate. The browser helper `readPersonalWriteCapabilities` validates this response. Only mutative UI controls and save/409 UX belong to PR #42, not this PR. Never infer the gate from a client-side flag. No existing button should simulate persistence. For conflicts, refresh the target job's `jobRevision`, show the new decision to the user, and create a new operationId for an intentional retry; do not silently overwrite it.

## Effective state and read-your-writes

Read functions now union imported `personal_job_refs` with APP-only job captures, avoiding duplicate identities. A decision APP override (including tombstone) takes precedence over the imported current pointer; a SAVED override takes precedence over imported SAVED only. Imported APPLICATION/DISMISSED remain independent. All lists, global filters, counts, details and bounded composite overlays use this effective state. No per-row PERSONAL HTTP queries are created.

Read responses contain `jobRevision` (0 before first mutation), owner-wide `appRevision` and `decisionSource` (APP/GITHUB/null). A PERSONAL cursor includes owner-wide appRevision and rejects it after a mutation with 409 CONTEXT_CHANGED. A row with a local APP mutation cannot be presented as imported VERIFIED; it remains PENDING unless more urgent prior CONFLICT/UNRESOLVED_REFERENCE applies.

Detail `decisionEvents` contains both APP and imported events with an `origin` discriminator. APP entries have `sourceCommit/sourcePath/sourceSha256: null`: they must **never** be displayed as GitHub-sourced. This forces the read-only client schema to permit null source fields and null decisions for revocation, without adding UI actions.

The imported `personal_heads` revision/context_digest, receipts, provenance and assessment event pointers are unchanged; fingerprint-based FIT freshness remains intact.

## Limitations and subsequent milestones

The only enabled environment is a **synthetic local laboratory**. No remote worker, real D1, production identity/authentication, GitHub bidirectional sync or public app has been activated. No cross-database transaction is claimed. The importer does not ingest APP events; the future explicit synchronization workflow must carry them with idempotent external receipts, ordering and conflict handling.

PR #42 will add a server-confirmed write capability endpoint, React command client, accessible decision/SAVED controls, APPLIED confirmation, conflict dialogs, pending state and read-your-writes browser E2E. It must preserve the #39/#40 layout, and must not weaken the server ownership boundary.

Testing: `npm run check`, `npm run worker:check`, migration/backup, all importer/read-only regression tests and `model-c-personal-write.test.ts` (live Miniflare D1, real Worker, atomic failures, concurrency and owner isolation). No write gate in normal Wrangler configuration.

## Archived PERSONAL captures

A known permanent CATALOG identity that is no longer a current vacancy may still have an existing owner-bound imported `personal_job_refs` capture. Such a job can receive an APP decision/SAVED command using its original captured title, URL, lifecycle and immutable provenance; the writer verifies current CATALOG checkpoint and permanent identity and never fabricates a capture. An unknown job or a different owner's archived capture is rejected. The imported capture is never edited. This protects historical Candidature entries after a vacancy closes.
