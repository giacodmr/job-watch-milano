# JOB WATCH — M47 atomic publication and cross-D1 recovery

**Branch status: PARTIAL IMPLEMENTATION / Gate A NOT YET COMPLETED.**
**CLOUD_VERIFIED: NO / DEPLOYED: NO / ACTIVATED: NO / Gate B CLOSED.**

## Architecture and concrete implementation

This iteration extends M46's isolated local D1 staging without exposing any
new deployable Worker route. The new modules live under `apps/web/tools/`:

- `model-c-stage-attestation.ts`: read-only, durable run/chunk receipt audit.
  Recalculates the canonical M46 run/chunk digests, checks contiguous chunk
  coverage, record counts, idempotency keys, unique record IDs and references.
  It never treats an M46 `complete` flag as proof of Git provenance.
- `model-c-trusted-stage.ts`: compares the staged **reduced** inventory to
  a complete independently replayed Git/Python snapshot, selection and
  a digest-checked offline plan. It refuses incomplete, lossy or inconsistent
  M46 v1 projections and verifies already-published replay using durable
  `catalog_runs` and `catalog_run_proofs`.
- `model-c-importer.ts`: a new *optional*, explicit `stagedPublication`
  argument is checked after the existing `verifyGitProjection`,
  `verifyProjectionProof` and `selectModelC` steps and **before**
  reservation, PERSONAL append or CATALOG publication. No remote execution
  target is enabled. Existing importer CAS/batch/guards/reconciliation remain
  authoritative, not replaced by a second importer.
- The M46 immutable `ingest:<digest>` run ID is reused as the
  `catalog_runs.id` only for this trusted local staged path. The shared ID is
  the durable binding to the published head; no new schema or migration is
  required for this first implementation.
- `model-c-import-recovery.ts`: independently re-reads head, owner-scoped
  PERSONAL receipt/reconciliation, personal revision and APP revision, then
  re-reads checkpoints to catch concurrent changes. It is a read-only
  diagnostic, not an authorization to repair or an external API.

## Explicitly separated states

1. **RECEIVING**: immutable M46 packets are present, possibly incomplete.
2. **PACKET_INTEGRITY_VERIFIED_ONLY**: canonical receipt bytes/indices match.
   This does NOT mean that Git, full snapshot or publisher has been verified.
3. **TRUSTED_STAGE_MATCH**: offline importer has independently replayed the
   full Git/Python source, recomputed selection/ledger and compared its
   conservative M46 wire projection and offline plan digest.
4. **CATALOG PUBLISHED**: preexisting `importModelC` commits all CATALOG
   mutations and the head through one local D1 batch with a CAS guard.
   When staged mode is used, the same immutable ingest ID is also the run ID
   in `catalog_head`, making a committed outcome observable after failure.
5. **PERSONAL PENDING**: CATALOG may already have committed; independent
   PERSONAL receipt/reconciliation still must finish.
6. **PUBLISHED_RECEIPTS_RECONCILED**: readback verifies CATALOG head and
   current owner-scoped PERSONAL receipt/references. This is not a claim of
   a distributed transaction or a cryptographic Git proof by the inspector.
7. **APP_CONTEXT_REQUIRES_REVALIDATION**: APP state is independent of Git
   import; current APP revision prevents claiming a fully fresh reconciliation.
8. **PERSONAL_CONFLICT / CHECKPOINT_CHANGED_DURING_READ**: fail closed.

Intermediate stages 2 and 3 are currently transient verified operations;
a standalone persistent transition journal is **not yet implemented**.
Therefore M47 is NOT complete under its full durable-state acceptance gate.

## Trust and security

M46 `catalog:stage` principal has no publication or PERSONAL capability.
The new verifier is Node-only and is invoked solely through the existing
offline importer with `executionTarget:'local-ephemeral'` and verified
owner context. No import of these helpers by a Worker entrypoint.
No user/client-provided digest alone can grant publication.

The M46 `job-watch-model-c-ingestion/1` reduced schema cannot carry full
provenance, aliases, historical PERSONAL facts, or all CATALOG fields.
M47 never publishes that reduced payload directly. It reconstructs the
FULL authoritative bundle using the verified Git adapter and publishes with
the existing full importer. A selected vacancy with unrepresentable M46
metadata (e.g. non-64-hex fingerprint or missing title) is refused, not
coerced to fit; larger inventories and continuous operational ingestion
remain blocked until a separately versioned transport solves this.

## CATALOG and PERSONAL consistency

CATALOG publication is atomic **within its one database**, via existing
D1 batch and revision CAS. PERSONAL append is a separate D1 transaction
before the CATALOG commit. PERSONAL reconciliation and receipt are a
subsequent separate D1 transaction. No rollback of CATALOG is claimed
on a PERSONAL failure. A retry of the same verified Git source can use
the preexisting importer reconciliation path. The recovery inspector
reads the durable receipt and current owner-specific checkpoints.

A Cloudflare D1 Time Travel restore is NOT an import-specific rollback;
it overwrites the selected database's later state and is not invoked here.
Rebuild and verified replay are preferred where safe. A real restore
requires separate approval and an assessment of later APP edits.

## Quota, retention and blockers

The importer continues its existing conservative 30,000 write-unit budget,
explicit extended 60,000 path and special guarded initial bootstrap policy.
The new audit performs reads but no extra persisted writes; prior M46 stage
ingestion write costs must also be accounted for in any full remote budget.
Remote account usage is UNKNOWN and therefore DENY.

M46 caps one request at 12 KiB, 16 records per chunk, 64 chunks per run and
8 immutable retained runs. Existing immutable retain triggers are preserved.
A safe terminal-run retention/GC policy is **not** delivered here; indefinite
reuse of this v1 receiver would exhaust local admission capacity.

**Not yet completed**: persistent pre-publication transition journal;
versioned complete transport beyond v1; production-sized publication
splitting or Worker Free CPU validation; full failure-injection matrix;
live quota measurement; remote auth and route testing; Cloudflare activation.

## Tests

The added test cases include Miniflare real local D1 receipt integrity
checks, tampered but digest-consistent incoming metadata, missing chunks,
replay, no-write rejection, published-run ID binding, and a failure after
CATALOG commit but before PERSONAL reconciliation followed by recovery.
Final CI results must be reported against the final PR SHA; do not treat
this list as proof that all tests passed until CI confirms it.

## Handoff

Before Gate A can be marked COMPLETE:

1. Demonstrate full E2E with service JWT staging and provenance, not only
   trusted local direct insertion in integration tests.
2. Persist distinct pre-publication phase evidence and prove restart
   recovery for all required points, including poisoned state/concurrency.
3. Resolve M46 v1 completeness/size limits with a versioned protocol.
4. Solve secure retention and full write accounting.
5. Run the complete failure matrix, get all required CI checks green.
6. Preserve Gate B CLOSED until independently authorized remote deployment.
