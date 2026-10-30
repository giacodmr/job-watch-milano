# Model C / PR 3 — incremental importer, local and inactive

Base analyzed: `254c22965ce83da17d0d8565796a3b757fbc3861` (PR #32). Dedicated branch `codex/model-c-incremental-importer`. V1 remains the active path. No binding, route, UI, Python engine, V1 importer/reader, production workflow, dependency, deployment or persistent database changes.

## Entry points and trust boundary

`tools/model-c-importer.ts` exports the Node-only `importModelC(catalog, personal, options)` service. Both databases must already have the separate Model C schemas. There is deliberately no persistent-database CLI or HTTP ingestion endpoint. The only executable harness, `node tools/model-c-import-lab.mjs`, accepts no arguments and creates exclusively synthetic Git repositories and ephemeral Miniflare D1 databases (`cf:false`, no persistence).

Options require a repository, full 40-character commit, opaque owner, UTC budget day and trusted daily allocation ceiling. An empty destination requires explicit `bootstrap:'empty-target'`; migrating V1 instead requires `v1` pointing to its separate, confirmed source database. V1 is read only. Model C role/version checks reject sharing a database. This is a trusted local administrative API, not an authentication mechanism or a remote feature.

`tools/model-c-git.ts` verifies origin repository, resolves the authorized `origin/main` tip once, checks commit ancestry against that tip and the confirmed prior observation, rejects symlinks/submodules, and hashes original Git blobs with exact byte lengths. It verifies the complete V1 manifest scope, including tracked archives/receipts. It replays the existing exporter in a temporary private Git archive, compares the entire envelope if supplied, and binds all tracked Python/JSON/JSONL, actual shared/tools implementation bytes, runtime versions and selection context to the existing projection proof. Hash preimages remain in memory. The source working tree is never used for operational JSON. Remote refs are not automatically refreshed; a trusted caller must fetch before invoking the API.

The complete permanent ledger is read with head/run/content/checkpoint in a single D1 read batch. Its canonical digest and both counts must match the ledger checkpoint reached from the PUBLISHED head. Prepared rows cannot become a trusted checkpoint. An empty head with preexisting application rows is refused. The existing selector determines identities, aliases, lifecycle and selection; the importer introduces no matching or ranking rules.

For V1 migration, all identities/aliases and company/source identity rows must have confirmed version/membership evidence. Unconfirmed identities or personal facts are refused rather than silently omitted. Original decision/review IDs are checked, all confirmed historical personal facts and bounded captures are copied, including facts absent from the newest Git projection. Immutable summaries, provenance and alias resolution labels are retained. There is no timestamp-based reconstruction of effective user choices.

## Delta and atomic publication

Company/source/current-vacancy payloads are compared field by field excluding provenance. Unchanged rows keep their original origins, including separate ATS configuration and coverage proofs. `needs_analysis` is independent of kind: an OPPORTUNITY may also belong to AI_QUEUE. Company config/tier/priority/membership and nullable technical flags are preserved.

New identities and aliases are permanent. New aliases on existing IDs use IDENTIFY_ONLY staging when no payload changes. REMOVE is generated exclusively for a previously current payload absent from the complete verified selection; no identity, alias or personal fact is removed. Company/source current removals are ordered after vacancy mutations to satisfy FKs.

The bounded plan is staged, checked and promoted in **one `catalog.batch()`**:

1. Assert expected sync revision with the existing aborting CAS guard.
2. Insert any new content/ledger revisions, run, proof metadata and deduplicated origins.
3. Write typed delta staging and a digest/count chunk marker, assert exact stage cardinalities, and seal READY.
4. Extend identities/aliases; UPSERT current rows from sealed staging; apply authorized current removals.
5. Advance head; existing triggers atomically publish the run and append audit.

Putting staging inside the same transaction avoids immutable orphan revision numbers after crashes or competing plans, without replacing the schema. No current mutation is committed before publication. Incomplete staging, late SQL failures or losing CAS roll back the entire batch. The existing statement/chunk schema is reused; its chunk is an internal delta marker, not a changed V1 transport contract. No chunked publication exists.

The local guard rejects plans above **8,000 statements or 8 MiB of serialized SQL/parameters** before reservations or target writes. These are deliberately bounded local limits, not demonstrated Cloudflare production limits. A large bootstrap can fail admission and requires a separate, reviewed capacity solution; this PR does not evade limits by publishing fragments.

Observed commit, projection input digest, content origin/revision, ledger revision and sync revision remain distinct. A new commit with identical functional selection advances only observation/sync metadata. Exact replays reverify Git/Python/proof and PERSONAL context but write zero rows. The saved environment digest excludes only selection-context digest so that changing from bootstrap to the now-confirmed equivalent ledger does not manufacture a new observation on the first replay. Full verified proof/context is always computed; no verification is skipped.

## PERSONAL, receipts and recovery

Every existing capture, including inactive references and assessment history, must resolve against the full permanent ledger. Unknown references stop the import. Active SAVED/APPLICATION/DISMISSED facts are read directly from PERSONAL, across the complete context, and supplied to the existing selector. Existing personal decisions with an unresolved projected effective choice fail closed.

Before publication, new original Git decision/review facts are appended once and captures are inserted only when missing. Existing captures, reference states, current-event pointers and historical facts are never overwritten or deleted. V1 import therefore preserves event history without inventing a production CRUD API or choosing effective pointers. Personal head/audit advance only for actual new facts. References awaiting the next publication are marked PENDING first.

PERSONAL append and reconciliation batches assert the complete read context in SQL, grouped below 80 bound parameters per statement; count assertions detect phantom inserts. This prevents silently overwriting concurrent PERSONAL writes. The catalog transaction has its own CAS. There is **no cross-database transaction**: after catalog publication, a separate read verifies the actual head and ledger before writing immutable receipt and VERIFIED reconciliation at the current personal revision.

A crash before catalog commit leaves the prior confirmed catalog intact, possibly with additional durable personal facts/PENDING reconciliation. A crash after publication leaves catalog confirmed and reconciliation/cleanup retryable. Retrying recognizes that run, appends no duplicate facts, does not republish, and completes only missing receipt/reconciliation/cleanup work. Old receipts are historical assertions: a consumer must compare receipt head/revision with the actual CATALOG head, as specified in PR #32; the local PERSONAL view alone cannot prove freshness. Concurrent changes between databases can leave stale receipts; the next verification must detect this, never assume distributed atomicity. Remote concurrent writers/cutover remain disabled.

Cleanup deletes only staged aliases/vacancies/sources/companies and chunk markers for PUBLISHED/ABORTED runs, in FK order. It retains origins, runs, revisions, proof metadata, receipts, ledger, events and audit. No retention of permanent history is implemented.

## Write admission and measurements

Additive CATALOG migration 0003 adds shared write reservations and immutable run proof metadata/assertions. PERSONAL migration 0002 adds the aborting context assertion. Earlier migrations remain byte-for-byte unchanged. These migrations are applied only in ephemeral tests/harnesses in this PR.

The shared daily ledger admits at most **30,000** charged row writes, or **60,000** only with `extendedAuthorized:true` and a sustainable available allocation supplied by the trusted caller. The UTC day must match the current UTC day. The allocation must already account for other account workloads; the local ledger is not an account-wide Cloudflare meter and cannot automatically see unrelated writers.

Admission bounds include every planned table/index write, replacement index entries, all known trigger side effects, identity/alias extension, staging, current mutation, checkpoints/head/audit, PERSONAL append, assertions, receipts, cleanup and reservation accounting itself. Index counts come from the pinned local schemas. CAS, budget and assertion trigger writes are explicit. The complete bound is reserved atomically before the first PERSONAL/catalog mutation. Insufficient admission rolls back the reservation. A successful reservation is never reclaimed: crashes, uncertain outcomes and retries cannot accidentally recover allowance already potentially consumed. This is deliberately conservative and may reject operations whose eventual actual writes would fit.

Actual per-phase costs come separately from successful D1 `meta.rows_written`, including index/trigger effects reported by the pinned Miniflare build. Error objects contain only redacted codes and successfully observed metrics; the failed batch's actual billing is unavailable, so its reserved bound stays charged. Local elapsed time and serialized plan size are diagnostics, not remote CPU/billing evidence.

See [MODEL_C_IMPORTER_METRICS.json](MODEL_C_IMPORTER_METRICS.json) for reproducible synthetic synchronization costs, including bootstrap/replay/unchanged observation/minimal and broad delta/alias/removal/PERSONAL/V1 migration/cleanup recovery. Schema setup, fixture seeding and reads are excluded and explicitly labeled; these are actual importer runs, not empty-schema costs. The broad delta changes 120 of 120 synthetic vacancies; it is not a claim about production cardinalities or account sustainability. No real data was imported or measured. Empty-schema/restore costs belong to the earlier schema laboratory and must not be confused with these measurements.

## Verification and remaining gates

Local validation: **109 tests in 9 files PASS**, including **21 importer tests**, TypeScript strict/build PASS, Worker dry-run PASS and isolated V1 migration replay PASS. Node 24.15.0 / Python 3.14.2. The closed synthetic laboratory also passed; the final full-suite run regenerated the checked-in phase metrics.

Commands: `npm ci`; `npm run check`; `npm run worker:check`; `node tools/model-c-import-lab.mjs`; `git diff --check`. V1 migration CLI is checked twice only in a disposable temporary fixture directory, never against the workspace database. Test results and CI are recorded in the PR on its final head.

Synthetic importer tests cover bootstrap, zero-write replay, unchanged commit observation, code-only invalidation, minimal/broad delta, alias extension, removal, OPPORTUNITY+AI_QUEUE, DISMISSED and historical PERSONAL facts, V1 history migration and unconfirmed-source refusal, bad hashes/proof/runtime, ancestry/divergence, unsupported Git modes, incomplete ledger, missing personal identity, incomplete staging, insufficient/shared/extended budget, late rollback, concurrent CAS, concurrent PERSONAL writes, oversized atomic plans and recovery before receipt/after cleanup failure. Existing V1/schema/restore tests remain active.

Ready for an independent technical review of this local inactive implementation after checks on the final head. **No authorization for cutover, cloud, deployments, production writers or new readers.** Remaining gates include realistic private workload capacity/cost measurement, remote batch/CPU/body limits, account-wide quota coordination, immutable runtime/artifact authentication, consistent new-reader integration and independently reviewed backup/restore/cutover. Keeping V1 active remains the rollback path; no destructive reverse migration is proposed.
