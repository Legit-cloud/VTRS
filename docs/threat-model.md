# VTRS threat model

Scope: the backend described in the README (API, WebSocket feed, workers, PostgreSQL, object
storage, provider integrations). The web app (one app for every role; agents use it in their
phone's browser) is a client of it and is assessed separately; this document says what the
backend assumes of it.

This is a working document for PB-11. It names what is protected, who might attack it, what the
code does about each threat today, and what is still open. Every "control" below points at
code or a test, so it can be checked rather than believed.

## 1. What is protected

| Asset | Why it matters | Where it lives |
| --- | --- | --- |
| Result figures and their history | The product's reason to exist; a wrong or silently changed figure is the worst failure | `result_version`, `vote_line`, `pu_result`, `result_review` |
| Result-sheet photos and their custody | The proof behind a figure | object store, `evidence_file`, `custody_event` |
| The audit trail | Lets anyone reconstruct who did what | `audit_event`, `audit_batch` |
| Agent and officer identity data | Phone numbers and emails of people in a sensitive political activity (NDPA) | `account_user` (field-encrypted), invitations |
| Credentials and tokens | Gate everything else | password hashes, refresh tokens, signing key |
| Availability on Election Day | A tracker that is down at 6 pm is worthless | the whole stack |
| The party's position (provisional leads, anomalies) | Competitive and political sensitivity | rollups, flags, exports |

## 2. Who attacks, and from where

| Actor | Capability | Typical goal |
| --- | --- | --- |
| Outsider on the internet | Anonymous requests, scripts, botnets | Take it down; harvest SMS (pumping); read results |
| Hostile or compromised agent | A valid agent account at one polling unit | Inject or alter a result; claim another unit; reuse a photo |
| Rogue officer or admin | Legitimate access to part or all of one organization | Read another area; erase a trail; export data out |
| Rival party's user | A valid account in *another* organization | Cross a tenant boundary |
| Insider with database or storage access | Operator credentials | Edit a figure or a photo without trace |
| Compromised provider or dependency | A webhook sender, an SMS vendor, a library | Forge receipts; run code |

## 3. Trust boundaries

1. Internet to edge (TLS, rate limiting, WAF: the edge is infrastructure, see section 6).
2. Edge to API/WebSocket. Everything beyond this line is authenticated or explicitly `public`.
3. Browser to API. The agent's phone is *untrusted*: its clock, GPS and totals are inputs,
   never facts.
4. API to workers over the outbox (events are facts the API wrote; workers re-derive state).
5. Application to PostgreSQL as `vtrs_app`, which has no UPDATE or DELETE on immutable tables.
6. Application to object storage with presigned, short-lived, checksum-pinned URLs.
7. Application to providers (SMS, challenge, scanner) over HTTPS through one seam.

## 4. Threats and controls (STRIDE)

### Spoofing

| Threat | Control | Evidence |
| --- | --- | --- |
| Credential stuffing or guessing | Argon2 hashing, per-account and per-IP throttles, lockout counters that survive failed requests | `tests/accounts/test_login_and_sessions.py` |
| Stolen access token | 10-minute EdDSA tokens; role and scope re-read from the database on every request, so removal or demotion is immediate | `apps/accounts/services/sessions.py::resolve_actor` |
| Token forgery (alg none, algorithm confusion, tampered claims, wrong audience, unknown key id) | Pinned algorithm and key set, required claims, audience and issuer | `tests/security/test_hardening.py` |
| Refresh token theft | Rotation on every use; reuse revokes the whole session | `tests/accounts` (reuse detection) |
| Admin account takeover | TOTP MFA mandatory for admins and anyone who can export; step-up for locks, exports, downloads and alert policy | `apps/core/domain/permissions.py::requires_mfa` |
| Open registration of agents | Agents exist only by invitation, with an OTP to the invited contact | `apps/accounts/services/invitations.py` |
| SMS pumping through public OTP endpoints | Bot challenge (Turnstile, hCaptcha or reCAPTCHA) fail-closed, per-destination and per-IP OTP budgets, allowed country prefixes | `apps/accounts/bot_challenge.py`, `tests/providers` |
| Forged delivery receipts | Twilio signature verified in constant time; endpoint closed until configured | `tests/providers/test_webhook.py` |

### Tampering

| Threat | Control | Evidence |
| --- | --- | --- |
| Editing or deleting a submitted result | A result version is immutable (trigger plus grants); only its review `state` may change, and that is ledgered. Corrections are new versions | `apps/results/migrations/0002_integrity.py`, `tests/results/test_submission.py` |
| Replay or duplicate submissions | Client-generated version id is the idempotency key; same id with a different hash is a 409 and an audit entry | `tests/results/test_concurrency.py` (100 parallel replays, one version) |
| Altered payload in transit or at rest | TLS in transit; the client's `payload_hash` (SHA-256 of the canonical submission) is recomputed on receipt and stored, so a replay with different numbers is refused | `apps/results/domain/versions.py` |
| Swapped or corrupted sheet | Presigned PUT pins the SHA-256, so the store rejects corruption; the server re-hashes after upload; packs re-hash again and exclude mismatches | `tests/results/test_evidence.py`, `tests/reports/test_pack.py` |
| Rewriting custody or audit history | Per-file hash chain; audit events sealed into Merkle batches that chain to the previous root; both tables append-only by trigger and grants | `verify_custody`, `verify_audit_chain` |
| Rollup figures drifting from the truth | Rollups are derived data, recomputed from head versions; `verify_rollups` compares against an independent calculation; reconciliation freezes an immutable snapshot with a digest | `tests/aggregation` |
| Malicious spreadsheet content | Formula-like text neutralized in every exported cell | `tests/reports/test_formats.py` |
| Path traversal in archives | Archive member names built from slugs, never from raw input | `apps/reports/domain/pack.py` |

### Repudiation

| Threat | Control |
| --- | --- |
| "I never approved that" | Review decisions, flag actions, policy changes, exports and downloads each write an audit entry in the same transaction as the action, with actor, role, IP and request id |
| "That photo never left the system" | Every download link and every export is a custody event on the photo |

### Information disclosure

| Threat | Control | Evidence |
| --- | --- | --- |
| One organization reading another's data | Row Level Security on every tenant table, with the tenant set per transaction; requests start with no tenant | `tests/core/test_crypto_and_rls.py` |
| An officer reading outside their area | Geographic scope applied in the query layer (`for_actor`), not the UI; scoped officers never see the state total | authorization matrix, `tests/aggregation/test_dashboard.py` |
| Enumeration of other tenants' ids | Out-of-scope objects answer 404, never 403 | `tests/authz/test_matrix.py` |
| PII at rest | Email and phone are field-encrypted with a key ring; lookups use blind indexes; logs carry masked values | `apps/core/crypto.py`, `apps/core/logging.py` |
| Public photo URLs | Private bucket; 60-second scoped links issued only after the permission check and logged | `apps/evidence/services.py::download_url` |
| Data leaving in bulk | Exports and packs need explicit permission, a fresh second factor twice, are built with the requester's own scope, purged after 72 hours, and audited | `tests/reports` |
| Stack traces or internals in errors | Uniform problem+json; unexpected errors return a request id only | `tests/security/test_hardening.py` |
| Cross-origin reads | Exact-origin allowlist, no credentials, no wildcard (production refuses `*` and non-https) | `ApiBoundaryMiddleware`, `config/settings/prod.py` |
| Caching of sensitive responses | `Cache-Control: no-store` and a restrictive CSP on every API response | `tests/security/test_hardening.py` |
| Official-sounding claims | Every figure is labelled provisional in responses, exports and packs | `PROVISIONAL_NOTICE` |

### Denial of service

| Threat | Control |
| --- | --- |
| Request floods | Throttles by scope (login, OTP, refresh, submit per agent), body size limit (413), one result per submission, pagination caps |
| Expensive queries | Keyset pagination only; windowed audit queries (31 days); statement and lock timeouts at the database |
| Long-running exports | Background jobs, three per person, pack limits, retention purge |
| Worker starvation or backlog | Outbox relay and sweeps as safety nets; health endpoint exposes backlog age; rollup refresh is coalesced so a burst costs a few refreshes, not one per result |
| Provider outage | Fail closed only where abuse is the risk (bot challenge); delivery retries with bounded attempts elsewhere; results never wait on a provider |

### Elevation of privilege

| Threat | Control |
| --- | --- |
| A role doing more than allowed | Permission map plus scope; every view must declare a permission or be public (a test walks the URL table); a matrix test tries every endpoint with every role against four targets |
| Granting oneself power | Roles may only grant at or below their own; grants limited per role; role and scope changes need a fresh second factor and bump the session version |
| Application bug becoming data loss | The application role has no UPDATE or DELETE on immutable tables; the migration role is separate |
| Mass assignment | Strict serializers reject unknown fields; list endpoints reject unknown query parameters |

## 5. Field abuse cases

| Abuse | What stops or exposes it |
| --- | --- |
| Agent submits for a unit they are not assigned to | Refused (403), flagged CRITICAL, audited |
| Agent submits from home or from elsewhere | Geofence flag (HIGH beyond 2 km); the result still counts and goes to review |
| Same sheet photographed for two units | Duplicate-evidence flag from exact and perceptual hashes |
| Totals that do not add up, or exceed accredited or registered | Inline arithmetic and over-voting flags |
| Implausible turnout or vote share | Robust outlier flags against neighbouring units |
| Backdated or future-dated phone clock | Clock-ahead and before-polls flags; server time is authoritative |
| Two agents, two stories | Duplicate-source flag; both versions kept; the reviewer decides |
| Retrying until it "sticks" | Idempotent by version id; a changed payload under the same id is refused |
| Photo that is not an image, or is malware | Magic-byte check, bounded decode, scanner; quarantined and flagged |

## 6. Assumptions and what this backend does not cover

- **Edge and network.** TLS termination, a WAF, volumetric DDoS protection and per-IP rate limits
  at the edge are infrastructure. The application's throttles are a second line, not the first.
- **Secrets.** Production reads the signing key, field-encryption keys, blind-index key, OTP
  pepper and provider credentials from a secrets vault. Production settings refuse to start
  without them or with the development stand-ins. KMS or HSM-backed key custody is a
  deployment decision.
- **Agent phones.** Agents use their own phone's browser (open decision #7): there is no device
  binding or attestation, so a stolen session works from any browser until it expires or is
  revoked. Sessions are short, refresh tokens rotate, and deactivating an agent ends every
  session and assignment at once.
- **Biometrics.** Face verification (FR-6.1.3) is not implemented and stays behind PB-08 and
  SEC-09.
- **Data residency.** No residency claim is made until PB-12 selects the region (DG-06).
- **Insider with superuser access.** Triggers stop the application role, and the audit and
  custody chains make tampering detectable, but a person with database superuser rights can
  still act. Detection depends on sealing and verifying the chains regularly (see the
  runbook) and on keeping sealed roots somewhere that person cannot also rewrite.

## 7. Open items before go-live

1. Independent penetration test of the API and the deployed edge.
2. Decide and implement edge controls (WAF rules, rate limits, bot management).
3. Stand up the secrets vault and key rotation procedure; rehearse it (runbook section 9).
4. Anchor sealed audit roots outside the database (object lock or a second system).
5. Confirm provider choices (PB-07) and run each adapter against the real service.
6. Confirm that agents' own phones without device binding are acceptable (PB-06).
7. Legal review of retention, export and biometric decisions (PB-08, PB-09).
