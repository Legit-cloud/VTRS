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
