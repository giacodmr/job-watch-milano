# Job Watch — password-only private pilot (code-only; NOT permission to deploy)

## Decision and isolation

The owner selected **Option B: one strong password, no Zero Trust, no card, €0/month**.
This change adds a separate `APP_ENV=password` runtime; it **does not weaken**
`APP_ENV=private` / Cloudflare Access (RS256) or `APP_ENV=local`.
Every request including SPA HTML/JS/CSS is authenticated before `ASSETS.fetch` and before
D1 reads. Unauthenticated API requests return 401, page requests redirect to `/login`.
Service ingestion and APP mutations remain **disabled** in password mode. The two remote
D1 schemas already exist (CATALOG v7 / PERSONAL v3) but must not be written to by this PR.

## Prerequisites — all must pass before any remote deployment

- Owner explicitly approves a single hostname on the included `workers.dev` domain.
- No Cloudflare Access, DNS purchases, or subscription changes; Workers Free and D1 Free
  account-wide quotas are verified. Any unexpected billing requirement = STOP.
- An **isolated**, untracked Wrangler configuration is prepared with:
  `APP_ENV=password`; `PASSWORD_HOSTNAME` set to the exact deployed HTTPS hostname;
  `PRIVATE_OWNER_ID` set to an independently verified **non-synthetic** opaque owner ID;
  the TWO verified remote, distinct D1 bindings `CATALOG` and `PERSONAL`;
  `ASSETS` and `assets.run_worker_first=true`; `PASSWORD_RATE_LIMITER`
  binding. No service ingestion route or APP write gate is activated.
- Never commit owner identifiers, D1 IDs, account IDs, personal data, passwords, JWTs,
  telemetry, or a deployable config. The committed `wrangler.password.template.jsonc`
  intentionally has **no** D1 bindings, hostname, owner or secrets and has
  `workers_dev=false`, `preview_urls=false`.
- Provision three **Worker secrets**, never plaintext vars: `PASSWORD_HMAC_KEY`
  (32 CSPRNG bytes, canonical base64url), `PASSWORD_HMAC_VERIFIER` (32-byte HMAC tag),
  and independent `PASSWORD_SESSION_KEY` (32 CSPRNG bytes, canonical base64url).
  The credential is `jw1_` + canonical base64url of **32 CSPRNG bytes**; it is never
  stored in the Worker. No human-selected, reused or predictable password is supported.
  Shape checks cannot establish entropy: provision only using the trusted offline generator.
  Run `node tools/generate-password-secrets.mjs /absolute/new/private-directory`
  in a private trusted terminal, outside Git and CI. It creates a 0700 directory and
  two exclusive 0600 files (`worker-secrets.json`, `login-password.txt`) and prints
  **no secret values**. Put the credential into a password manager privately.
- Both D1s are initially empty: do not provision an owner, seed demo data, import the
  catalog, or perform APP writes under this PR.

## Login and session security

- `POST /login` validates `Origin` + form type and requires the Cloudflare Worker Rate
  Limiting binding. The rate limiter fails closed when unavailable and applies an
  **approximate threshold** of five attempts per sixty seconds per Cloudflare edge
  location. Counts are eventually consistent: requests can exceed five even within
  one location. Sharing a namespace/key across Workers does not create a strict
  combined or global limit. The namespace ID is operator-chosen, not an API token;
  choose a unique namespace in the account for the future pilot.
  This is why the offline generator produces a random 256-bit password; **do not**
  substitute a short or reused password.
- Credential verification uses native WebCrypto HMAC-SHA256 `verify`, with a
  domain-separated message `job-watch-login:v1\0` + credential. The verifier and HMAC
  key are protected server secrets; JWT signing uses a distinct key (reuse fails closed).
  Malformed/noncanonical credentials fail closed. No PBKDF2 fallback exists.
  Actual remote CPU must still fit **10 ms/request**: `CLOUD_GATE_PENDING`.
