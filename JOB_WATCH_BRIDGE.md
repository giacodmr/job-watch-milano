# ChatGPT Job Watch bridge

This bridge lets a ChatGPT task use the repository's existing semantic worker without
assuming that the ChatGPT container can clone GitHub or reach ATS endpoints directly.

It is intentionally enabled only on `refactor/job-state-simplification` during the
pilot. It does not merge `main`, create schedules, change business rules, or replace
ChatGPT semantic judgment with deterministic scoring.

## Protocol

Requests are small JSON files committed to:

`.job_watch_bridge/requests/<request_id>.json`

A push of exactly one added/modified request starts
`.github/workflows/chatgpt_job_watch_bridge.yml`. A cleanup-only deletion is a no-op.
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
the just-in-time public JD, is never committed and is not printed to the Actions log.
It is uploaded as an Actions artifact with one-day retention. ChatGPT retrieves the
run artifact through the GitHub connector, downloads the ZIP and reads
`job-watch-packet.json`. The log contains only the compact select receipt, including a
SHA-256 of the exact packet bytes.

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
existing worker/code. `packet_sha256` is carried as a traceability receipt; it does not
replace the authoritative snapshot/fingerprint validation performed by `apply`.

The runner then executes the standard validations from `MAINTENANCE.md`, performs a
second sync stability check, removes the processed select/apply request files, commits
the validated state, pushes only to the triggering branch, and verifies the remote SHA.

The apply receipt reports pending counts before/after and the verified remote commit
SHA. Worker processing does not create surfacing history.

## Replay, stale requests and cleanup

- `semantic_worker.py apply` remains replay-safe through its existing patch receipt.
- A stale snapshot or changed fingerprint fails before publication.
- Exactly one added/modified request file is accepted per triggering commit.
- Cleanup-only deletion commits are recognized as no-op runs rather than failed jobs.
- The workflow ignores bot-authored cleanup/publication pushes, preventing loops.
- Select requests remain in the branch until their matching apply succeeds; the apply
  commit removes both request files. A read-only verification request can be explicitly
  deleted after its result has been checked.
- Full JD text exists only in the transient Actions artifact, never in repository state,
  a new JD cache, or the normal Actions log. Successful packet artifacts expire after
  one day; failure diagnostics expire after two days.
- No credential is accepted in request JSON; GitHub's built-in token is used only by
  Actions for the branch push.

## Pilot verified on 7 October 2026

The manual ChatGPT pilot completed for `American Express::26014697`:

- exact key and fingerprint `800a57fabae4cb1e` selected on GitHub Actions;
- official Oracle Candidate Experience external JD fetched just in time;
- ChatGPT produced a real full-JD semantic review;
- `semantic_worker.py apply` committed one decision and all validations passed;
- JW1 semantic pending moved 41 -> 40 and total semantic pending 71 -> 70;
- the validated checkpoint was pushed and the remote SHA was verified;
- a fresh subsequent worker selection returned a Satispay vacancy, proving the Amex
  vacancy was no longer selected;
- no surfacing was written for the technical worker processing.

This verifies the manual bridge path. It still does not prove an unattended scheduled
ChatGPT Worker run: that must be tested after the recurring Worker task is explicitly
configured and authorized.

## Production gate

Only after user approval should the recurring Worker prompt be changed to use this
bridge protocol and the Worker task be activated. Before activation, set the exact
verified operational branch in both Worker and Daily prompts. Do not keep writing to a
closed PR branch and do not merge `main` autonomously.
