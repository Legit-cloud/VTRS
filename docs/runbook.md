# VTRS operations runbook

For the people who run VTRS before, during and after an election. Commands assume the project
root as the working directory and the production environment loaded.

## 1. The moving parts

| Process | Command | Scale by |
| --- | --- | --- |
| API (HTTP and WebSocket) | `daphne -b 0.0.0.0 -p 8000 config.asgi:application` behind the load balancer | more instances; stateless |
| Workers | `celery -A config worker -Q default,ingest,aggregation,evidence,anomaly,notifications,reports -c N` | more processes, more hosts |
| Scheduler | `celery -A config beat` | exactly **one** instance |
| PostgreSQL 16 | managed, with a replica for reporting (`vtrs_readonly`) | vertical, then read replica |
| Redis (cache, broker, channels) | three separate instances | each independently |
| Object storage | S3-compatible, private bucket, versioning and object lock on | provider |

Run workers as **processes**, not threads, in production (`-P prefork`, Linux). Threads share
one interpreter lock, so one worker process behaves like roughly one core. Give the
`aggregation` queue its own worker so a flood of photo verification cannot delay the dashboards.

Celery's built-in Django fixup is deliberately disabled (`config/celery.py`); it throttled
every worker to a few tasks per second. Do not re-enable it. The prefetch multiplier is 4 for
the same reason (at 1, short tasks stall between polling ticks); run the `reports` queue on its
own worker with `--prefetch-multiplier=1 -c 2` so a long export never holds other work.

## 2. Environment

Required in production (the process refuses to start otherwise): `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DATABASE_URL` (as `vtrs_app`),
`REDIS_CACHE_URL`, `CELERY_BROKER_URL`, `REDIS_CHANNELS_URL`, `VTRS_JWT_PRIVATE_KEY`,
`VTRS_FIELD_ENCRYPTION_KEYS`, `VTRS_BLIND_INDEX_KEY`, `VTRS_OTP_PEPPER`.

Providers: `VTRS_SMS_PROVIDER`, `VTRS_PUSH_PROVIDER`, `VTRS_WHATSAPP_PROVIDER`,
`VTRS_BOT_CHALLENGE_PROVIDER` and `VTRS_BOT_CHALLENGE_SECRET`, `VTRS_MALWARE_SCANNER` and
`VTRS_CLAMD_HOST`, plus the vendor credentials (`VTRS_TWILIO_*`, `VTRS_FCM_SERVICE_ACCOUNT_JSON`).
`VTRS_PUBLIC_BASE_URL` and `VTRS_CORS_ALLOWED_ORIGINS` (exact `https://` origins of the portal).

Production settings refuse the development stand-ins, `*` origins and incomplete provider
configuration, so a bad deployment fails at start, not at 6 pm.

## 3. Deploying

1. Take a database snapshot.
2. Run migrations as the owner role: `DATABASE_URL=<vtrs_migrator url> python manage.py migrate`.
3. `python manage.py check --deploy` with production settings.
4. Roll the API, then workers, then beat. Migrations are written to be backwards compatible
   with the previous release for one version, so a rolling deploy is safe.
5. Smoke test: `GET /api/v1/health/ready`, then `GET /api/v1/admin/health` as an admin.

## 4. Before Election Day

| When | Do |
| --- | --- |
| T-14 days | Import and verify the polling-unit directory (`import_master_data --dry-run`, then for real); review `/api/v1/admin/data-quality` |
| T-14 days | Configure the election, contests and candidates; lock it (needs a fresh second factor) |
| T-10 days | Invite and deploy agents; track activation in `/elections/{id}/analytics`; load-test and simulate (section 8) |
| T-7 days | Rehearse restore (section 7) and key rotation (section 9); confirm provider balances and sender registrations |
| T-3 days | Freeze deployments; confirm alert policy and the officer chain for every ward and LGA (`/admin/alert-policy`) |
| T-1 day | Move the election to LIVE (a worker builds every rollup row; confirm `reported/expected` shows the full unit count); verify `verify_rollups` and `verify_audit_chain` are clean |
| T-0 | Staff the command centre; watch health and the review queue |

## 5. During the election

Watch, in this order:

1. `GET /api/v1/admin/health`. Anything not `ok` has a component and a number.
2. The outbox backlog age (`outbox.oldest_seconds`). Above 60 seconds is degraded, above 300
   is down: events are not reaching workers. See section 6.
3. `audit_sealing.oldest_seconds`. Above 600 seconds means sealing is stuck.
4. Unacknowledged CRITICAL flags (`flags.open_critical`). Someone must own each.
5. Failed deliveries and quarantined photos.

Useful at any time, all read-only and safe to repeat:

```sh
python manage.py verify_rollups --election <id>   # exits non-zero on any difference
python manage.py verify_audit_chain
python manage.py rebuild_rollups --election <id>  # repair, then verify again
```

