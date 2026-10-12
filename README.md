# VTRS backend

Vote Tracking & Recording Solution: the Django backend for the Oyo State pilot. It serves
the public website, the party portal and the offline-first agent app.

VTRS is a party-side monitoring and recording system. Any leading position it shows is
provisional and based on captured party data. It is never an official declaration.

## Stack

Python 3.12, Django 5.2, Django REST Framework, PostgreSQL 16, Celery with Redis, and
S3-compatible object storage (MinIO locally).

## Local development

Docker Compose runs PostgreSQL, three Redis instances (cache, broker, channels), MinIO and
Mailpit. It is for local development only.

```sh
cp .env.example .env
make venv          # Python 3.12 virtualenv with dev dependencies
make up            # start the stack
make migrate       # migrations run as vtrs_migrator; the app connects as vtrs_app
make seed          # synthetic Oyo-shaped master data: 33 LGAs, 351 wards, 6,390 PUs
make check         # ruff, import-linter, pytest
```

On Windows (PowerShell), without make:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
docker compose up -d
$env:DATABASE_URL = "postgres://vtrs_migrator:vtrs_migrator_dev@localhost:5432/vtrs"
.\.venv\Scripts\python manage.py migrate
Remove-Item Env:DATABASE_URL
.\.venv\Scripts\python manage.py generate_synthetic_geography --out var\synthetic_oyo.csv
.\.venv\Scripts\python manage.py import_master_data var\synthetic_oyo.csv --report var\import_report.json
.\.venv\Scripts\python -m pytest
```

Tests need PostgreSQL. Triggers, partitioning, `SKIP LOCKED` and advisory locks are all
exercised for real. Tests connect through `TEST_DATABASE_URL`, which defaults to the Compose
superuser, because they create their own database.

## Database roles

`docker/postgres/init/01-roles.sql` creates three roles on first start:

| Role | Purpose |
| --- | --- |
| `vtrs_migrator` | Owns the schema and runs migrations |
| `vtrs_app` | The running application. DML only. No UPDATE, DELETE or TRUNCATE on immutable tables |
| `vtrs_readonly` | Reporting and read replicas |

## Layout

```
config/            settings (base, dev, test, prod), urls, celery
apps/<app>/
  api/             DRF views and serializers (thin)
  services.py      state changes; own the transaction and write the audit entry
  selectors.py     reads; take the acting user and return scoped querysets
  domain/          pure Python rules, no Django
  models.py        schema and constraints
