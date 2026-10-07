# ChatGPT Job Watch bridge — batch v2.0, immutable checkpoints

The bridge is enabled for request pushes only on `refactor/job-state-simplification`.
No recurring Worker is activated and no main merge or collector schedule change is made.
ChatGPT supplies the actual semantic judgment; Actions only fetches, validates and persists.

## Batch protocol

Write one request per commit under `.job_watch_bridge/requests/<request_id>.json`.
IDs contain letters, digits, underscores or hyphens and are at most 120 characters.
Process one request at a time and verify its remote checkpoint before the next request.

Select example:

```json
{"version":"2.0","request_id":"night-20261008-0200-jw1-select","action":"select","batch":"jw1","limit":10,"fetch":true,"exclude_keys":[]}
```

Both select and apply accept 1–20 records; `semantic_worker` continues to support 1–30.
A packet is scoped to one JW. The initial Worker budget is two sequential packets of
10 per scheduled run, 20 attempted vacancies overall. Optional expected_job_key and
expected_fingerprint are assertions on the first selected record, not target selectors.

Every selected record is in the same packet artifact with its complete fetched JD or
jd_error. One failed fetch no longer aborts the successful records. EMPTY is a normal
no-work result. Full JD text is not silently truncated. Do not force 20 very long JDs
into model context by shortening them; reduce packet size instead.

The select receipt includes the run ID and attempt, pinned artifact ID/name, snapshot,
exact packet SHA-256, keys, fingerprints, ready count, fetch errors and UTC creation time.
Actions uploads the packet before finalizing this metadata. Artifact names include the
run ID and attempt; an already-published SELECT skips fetching and uploading entirely. This metadata-only receipt is committed
under `.job_watch_bridge/receipts/`; no JD is stored there. It supports recovery and
finite retry cooldowns even after the artifact expires. Replaying a SELECT returns its
original receipt unchanged, regardless of later memory/source changes or expiry. It
never silently creates another packet. Expiry requires a NEW SELECT ID and fresh JD.

The packet exists only in Actions temporary storage and an artifact with one-day
retention. ChatGPT downloads it once through the connector and verifies its byte hash.
Normal and error logs must never print packet stdout, JD text or decoded JSON failures.
Failure diagnostics also expire after one day. No new versioned JD cache is introduced.

Apply example:

```json
{
  "version":"2.0", "request_id":"night-20261008-0200-jw1-apply",
  "action":"apply", "batch":"jw1",
  "parent_request_id":"night-20261008-0200-jw1-select",
  "select_run_id":123456789,
  "packet_sha256":"<exact 64-character packet hash>",
  "patch":{"batch":"jw1","snapshot":{"...":"copy exact packet snapshot"},
           "semantic_decisions":{"Company::ID":{"...":"real complete semantic fields"}}}
}
```

The runner loads the latest branch state before BOTH queued SELECT and APPLY, and
rejects changed request content. APPLY downloads the canonical artifact from the
successful select run and checks repository/branch/workflow, original request digest,
pinned artifact ID/name, SHA, packet snapshot, keys, fingerprints and selected membership.
Legacy v2 receipts without the new artifact fields remain bound to their original
run, original artifact name, exact packet hash and selected keys/fingerprints. The packet hash is now verified, rather
than merely carried as a traceability field. Expired/missing artifacts require a new select.
Protocol v1 pending requests must be regenerated with v2 and a fresh select; do not
relabel old packets as v2 or fabricate the run ID.

## Atomic persistence and partial retry

Snapshot/global/packet errors fail the whole request without publishing semantic state.
Within a valid packet, the bridge prevalidates each review with the existing semantic
guardrails and passes all valid reviews to ONE worker apply with the same all-or-nothing semantics.
Invalid/omitted reviews and failed JD fetches are listed individually in `retry`.

The worker transaction writes its own batch memory and the metadata request receipt
together in one journal. Every bridge entry recovers the journal under the writer lock BEFORE looking for
a receipt or checking snapshots. Even an interruption after memory was written and
before its receipt was written resumes as a replay, without downloading another JD. No user decision or surfacing event is created by this path. A receipt is a
published checkpoint only after its commit is confirmed on the remote branch.

The persistent apply receipt records request-content hash, accepted-patch hash,
applied keys, retry reasons and pending before. The emitted receipt additionally
contains pending after and the verified remote commit SHA. COMPLETE requests are
cleaned up; PARTIAL requests remain intact so unresolved review drafts are not lost.
Replaying the same request returns zero applications, even after the artifact expires
or a later user choice changes memory. Reusing an ID with different content is rejected.

Correct a residual review with a NEW select/snapshot and NEW apply request ID. An apply
changes its memory snapshot, so the original snapshot cannot simply be reused for the
residual. Preserve and explicitly revalidate earlier judgments; never replace hashes
blindly. The Worker reconciles and deletes older partial requests only after all their
residuals have been validly resolved. Receipts do not authorize overwriting newer choices.