## 6. Incidents

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Dashboard figures lag results | Workers behind, or the `aggregation` queue starved | Check queue depth; add `aggregation` workers; `drain_stale_marks` runs every 10 s as a safety net |
| `rollup_differences` in readiness, or `verify_rollups` fails | A lost event or a worker died mid-update | Live elections self-check every 5 minutes and rebuild (audited as `rollup.self_healed`); otherwise `rebuild_rollups --election <id>`, then investigate the cause |
| Outbox backlog growing | Broker unreachable, or no workers on that queue | Restore the broker; `core.relay_outbox` replays everything once it is back |
| Photos stuck in PENDING_UPLOAD | Object store unreachable from devices, or presign clock skew | Check the store and its clock; `reconcile_pending_uploads` completes orphans automatically |
| Photos quarantined in bulk | Scanner down (fails closed) or a genuinely bad batch | Check `VTRS_CLAMD_HOST`; quarantined files stay recoverable under `quarantine/` |
| SMS not arriving | Provider outage or sender not approved | Deliveries retry three times; failures show per message; switch provider by changing `VTRS_SMS_PROVIDER` |
| OTP endpoints returning 503 | Bot-challenge provider unreachable (fails closed) | Restore reachability; do **not** set the provider to `disabled` in production |
| An agent cannot submit | Wrong device, unassigned unit, election not LIVE | The refusal code says which; reassign through `/assignments` |
| A wrong result was submitted | Agent or officer error | Never edit data. The agent resubmits (new version) or the reviewer rejects with a reason |

If you suspect tampering: stop writing nothing, run `verify_audit_chain` and
`verify_rollups`, export the audit window and the affected evidence pack, and escalate.

## 7. Backup and restore

What to back up: PostgreSQL (the system of record), the object store bucket (versioned, with
object lock; the platform never overwrites an original), and the secrets vault.

Procedure (rehearsed; section 8 records the drill):

1. `pg_dump --format=custom --no-owner --file=vtrs.dump <database>` (or a base backup plus WAL
   archiving for point-in-time recovery in production).
2. Restore into an empty database: `createdb vtrs_restore; pg_restore --no-owner
   --dbname=vtrs_restore vtrs.dump`.
3. Point a throwaway environment at it and run, as a gate before declaring it good:
   `python manage.py verify_audit_chain`, `python manage.py verify_rollups`, and the health
   endpoint.
4. Evidence: spot-check a sample of photos against `sha256_server`, or build a pack and run its
   `verify.py`.

Targets to agree with the business: recovery point (WAL archiving gives minutes) and recovery
time. Both should be exercised in the dry run, not assumed.

## 8. Simulation and load

```sh
VTRS_ALLOW_SIMULATION=1 python manage.py simulate_election_day --agents 1000 --workers 12 --readers 25
```

Creates a throwaway organization on the polling-unit directory, submits through the real API
with retries, corrections and injected anomalies while dashboard users read, waits for the
workers, and reports throughput, latency, consistency (rollups against a fresh calculation, and
the audit chain). It refuses to run unless `DEBUG` is on or `VTRS_ALLOW_SIMULATION=1`, because
it writes data: use a staging stack, never production.

Reference numbers from a single developer laptop (8 logical cores, Postgres and Redis in
containers, one worker process with eight threads, simulator and workers on the same machine):

| Measure | Result |
| --- | --- |
| Sustained submissions | 4.4 to 5.1 per second (15,700 to 18,400 per hour) with the generator on the same cores |
| Dashboard | about 0.25 s p50 and 0.4 s p95 with five readers; 1.0 s and 3.5 s with twenty under write load |
| Target (PRD 7.6) | 10,000 submissions per hour (2.8 per second); dashboard under 3 seconds |

Full tables, and what the load work changed, are in `docs/pilot-readiness.md`.

Treat laptop numbers as a floor. Repeat on staging hardware before sign-off (DD-06).

## 9. Keys and secrets

| Secret | Rotation |
| --- | --- |
| JWT signing key | Add the new key id to `VTRS_JWT_PUBLIC_KEYS`, switch `VTRS_JWT_PRIVATE_KEY` and `VTRS_JWT_KEY_ID`, keep the old public key until access tokens (10 minutes) expire, then remove it |
| Field encryption keys | Add a new id to `VTRS_FIELD_ENCRYPTION_KEYS` and make it active; old ids stay readable. `python manage.py reencrypt_fields` rewrites rows to the active key; retire the old id afterwards |
| Blind-index key | Not rotatable without re-indexing every lookup column: treat as permanent and protect accordingly |
| Provider credentials | Rotate at the provider, update the vault, restart workers (tokens are read at start) |
| Database passwords | Rotate `vtrs_app` and `vtrs_migrator` separately; connections are short lived |

## 10. After the election

1. Close polls (`CLOSED`). Late submissions are accepted and flagged.
2. Review every flag and result decision; with review on, reconciliation is blocked until each
   counting result is decided.
3. `GET /elections/{id}/reconciliation`, then `POST /elections/{id}/reconcile` (fresh second
   factor). The snapshot and its SHA-256 are the record of what was counted.
4. Export what is needed (results, flag register, evidence packs). Exports expire after 72
   hours; keep the files and the recorded digests.
5. `python manage.py retention_report` lists what has passed its retention period. Nothing is
   deleted automatically; deletion needs legal sign-off.
