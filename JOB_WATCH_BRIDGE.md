# ChatGPT Job Watch bridge

This bridge lets a ChatGPT task use the repository's existing semantic worker without
assuming that the ChatGPT container can clone GitHub or reach ATS endpoints directly.

It is intentionally enabled only on `refactor/job-state-simplification` during the
pilot. It does not merge `main`, create schedules, change business rules, or replace
ChatGPT semantic judgment with deterministic scoring.

## Protocol

Requests are small JSON files committed to:

`.job_watch_bridge/requests/<request_id>.json`

A push of exactly one request starts `.github/workflows/chatgpt_job_watch_bridge.yml`.
The workflow shares the `job-watch-state-writer` concurrency group with the existing
state writers.

### 1. Select

Example:

```json
{
  "version": "1.0",
  "request_id": "pilot-20261007-amex-26014697-select",
  "action": "select",
  "batch": "jw1",
  "limit": 1,
  "fetch": true,
  "expected_job_key": "American Express::26014697",
  "expected_fingerprint": "800a57fabae4cb1e"
}
```

The runner executes `semantic_worker.py select ... --fetch`. The full packet, including
the just-in-time public JD, is never committed. It is emitted between
`CHATGPT_PACKET_BEGIN` / `CHATGPT_PACKET_END` in the Actions job log and uploaded as an
Actions artifact with one-day retention. The select receipt includes a SHA-256 of the
exact packet bytes.

If the expected identity/fingerprint does not match, or the JD fetch fails, the run
fails and no semantic state is changed.

### 2. Apply

ChatGPT reads the packet, performs the semantic review, and commits one apply request:

```json
{
  "version": "1.0",
  "request_id": "pilot-20261007-amex-26014697-apply",
  "action": "apply",
  "batch": "jw1",
  "parent_request_id": "pilot-20261007-amex-26014697-select",
  "packet_sha256": "<sha256 from select receipt>",
  "patch": {
    "batch": "jw1",
    "snapshot": {"...": "..."},
    "semantic_decisions": {
      "American Express::26014697": {"...": "..."}
    }
  }
}
```

The bridge accepts at most five decisions and passes the patch to
`semantic_worker.py apply`. Snapshot, fingerprint, ownership, historical-evidence,
seniority, protected-category and semantic-field guardrails remain enforced by the
existing worker/code.

The runner then executes the standard validations from `MAINTENANCE.md`, performs a
second sync stability check, removes the processed select/apply request files, commits
the validated state, pushes only to the triggering branch, and verifies the remote SHA.

The apply receipt reports pending counts before/after and the verified remote commit
SHA. Worker processing does not create surfacing history.

## Replay, stale requests and cleanup

- `semantic_worker.py apply` remains replay-safe through its existing patch receipt.
- A stale snapshot or changed fingerprint fails before publication.
- Exactly one request file must be changed by the triggering commit.
- The workflow ignores bot-authored cleanup/publication pushes, preventing loops.
- Select requests remain in the branch until their matching apply succeeds; the apply
  commit removes both request files.
- Full JD text exists only in the transient Actions log/artifact, never in repository
  state or a new JD cache. Artifacts expire after one day.
- Failed runs preserve only temporary diagnostic artifacts for two days.
- No credential is accepted in request JSON; GitHub's built-in token is used only by
  Actions for the branch push.

## Pilot success criterion

For the first pilot, one selected vacancy must complete the entire sequence:
request push -> Actions select -> ChatGPT packet read -> real semantic decision ->
Actions apply -> sync/validation -> verified remote commit -> next select excludes the
completed vacancy.

Only after that manual end-to-end pilot should the recurring Worker prompt be changed
to this protocol and a scheduled Worker task be activated.