```

Imports flow downward only: api → services → selectors → models → domain. `lint-imports`
enforces this, and it also keeps Django out of `domain/`.

Every API view must declare `required_permission` or `public = True`. A test walks the URL
table and fails on any view that does neither.

## Identity and access

- **Organizations** register at `POST /api/v1/auth/organizations`. They stay pending until
  the signer verifies an OTP (SMS or email) and a platform operator approves them, in the
  portal's platform admin surface or with
  `python manage.py approve_organization <id> --operator <name>`.
- **Platform operators** hold the `PLATFORM_ADMIN` role in the platform organization
  (`Organization.is_platform`, one only). They are created with
  `python manage.py create_platform_admin`, never by invitation, and no party role can grant
  the role. They see organizations, elections' lock state, master-data completeness, delivery
  rates and a platform-wide audit trail (`/api/v1/platform/*`), never a party's results,
  evidence or people. Decisions (approve, reject, suspend, reinstate) and master-data imports
  need a fresh second factor and are audited against the organization concerned.
- **Agents and officers** are only ever invited (`POST /api/v1/invitations`). The invitee
  accepts with the token from the SMS or email link, an OTP sent to the invited contact, and
  a password. Agents also register their device.
- **Tokens:** access tokens are 10-minute EdDSA JWTs. Refresh tokens are opaque, rotated on
  every use, and a reused one revokes the whole session. Role and scope are re-read from the
  database on every request, so changes apply immediately.
- **MFA:** TOTP with recovery codes. It is mandatory for admins and anyone who can export, and
  role or scope changes need a fresh second factor.
- **Row Level Security:** tenant tables only show the current organization's rows. The test
  suite runs as the `vtrs_app` role, so RLS and the restricted grants are exercised by every
  test.
- **Authorization matrix:** `tests/authz/test_matrix.py` tries every protected endpoint with
  every role against four targets. It fails if a new endpoint isn't listed.

Production must provide these from the secrets vault: `VTRS_JWT_PRIVATE_KEY` (Ed25519 PEM),
`VTRS_FIELD_ENCRYPTION_KEYS`, `VTRS_BLIND_INDEX_KEY`, `VTRS_OTP_PEPPER`, `VTRS_SMS_PROVIDER`
and `VTRS_BOT_CHALLENGE_PROVIDER`. Production settings refuse to start with the fake SMS
provider or with the bot challenge disabled.

## Elections and deployment

- **Lifecycle:** `DRAFT ⇄ CONFIGURED → LOCKED → LIVE → CLOSED`. Contests and candidates can
  change only before `LOCKED`. Locking needs a fresh second factor and records a SHA-256
  fingerprint of the whole configuration (`config_hash`). Results capture opens at `LIVE`.
- **Contests:** a contest covers a set of states, LGAs or wards, so a senatorial district is
  just the list of its LGAs. Each contest says which result-sheet totals it captures.
- **Config changes:** every change bumps the election's `config_version`, which agents sync
  against. Edits need the `ETag` from the last read in `If-Match`; a stale edit gets 412.
- **Assignments:** an agent can only be deployed to a polling unit that is inside the
  election's state and among the agent's authorized units. `VTRS_MAX_AGENTS_PER_POLLING_UNIT`
  (default 1) caps how many agents can cover one polling unit.
- **Agent view:** `GET /api/v1/me/assignments` returns each assigned polling unit with its
  ballot (only the contests that cover it, candidates in ballot order). It also says whether
  capture is open.

## Results, review and dashboards

- **Counting rule:** a polling unit's result is its *head version*: the highest version that
  has not been rejected. Corrections are new versions; nothing is edited or deleted.
- **Two measures, always kept:** *Reported* counts every counting head (submitted, flagged or
  approved). *Verified* counts only heads a reviewer has approved. The election's
  `count_policy` picks the default, and every dashboard call accepts `?measure=reported|verified`.
- **Review** (off unless the election sets `review_enabled`): `POST /api/v1/results/{id}/review`
  approves or rejects the version that currently counts. A rejection needs a reason, keeps the
  original record, and the head falls back to the previous version; the agent sees the reason
  in `GET /sync/status` and resubmits as a new version. Approving a flagged result needs
  `acknowledge_flags`. Decisions live in an append-only ledger and the audit log.
  `GET /elections/{id}/review-queue` lists what is waiting inside the caller's scope.
- **Rollups:** Ward, LGA and State figures are stored (`rollup`, `rollup_vote`) and recomputed
  by a worker after every accepted version or review decision. Recomputing is idempotent, so a
  repeated or delayed event cannot leave a wrong figure behind. Polling-unit figures are read
  straight from the head version. Operators can repair or check them:

  ```sh
  python manage.py rebuild_rollups [--election ID] [--contest ID]
  python manage.py verify_rollups  [--election ID]     # non-zero exit on any difference
  ```
- **Reads** (`dashboard.view`, narrowed to the caller's geography): `GET
  /elections/{id}/dashboard` (War Room), `GET /contests/{id}/results?level=lga|ward|pu&parent_id=`
  (drill-down and LGA scorecards), `GET /contests/{id}/coverage-timeline`, and `GET
  /contests/{id}/polling-units/{id}/history` (every version with reviews, flags and evidence).
  A scoped officer's top level is their own area; they never see the state total.
  Every figure is provisional, and responses say so.
- **Live updates:** connect a WebSocket to `/ws/v1/dashboard`, send
  `{"type": "auth", "token": "<access token>", "election_id": "<uuid>"}` as the first message,
  and receive `rollup.updated` notices (ids and a revision, never figures) for the areas in
  scope. Refetch over REST. Run the ASGI app with `daphne config.asgi:application`; production
  needs `REDIS_CHANNELS_URL` so workers and sockets share a channel layer.
- **Reconciliation:** `GET /elections/{id}/reconciliation` shows what is outstanding, and
  `POST /elections/{id}/reconcile` (fresh second factor) rebuilds the rollups from head
  versions, proves them against a second pass, stores an immutable snapshot with its SHA-256,
  and moves the election to `RECONCILED`. With review on, every counting result must have been
  decided first. After that, results cannot change.

## Anomalies, alerts and notifications

A finding never removes a result from the count. It raises a **flag**, sends the result to
review, and tells the right people. Cheap arithmetic rules run inside the submit; the rest run
on a worker (`anomaly` queue) as soon as the result or its photo is stored.

| Rule | Severity | Meaning |
| --- | --- | --- |
| `ARITHMETIC_VARIANCE`, `OVER_VOTING` | HIGH, CRITICAL | Totals do not add up; more votes than accredited or registered |
| `DUPLICATE_SOURCE`, `VERSION_FORK`, `UNASSIGNED_PU_ATTEMPT` | HIGH, HIGH, CRITICAL | Two sources, a correction that skips a version, an unassigned agent |
| `GPS_OUT_OF_GEOFENCE` | MEDIUM, HIGH beyond 2 km | Fix is more than 300 m (plus its own accuracy) from the unit |
| `GPS_MISSING`, `GPS_LOW_ACCURACY` | MEDIUM, INFO | No fix, or one worse than 100 m |
| `CAPTURED_BEFORE_POLLS_OPEN`, `CAPTURED_BEFORE_POLLS_CLOSE` | HIGH | A result sheet cannot exist before voting ends |
| `DEVICE_CLOCK_AHEAD` | MEDIUM | Device time is more than 5 minutes ahead of the server |
| `TURNOUT_OUTLIER`, `VOTE_SHARE_OUTLIER` | MEDIUM, HIGH at 90% turnout | Modified z-score above 3.5 against the ward (or LGA) |
| `HIGH_REJECTED_RATE`, `UNANIMOUS_RESULT` | MEDIUM | More than 10% rejected; every valid vote to one candidate |
| `DUPLICATE_EVIDENCE` | HIGH | Photo matches another unit's (identical hash, or 64-bit dHash within 4 bits) |
| `EXIF_TIME_MISMATCH`, `EXIF_GPS_MISMATCH` | MEDIUM | Photo metadata disagrees with the declared time or place |
| `MISSING_EVIDENCE`, `EVIDENCE_QUARANTINED` | MEDIUM, HIGH | No photo after 30 minutes; photo failed verification |

Thresholds are the fields of `Thresholds` in `apps/anomalies/domain/contextual.py`; override
any of them with `VTRS_ANOMALY_THRESHOLDS = {"geofence_m": 500.0}`.

**Routing and escalation** follow an incident-severity matrix
(`apps/anomalies/domain/escalation.py`, overridable with `VTRS_ESCALATION_MATRIX`):

| Severity | Told at once | Channels | Acknowledge within | Then |
| --- | --- | --- | --- | --- |
| CRITICAL | ward, LGA, admin | in-app, SMS, email | 15 min | repeat on WhatsApp |
| HIGH | ward, LGA | in-app, email | 30 min | admin, plus SMS |
| MEDIUM | ward | in-app | 2 h | LGA, then admin, plus email |
| INFO | nobody | | | listed only |

Acknowledging stops the clock. Flags are worked through `/api/v1/elections/{id}/flags`
(list, summary), and `/api/v1/flags/{id}` with `acknowledge`, `comments`, `assign`, `resolve`
(RESOLVED or FALSE_POSITIVE, with a note) and `reopen`. Resolving the last active flag returns
a result from REQUIRES_REVIEW to SUBMITTED. Every step is an append-only `FlagEvent` and an
audit entry, and visibility follows the caller's geography.

**Notifications** (`/api/v1/me/notifications`): each message is an in-app record with one
delivery row per channel (PENDING, SENT, DELIVERED, FAILED, SKIPPED), retried up to three
times. Agents get a push (and an inbox entry) when a result is rejected, with the reviewer's
reason; they register a token with `PUT /api/v1/me/push-token`. Providers are adapters
(`VTRS_SMS_PROVIDER`, `VTRS_PUSH_PROVIDER`, `VTRS_WHATSAPP_PROVIDER`); production refuses the
fakes, and WhatsApp stays off until `VTRS_FEATURE_WHATSAPP_ALERTS` is enabled.

Beat schedules the escalation sweep (every minute), the missing-photo sweep (every five
minutes) and delivery retries (every minute). Run workers on the `anomaly`,
`notifications` and `reports` queues as well.

## Exports, evidence packs and administration

**Exports** are background jobs, never response bodies: `POST /api/v1/exports` returns a job,
a worker (`reports` queue) builds the file as the requester, and `POST
/api/v1/exports/{id}/download-url` issues a 60-second link to private storage.

| Kind | Formats | Needs |
| --- | --- | --- |
| `RESULTS` (per contest; level `pu`, `ward` or `lga`; measure `reported` or `verified`) | CSV, XLSX | `reports.export` |
| `FLAGS` (the anomaly register) | CSV, XLSX | `reports.export`, `anomalies.view` |
| `AUDIT` (a window of at most 31 days) | CSV | `reports.export`, `audit.view` |
| `EVIDENCE_PACK` (photos, manifest, custody, verifier) | ZIP | `evidence.export` |

Every export needs a fresh second factor, to request and again to download, and is limited
to three running jobs per person. The file is built with the requester's own role, scope and
grants, so it can only hold what they could see on screen. Text a spreadsheet would read as a
formula is neutralized. Results files are tagged `PROVISIONAL` and say so inside. Files are
purged after 72 hours; the job record and its audit entries stay.

An **evidence pack** holds the original photos, `manifest.json` (SHA-256 and the hash-chained
custody events for each file), `results.csv`, and `verify.py`, a standard-library script that
recomputes every hash and chain offline and prints the manifest's digest (also recorded on the
job as `manifest_sha256`). Only VERIFIED photos go in; one whose stored bytes no longer match
its hash is left out and listed. Exporting is itself a custody event on each photo. A pack
proves integrity and custody; it does not claim legal admissibility. Selections beyond 2,000
photos or 1 GiB must be narrowed (by contest, LGA, ward or polling unit).

**Administration** (admin by default):

- `GET /api/v1/audit/events`: the organization's audit trail, filtered, in windows of at most
  31 days.
- `GET /api/v1/admin/health`: database, cache, broker and storage checks, outbox and audit
  sealing backlog, and the organization's stuck uploads, failed deliveries and exports, and
  unacknowledged critical flags.
- `GET /api/v1/elections/{id}/analytics`: onboarding and activation, assignment completion,
  submission completion, offline share and sync delay, evidence success, and anomaly rates,
  inside the caller's scope.
- `GET /api/v1/admin/data-quality`: gaps in the polling-unit directory.
- `GET|PUT|DELETE /api/v1/admin/alert-policy`: the organization's override of the escalation
  matrix (who is told, on which channels, and the acknowledgement window). Changes need a fresh
  second factor and are audited with before and after.

**Retention (PB-09, DG-04)** defaults, pending the approved policy: exports 72 hours;
evidence 7 years, results and audit 10 years, notifications 1 year, counted from
reconciliation (`VTRS_RETENTION_YEARS`). Nothing is deleted automatically.
`python manage.py retention_report [--json]` lists what has passed its period so a person
with legal sign-off can act on it. Evidence is never purged while an election is not
RECONCILED.

## Providers, hardening and operations

- **Providers (PB-07).** Select by dotted path: `VTRS_SMS_PROVIDER` and
  `VTRS_WHATSAPP_PROVIDER` (`TwilioSmsProvider`, `TwilioWhatsAppProvider`; delivery receipts
  arrive on `POST /api/v1/webhooks/twilio/status`, verified by signature), `VTRS_PUSH_PROVIDER`
  (`FcmPushProvider`, HTTP v1 with a service account), `VTRS_BOT_CHALLENGE_PROVIDER`
  (`turnstile`, `hcaptcha` or `recaptcha`, fail-closed) and `VTRS_MALWARE_SCANNER`
  (`ClamAvScanner`, clamd over TCP; a scan that cannot finish is an error, never "clean").
  Every outbound call goes through one HTTP seam (https only, timeouts, no redirects).
- **Boundary.** CORS is an exact-origin allowlist (`VTRS_CORS_ALLOWED_ORIGINS`), also used for
  WebSocket origins; API responses are `no-store` with a restrictive CSP; oversized bodies are
  413 and NUL characters in query strings 400, never 500.
- **Dependencies.** `pip-audit` is clean at the pinned ranges. Re-run it (and `bandit -r apps
  config`) before each release.
- **Workers.** Celery's Django fixup is disabled and the prefetch multiplier is 4; see
  `config/celery.py` and `docs/runbook.md` for why and how to run them.
- **Key rotation.** `python manage.py reencrypt_fields [--dry-run]` re-seals encrypted columns
  onto the active key after rotating `VTRS_FIELD_ENCRYPTION_KEYS`.
- **Simulation and load.** `VTRS_ALLOW_SIMULATION=1 python manage.py simulate_election_day
  --agents 1000` (development or staging only).
- **Documents.** `docs/threat-model.md`, `docs/runbook.md` and `docs/pilot-readiness.md`.

## API contract

`docs/openapi.yaml` is the contract web and mobile build against, and a test keeps it in
sync with the code. After an intended API change, regenerate it and review the diff:

```sh
python manage.py spectacular --file docs/openapi.yaml --validate
```

In development the live schema is also served at `/api/v1/schema`.

## Master data

```sh
python manage.py import_master_data path/to/polling_units.csv [--dry-run] [--report out.json]
```

The CSV has one row per polling unit, with these columns: `state_code, state_name, lga_code,
lga_name, ward_code, ward_name, pu_code, pu_name, latitude, longitude, registered_voters`.
The importer validates counts, unique codes, parent consistency and coordinates. Any error
rejects the whole file. Re-importing the same file changes nothing.

The synthetic dataset (codes prefixed `SYN`) stands in until the approved INEC directory is
provided.

## Audit log

Audit events are written in the same transaction as the action they record. The table is
partitioned monthly and is append-only (enforced by a trigger and by grants). A sealer task
groups new events into batches, computes a Merkle root for each batch and chains it to the
previous batch. To verify the chain:

```sh
python manage.py verify_audit_chain
```

## Background tasks

```sh
celery -A config worker -Q default,ingest,aggregation,evidence,anomaly,notifications,reports
celery -A config beat
```

Beat relays the outbox every second, seals audit batches every five seconds, extends audit
partitions daily and purges expired idempotency and outbox rows hourly.
