# Model C PERSONAL Reader — inactive, trusted-owner scoped

Base: `18e1cfddf30684973d4076f10a92a75dfc6c7cb5` (PR #36 squash).
This change adds an **unwired**, read-only service in `worker/data/model-c-personal.ts`.
No Worker API route, active authentication, remote D1 binding, schema migration, writer,
V1 reader or UI changes. Synthetic ephemeral Miniflare D1 only.

## Contract

The functions `getModelCPersonalSummary`, `listModelCPersonalJobs`, and
`getModelCPersonalJob` receive physically separate CATALOG and PERSONAL D1 databases,
plus a **trusted server-supplied ownerId**. They do not authenticate the owner:
**never expose these functions to an untrusted request parameter**. A future server-side
adapter must verify the caller identity, derive the ownerId from that identity, enforce
the authorization boundary and select the correct PERSONAL database.

All personal SQL filters by ownerId and stable jobId, preserving historical captures,
decisions, event history, assessments, SAVED/APPLICATION/DISMISSED references and nullable
fields without inventing effective decisions. Pages are bounded to 50 and keyset-cursor
scoped by owner digest, PERSONAL revision **and context digest**, and CATALOG run/revision.

CATALOG supplies only the published ledger membership, current visibility and latest
confirmed head. PERSONAL retains private facts and its own head. For each reference,
reconciliation is VERIFIED only when its PERSONAL revision is current and its receipt
matches **all** of CATALOG sync/content revisions, observed commit, ledger digest and
canonical expected head digest. The receipt is a trusted imported database fact, **not an independent cryptographic signature**; the future adapter must enforce server-side trust and authorization. Missing, mismatching, CONFLICT and stale receipts
remain explicitly distinct; unknown identity is UNRESOLVED_REFERENCE, never discarded.
A catalog update cannot automatically certify an old PERSONAL receipt.

Assessment details carry a conservative `freshness`: `CURRENT` only if the assessment fingerprint matches the visible CATALOG vacancy fingerprint; `STALE` for a visible mismatch; `UNVERIFIED` when the opportunity is not visible or either fingerprint is missing. Historical assessments remain readable but are never silently presented as current. Decision and assessment histories retain their original fingerprints/result digests and source proofs.

Two database reads are **not** a distributed transaction. The service checks *both* database heads (including CATALOG revisions, observed commit, ledger digest and PERSONAL context digest)
after queries and fails closed if they moved; this is an optimistic
consistency check, not a guarantee of atomic cross-DB snapshots. A future adapter
must still address authentication, transport and race/retry policy.

Tests cover owner isolation, cross-owner cursors, pending/verified/stale states,
history, unknown archived IDs, invalid input, schema mismatch and no API activation.
CI must pass before integration. No actual end-user data or live Cloudflare queries used.

## PR #37 review corrections

Fixed three TS2532 strict nullability errors in tests without suppressing TypeScript checks. Added targeted regression coverage for owner-specific event history, fingerprint freshness (`CURRENT`/`STALE`/`UNVERIFIED`), conflicting/mismatched receipts, and verified zero persistent writes across CATALOG and PERSONAL read calls. The service is still unwired and cannot authenticate a browser user by itself. CI verification must target the final branch head before merge.