For failed fetches, the Worker uses the select receipt to defer identical key/fingerprint
retries for six hours and passes `exclude_keys`; a changed fingerprint is checked anew.
The exclusion is a scheduling hint only and does not modify eligibility or semantic
priority rules. Retry outstanding work automatically, never suppress it permanently.

## Validation, publication and concurrency

Each apply runs preflight, input validation, the complete unittest suite ONCE,
`job_watch.py project`, strict state validation, a second projection/worklist stability
comparison, and diff checking. This projection does not consume `daily_updates.json`,
maintain inventories, archive roles, modify user/surfacing/activity, or change other JW
memories. Publication stages only the reviewed JW memory, four read models, its receipt
and completed-request deletions. Daily retains its existing separate sync path.
There is no per-vacancy suite or extra sync inside bridge.apply.

PR CI can reuse a successful ancestral validation only when code/static inputs have
identical hashes and the new commit contains transport metadata alone. A bot-generated
state checkpoint requires proof that the exact parent apply run completed the full
validation step successfully. Missing proof or API errors fall back to full validation.
Code/config changes always get the full suite. Occasional fallback revalidation is
intentional; the guarantee is one suite in each apply, never skipping an unproven check.

All state writers retain `job-watch-state-writer`, `cancel-in-progress: false` and
`queue: max`. The queue can still saturate, and request creation advances the branch;
the Worker therefore keeps only one request in flight and reconciles missing receipts.
Publication uses an explicit state-file set and ordinary fast-forward push, verifies
the checkpoint as an ancestor of the fetched remote branch and compares the receipt
there, and never force pushes. A later remote commit is a valid acknowledgement if
the receipt is unchanged. A lost push response is reconciled the same way. A genuine
non-fast-forward rejection fails without publishing; the request and review draft
remain in Git for a guarded retry. There is no blind generated-state rebase.
Retry a failed delivery by rerunning its Actions run with the UNCHANGED command.
If the connector cannot rerun it, a formatting-only request-file change can create a
new push without changing its canonical JSON digest. Do not increment `retry_attempt`
on an existing ID: it is command content, not a transport counter. A changed command
requires a new ID. Send one command per push; the workflow reads the complete push
range rather than silently ignoring requests in earlier commits.
Only dependencies use a pip cache; full JDs never do. Select still fetches sequentially;
bounded HTTP concurrency is deferred until real per-host timings justify it.

## Agreed night schedule — not activated

- One **Job Watch Worker** task: **02:00, 03:00, 04:00, 05:00, 06:00 Europe/Rome**.
- Maximum **20 attempts/run**, normally two packets of 10: up to **100 attempts/night**,
  across all JW combined, without automatic budget extensions. Stop early when there
  is no selectable work. Actual saved reviews depend on successful fetch/validation.
- One existing **Job Watch Daily** task: **09:00 Europe/Rome**.
- Proposed collector ordering: **00:30**, recovery **01:15**, before the first Worker.
  Current collector schedules remain **06:30/07:15** until an explicit operational
  switch. Keeping them means overnight work uses the previous collection; a long-running
  06:00 Worker can still overlap collection. A new morning collection can also obsolete
  Daily activity certification until the reporting runner uses the fresh snapshot.

The durable Worker prompt is `CHATGPT_WORKER_PROMPT.txt`. The single handoff document
`CHATGPT_HANDOFF_E_RICORRENZE.md` includes the context and both recurring-chat prompts.
No schedule was activated or merged by this change. The manual v2 pilots saved
10/10 and 18/20 reviews, reducing pending 70→60→42; two failed fetches remained pending.
A SELECT replay exposed receipt replacement. The canonical 10-record receipt is
restored byte-for-byte from commit `c0cf97a9e67ffdf0fdfc802869f57de6d7896cb3`, checked
against its APPLY receipt; the erroneous replay remains visible in Git history. No
semantic/user/surfacing decision is changed by this repair. These corrections still
require a live ChatGPT batch/replay pilot before authorizing unattended operation.
Durable slot budgets/claims, automatic inbox reconciliation and uniform JD identity
hardening remain separate work; the current task prompt supplies those scheduling
constraints. These changes do not certify an unattended night run.

## Timing model to measure

The observed v1 pilot was ~12s select/fetch and ~40s apply/validation/sync/push.
Do not multiply the one-off ~20-minute bridge development session by vacancy count.
v2 adds an original-artifact download and a small select-receipt commit; measure those.
Keep separate select, model review, transfer, apply, queue time, failures and retries.
A planning range was 5–13 min for 10 and 8–24 min for 20 including model work, not a
benchmark or an SLA. Two 10-record checkpoints trade an extra apply setup for earlier
persistence and smaller model context. Do not claim throughput until live measurements.
