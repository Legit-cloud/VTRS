PY ?= .venv/bin/python
MIGRATE_DATABASE_URL ?= postgres://vtrs_migrator:vtrs_migrator_dev@localhost:5432/vtrs

.PHONY: venv up down migrate seed test lint check

venv:
	python3.12 -m venv .venv
	$(PY) -m pip install -r requirements-dev.txt

up:
	docker compose up -d

down:
	docker compose down

migrate:
	DATABASE_URL=$(MIGRATE_DATABASE_URL) $(PY) manage.py migrate

seed:
	mkdir -p var
	$(PY) manage.py generate_synthetic_geography --out var/synthetic_oyo.csv
	$(PY) manage.py import_master_data var/synthetic_oyo.csv --report var/import_report.json

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	.venv/bin/lint-imports

check: lint test
