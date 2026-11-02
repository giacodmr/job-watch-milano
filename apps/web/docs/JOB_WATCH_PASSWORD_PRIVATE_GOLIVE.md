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
- Provision the four environment values **as Cloudflare Worker secrets**, not plaintext
  `vars`: `PASSWORD_PBKDF2_SALT` (16 random bytes, base64url),
  `PASSWORD_PBKDF2_VERIFIER` (PBKDF2-HMAC-SHA256, 100000 iterations, 32 bytes, base64url),
  `PASSWORD_SESSION_KEY` (32 random bytes, base64url). The fourth secret is the
  password itself, **which is NEVER stored in the Worker**: keep it in a password manager.
  Run `node tools/generate-password-secrets.mjs` **only in a private local terminal**,
  never in CI, a Codex chat transcript, a recorded shell, or screenshots.
- Both D1s are initially empty: do not provision an owner, seed demo data, import the
  catalog, or perform APP writes under this PR.

## Login and session security

- `POST /login` validates `Origin` + form type and requires the Cloudflare Worker Rate
  Limiting binding. The rate limiter is fail-closed and limited to five attempts per
  sixty seconds per Cloudflare edge location (not a strict global rate limit).
  This is why the offline generator produces a random 256-bit password; **do not**
  substitute a short or reused password.
- Password is checked with WebCrypto PBKDF2-SHA256. A production Worker Free CPU smoke
  test is mandatory: **10 ms CPU/request** is the Free cap, and 100000 PBKDF2
  iterations must fit in the actual runtime. If they do not, STOP, do not lower the
  KDF cost silently or upgrade to Paid.
- Session is a signed HS256 JWT, four-hour expiry, scoped to the exact hostname, stored
  in a `__Host-` cookie (`Secure; HttpOnly; SameSite=Strict; Path=/`, no Domain).
  No Owner ID or personal email is read from cookies; the owner mapping is server-side.
  `POST /logout` checks Origin and clears the cookie. **Important limitation:** a
  copied signed token remains valid until its four-hour expiry or until the session
  signing key is rotated; logout is not server-side token revocation. Treat session
  theft/revocation and rate limiting as go-live review points.
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

## Separate go-live approval required

The next Gate B must explicitly authorize the **one Worker** `workers.dev` deployment,
exact hostname, binding IDs stored locally only, one owner, secret provisioning, access
policy, quota telemetry, CPU smoke, negative bypass tests and rollback. Do not deploy
from this PR automatically. No GitHub Actions secret/deployment workflow is permitted.
Do not merge while any auth failure, Free CPU limit failure, missing rate limiter,
cross-origin bypass, stale session behavior or private asset exposure remains.

## Follow-on work after a secure, read-only pilot

Only after the user separately approves: import one minimal pinned CATALOG snapshot
with trusted publication/recovery; independently initialize PERSONAL owner; enable
APP writes (CAS/idempotency/quotas) with another explicit gate. Automated ingestion
is not a prerequisite for the first read-only go-live.
