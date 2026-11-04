# DMP Agent Orchestrator

This repository contains the core through checkpoint 12 of the multi-agent orchestrator
specification. Provider execution, scheduling, API routes, and later lifecycle operations
are outside this checkpoint.

Python 3.12 and uv are required. Set `DATABASE_URL` to an async-compatible PostgreSQL
URL (`postgresql+psycopg://...`) and `REDIS_URL` before configuring the service. Do not
commit credentials. Install and validate with:

```sh
uv sync
uv run alembic upgrade head
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

To include database integration tests, set `TEST_DATABASE_URL` to a **dedicated, migrated**
test database. The tests insert test records and must not run against production.

The owner must supply transition and accepted-dependency policies, lock lease duration,
workspace and deployment settings, PII patterns, retention, and repository policy defaults.
Empty command and network policy defaults deny access; they do not select business policy.