- Session is a signed HS256 JWT, four-hour expiry, scoped to the exact hostname, stored
  in a `__Host-` cookie (`Secure; HttpOnly; SameSite=Strict; Path=/`, no Domain).
  No Owner ID or personal email is read from cookies; the owner mapping is server-side.
  `POST /logout` checks Origin and clears the cookie. **Important limitation:** a
  copied signed token remains valid until its four-hour expiry or until the session
  signing key is rotated; logout is not server-side token revocation. Treat session
  theft/revocation and rate limiting as explicit pilot limitations. The independent
  local security review accepts the bounded four-hour replay exposure for this
  single-owner, read-only pilot with a generated 256-bit password and protected
  signing key. This is not per-session revocation: after suspected theft, rotate
  `PASSWORD_SESSION_KEY` through a separately authorized secure operation, requiring
  everyone to log in again. Expanding users, writes or session duration requires
  reassessing this decision. Tests prove copied-token replay after logout and its
  rejection after key rotation.
- `GET /logout` displays the explicit logout confirmation form.
- A bad/missing verifier, missing limiter, wrong Host/protocol, missing D1, invalid
  cookie, unsupported method and cross-origin request fail closed.
- A successful password session is passed into the existing owner-bound read-only
  runtime; the existing Cloudflare Access authentication code is unchanged.
  Password mode does **not** activate `PRIVATE_APP_WRITE_GATE`.

## Validation to complete in Codex local checkout (NO remote mutations)

```bash
cd apps/web
npm ci
npm run check
npm run preflight:private
npm run worker:check:private
npm run worker:check:password
npm run benchmark:password:local
```

Also test, in a locally isolated Worker:
1. Password login succeeds with the generated fixture and wrong login fails.
2. Unauthenticated `/`, SPA, `/assets/*.js`, CATALOG and PERSONAL APIs return
   redirect/401 **without any asset or DB read**.
3. Cookie is `__Host-`, HttpOnly, Secure, SameSite Strict, short-lived, invalid signature
   and expiry rejected. Wrong host and non-HTTPS rejected.
4. Service ingestion, legacy APIs, unknown owners, owner override headers and ALL
   APP mutations are denied even with a valid session.
5. Access RS256 and the old private/local templates regressions PASS.
6. Test logout behavior and the four-hour stolen-token limitation explicitly.

## Historical M51 PBKDF2 evidence (superseded by HMAC below)

The benchmark uses the real bundled Worker in **local workerd**, two disposable local
D1 bindings and a local Rate Limiting binding. It uses public synthetic fixtures,
does not invoke the real secret generator, and makes no Cloudflare API calls.
Run on macOS/Linux with Node 24 and `ps`; it takes no input or real credentials.
Warm-up is excluded. Thirty login samples per case and sixty session samples measure
host wall time and the aggregate CPU increment of descendant workerd processes.
`ps` CPU has coarse resolution; it is neither an isolate CPU profile nor Cloudflare
per-invocation billable CPU. Node-side fixture derivation is excluded.

Observed 2026-11-02, Apple M1 Pro, Node v24.15.0, workerd 1.20261023.1:

| Scenario | Requests | Host wall p50 / p95 (ms) | Local workerd process CPU mean (ms/request) |
| --- | ---: | ---: | ---: |
| Login page, no KDF | 30 | 1.18 / 3.02 | 0.67 |
| Invalid password, full KDF | 30 | 10.45 / 10.99 | 9.00 |
| Valid password, full KDF and signing | 30 | 10.96 / 13.73 | 10.00 |
| Valid session, no D1 | 60 | 0.97 / 1.37 | 0.50 |

The separate local limiter exercise observed five rejected-credential redirects,
then seven HTTP 429 responses with no session issued. This checks local binding
wiring, not distributed edge accuracy or Free-account availability.

**Workers Free compatibility is NOT certified.** The documented limit is 10 ms CPU
per HTTP invocation; the local login mean leaves no demonstrated safety margin.
Wall time above 10 ms alone does not establish a cloud CPU failure. A separately
authorized, bounded remote test must measure actual CPU distribution for correct,
incorrect and rate-limited login, session reads and representative read-only D1 APIs.
STOP on CPU exceptions/1102 or insufficient margin; do not upgrade or lower PBKDF2
iterations. The remote test must exercise the actual limiter and protected asset
router on the exact final bundle before any real data or private go-live.

At M51, the proposed zero-cost correction was a dedicated
server-verified HMAC-SHA256 credential design for an exclusively machine-generated
256-bit random login credential, with separate verifier/session keys and the same
cookie, Origin and limiter controls. Fast verification is inappropriate for a
human-chosen password. This alternative requires explicit approval and review; it
is now implemented by the CPU-login correction below; it remains undeployed.

Primary references: [Free CPU](https://developers.cloudflare.com/workers/platform/limits/#cpu-time),
[limiter locality](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/#locality),
[limiter accuracy](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/#accuracy).

## Separate go-live approval required

The next Gate B must explicitly authorize the **one Worker** `workers.dev` deployment,
exact hostname, binding IDs stored locally only, one owner, secret provisioning, access
policy, quota telemetry, CPU smoke, negative bypass tests and rollback. Do not deploy
from this PR automatically. No GitHub Actions secret/deployment workflow is permitted.
Do not merge while any auth failure, Free CPU limit failure, missing rate limiter,
cross-origin bypass, stale session behavior or private asset exposure remains.
Pending edge CPU/asset certification alone is a cloud gate, not evidence that local
acceptance failed. The PR stays Draft until the owner reviews these limitations;
no automatic merge or deployment follows green local/CI checks.

The next operational mandate should separate two gates: (1) authorize merging the
reviewed PR #52; (2) approve one named Free Worker, exact `workers.dev` hostname,
private bindings/config and securely generated secrets, followed by the bounded
CPU/negative-route smoke and rollback. Confirm no payment method/upgrade and current
account-wide request/D1 quotas before either remote write or deployment. First
exposure remains password-protected and read-only. No owner provisioning, real
ingestion or APP writes are included. Missing owner data must remain an explicit
empty/uninitialized state; do not seed it to make a smoke pass. If the smoke fails,
disable the newly approved Worker route or use the separately approved rollback;
never restore/delete either D1 automatically.

For that next mandate, propose a maximum of 60 HTTP smoke requests and a conservative
reservation of 5000 D1 rows read across both databases, zero D1 rows written, no
retries of uncertain operations, and no other active writer. Confirm sufficient
account-wide remaining allowances before starting; unknown usage is NO-GO. Spread
allowed login samples across 60-second windows rather than raising the limiter to
collect more samples. Inspect CPU for valid and invalid full-KDF logins as well as
429 responses; report the actual small sample size and do not treat its p95 as a
worst-case guarantee. Capture only aggregate durations, counts, status/error codes,
commit and UTC timestamps, never request headers, cookies, passwords, JWTs, owner
IDs or database/account IDs. Any CPU 1102/limit warning, authentication or asset
bypass, unexpected write, paid requirement, target mismatch or unknown outcome
ends the smoke and keeps go-live closed.

## Independent local security acceptance (M51)

Reviewed starting branch HEAD `c1e42b7c844d84a591cd80a826b3d11a9076b8e2` against
main `7af2dddec2fe5ec191c7c5b7787caa6b5e78e705`, then re-reviewed the acceptance
changes. One concrete defect was corrected: awaiting the login promise inside the
outer error boundary keeps aborted-body errors in the sanitized 503 response.
Final independent local review: **zero unresolved security findings**. The existing
Access RS256/local runtimes, CATALOG/PERSONAL SQL migrations and private template
were not changed.

Password tests now include all unauthenticated routes/methods before D1/assets,
forged or wrong-claim JWTs, duplicate cookies, owner override, oversized/aborted
bodies, CSRF, disabled APP gates even when private write flags are present, and
copied-token replay/key rotation. A separate workerd integration uses actual static
HTML/JS/CSS and the Static Assets router, with `run_worker_first=true`, to prove
pre-login redirects and post-login access locally. The repository preflight guards
the password template's blocked routes, missing identities/D1, asset routing,
disabled telemetry and limiter binding. Edge routing remains a cloud gate.

The original TS2379 failures were corrected only in tests: clone and delete missing
optional bindings, and narrow the CATALOG binding before assigning it to PERSONAL.
Strict optional-property checking remains enabled, with no runtime type widening.

Local acceptance on 2026-11-02: **318 tests PASS** (316 unit/integration plus two
actual desktop/mobile browser flows), strict TypeScript and Vite build PASS via
`VITEST_MAX_WORKERS=2 npm run check`. The environment-only worker cap avoids a
local concurrent-workerd `ECONNRESET` seen in the existing 8000-statement capacity
probe; the probe passes unchanged both independently and in the final full run.
The browser harness now locates the installed macOS Chrome/Chromium binary while
preserving the Linux paths, temporary isolated profile and synthetic loopback data.
`npm ci --no-fund --no-audit`, `preflight:private`, both private/password Worker
dry-runs, local Worker dry-run, two consecutive local migration applies (no pending
migrations on the second), and `git diff --check` all PASS. No real secret/remote
identity was introduced. Acceptance status: **LOCAL_ACCEPTANCE_PASS / CLOUD_GATE_PENDING**.
GitHub CI must be verified on the final pushed HEAD, never inferred from these
local results or an older successful commit. PR remains Draft; no merge or remote
Cloudflare action is included in this acceptance.

## Follow-on work after a secure, read-only pilot

Only after the user separately approves: import one minimal pinned CATALOG snapshot
with trusted publication/recovery; independently initialize PERSONAL owner; enable
APP writes (CAS/idempotency/quotas) with another explicit gate. Automated ingestion
is not a prerequisite for the first read-only go-live.

## First remote pilot: expected uninitialized databases (2026-11-02)

The first bounded remote smoke confirmed valid/invalid password login, protected HTML,
JS, CSS and API assets, authenticated asset fetches and CATALOG read access.
The remote Worker was correctly disabled after the smoke stopped at
`GET /api/model-c/personal/summary`: HTTP 404
`PERSONAL_CONTEXT_UNAVAILABLE`. This is **expected** while PERSONAL v3 has no
owner context. CATALOG v7 also has no published snapshot. No real data was lost:
the databases were migrated but never populated.

This acceptance fix deliberately **does not** change the owner-scoped PERSONAL SQL
reader, forge a personal revision, invent an empty verified history, seed an owner,
or return HTTP 200 for `/personal/summary`. An authenticated browser now shows an
explicit, distinct "Registro personale non ancora inizializzato" state instead
of a generic API-failure panel. CATALOG `snapshot:null` and combined opportunities
`items:[]` remain valid, non-synthetic empty states.

**Updated remote smoke interpretation:**

- Authenticated `GET /api/model-c/catalog/snapshot`: HTTP 200
  `snapshot:null` is **PASS_EMPTY** (only when no published catalog exists).
- Authenticated `GET /api/model-c/opportunities/jobs`: HTTP 200,
  `snapshot:null` and empty items is **PASS_EMPTY**.
- Authenticated `GET /api/model-c/personal/summary` (and `/personal/jobs`):
  HTTP 404 with exactly `PERSONAL_CONTEXT_UNAVAILABLE` is
  **PASS_UNINITIALIZED**, but **not** proof of initialized, queryable owner data.
- Missing authentication remains **401** for every API; no owner override;
  invalid schema/DB failure remains **NO-GO** (do not normalize these).
- A future real owner import must replace these expected states with independently
  verified positive reads. No cloud writes are allowed by this UI fix.

The Worker remains **not exposed** until the already-authorized scope is
reconfirmed for a new attempt and remaining negative tests (logout, actual edge
rate limiter, CPU and edge asset routing) are completed. The failed smoke used
24 of its prior 60 HTTP requests; whether any remaining requests may be reused
must be approved explicitly for the next bounded smoke. Never invent remote
CPU evidence or silently activate exposure.


## CPU-login correction and secure credential rotation

Scope: main `c579a255c3fe90e684d7e6260f0ee8c686c3638e`; password verifier only.
Cloudflare Access, owner mapping, cookies, session expiry, Origin/Host validation,
read-only gates, assets and D1 routing stay unchanged. No remote operations in this PR.

After review and merge, **separate explicit Gate B authorization** is required:
1. Verify the existing Worker remains unexposed (`workers.dev=false`, previews=false),
   Free plan, zero cost, account-wide quotas and a fresh bounded smoke budget.
2. Generate a NEW credential, HMAC key/verifier and JWT session key privately with
   the offline tool. Rotate all three together; do not reuse the former credential.
   New session key invalidates every copied old JWT. Never run the generator in CI,
   transcript capture or screen sharing; never print/cat the resulting files.
3. Deploy the new bundle and three secrets together from the private file, while
   exposure remains disabled. Remove `PASSWORD_PBKDF2_SALT` and
   `PASSWORD_PBKDF2_VERIFIER` remotely while disabled. Legacy-only config returns
   503; mixed config uses only the new HMAC verifier, never PBKDF2 fallback.
4. Verify bindings and secret NAMES only, then expose the approved hostname for the
   bounded smoke. Measure cold/warm valid, wrong canonical and limited logins using
   edge CPU telemetry, not wall time. Complete logout, CSRF, asset/API protection
   and zero-write checks. Disable exposure on failure; no Paid upgrade.
5. Keep only the accepted credential in a password manager; remove temporary local
   secret files through the operator's secure storage policy. Do not restore the old
   PBKDF2 configuration or old session key as an exposed rollback: rollback is to
   **disabled exposure** until a separately reviewed fix.

Local profiling uses a synthetic, test-only entry point, exporting the signing helper
only through an esbuild plugin. No profiling routes or telemetry are added to the
production Worker. Each phase includes configuration and HTTP harness overhead;
results are not additive exclusive spans. Rate uses the real local binding.
`npm run profile:password:local -- --baseline` loads the prior auth source from the
pinned main commit; omit `--baseline` for HMAC. The full comparable benchmark also
supports `npm run benchmark:password:local -- --baseline`. Both are local-only,
use public synthetic credentials and never accept real secret files.

The native HMAC verifier is appropriate only for uniformly random 256-bit credentials,
not human passwords. No runtime can infer randomness from a string's appearance.
Cookie theft remains replayable for up to four hours unless the JWT key is rotated.
The rate limiter remains approximate per edge location and fail-closed.

References: [Workers Web Crypto](https://developers.cloudflare.com/workers/runtime-apis/web-crypto/),
[OWASP random-token verification](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

### Local comparative measurements — 2026-11-02

Apple M1 Pro / macOS arm64, Node 24.15.0, workerd 1.20261023.1.
Pinned PBKDF2 baseline and HMAC use the same canonical synthetic credential.
Full harness: five warm-ups, 30 requests per login case, 60 session reads.
Phase harness: five warm-ups per phase, 60 requests per phase. Configuration/HTTP
transport overhead is included in every phase; `ps` CPU is aggregate/coarse.

| Scenario | PBKDF2 CPU mean ms | HMAC CPU mean ms | PBKDF2 wall p50 ms | HMAC wall p50 ms |
|---|---:|---:|---:|---:|
| Configuration | 0.50 | 0.50 | 1.03 | 1.26 |
| Configuration + limiter | 0.83 | 1.17 | 1.67 | 2.25 |
| Configuration + credential verification | 8.33 | 0.50 | 9.04 | 1.20 |
| Configuration + JWT signing | 0.50 | 0.67 | 0.85 | 1.43 |
| Full invalid canonical login | 9.00 | 1.00 | 9.91 | 1.61 |
| Full valid login | 9.00 | 1.00 | 10.24 | 1.73 |

Valid login wall p95: baseline 10–12 ms in local runs; HMAC 2.93 ms.
Local limiter: five 303 responses, then seven 429 responses; no session issued
on denied credentials. Approximate process CPU improvement is 9x for warm valid
login, not a precise per-isolate speed guarantee. Cold compilation, scheduling,
shared edge hardware and remote limiter behavior are not certified here.
**CLOUD_GATE_PENDING** remains mandatory, including cold first-login CPU.
