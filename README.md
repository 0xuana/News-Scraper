# Aigupiao News Collector

A modular Python service that collects Aigupiao news, removes unnecessary comment/user data,
and stores idempotent records and stock/theme relationships in PostgreSQL.

## Setup

Requires Python 3.11+ and PostgreSQL.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/python -m collector init-db
```

Set `DATABASE_URL` in `.env` before initializing the schema.

## Run

```bash
.venv/bin/python -m collector backfill
.venv/bin/python -m collector backfill --before 1789617870
.venv/bin/python -m collector live
.venv/bin/python -m collector final-refresh
.venv/bin/python -m collector probe --date 2020-01-01
```

Backfill resumes from `crawler_state`; its news writes and cursor update share one transaction.
Live mode always requests the newest page and relies on the news primary key for idempotency.

Run `final-refresh` daily (for example, from cron or a systemd timer). It walks backward from
the newest page through the one-calendar-month boundary, refreshes engagement and metadata,
then sets `finalized_at` on due rows. Finalized rows and their relationships are immutable.

Structured metadata includes themes, theme quotes, concepts, topics, stock/plate quotes, stock
codes, and view/support/oppose/share/comment counters. The API's 24-hour-hot fields are stored
separately; they are not presented as a verified news-pinning flag.

## Verify

```bash
.venv/bin/ruff check .
.venv/bin/pytest
```

Tests use mocks and local JSON fixtures; they never call the production API.

## Docker

Copy the example environment file and change the PostgreSQL password before using the
configuration outside local development:

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f collector
```

The default stack starts PostgreSQL, waits for it to become healthy, initializes the schema,
and then runs the live collector. PostgreSQL data is retained in the `postgres-data` named
volume. `DATABASE_URL` from `.env` is intended for commands run on the host; Compose replaces
it with the internal `db` hostname for containers.

Run other collector modes as one-shot containers:

```bash
docker compose run --rm collector backfill
docker compose run --rm collector backfill --before 1789617870
docker compose run --rm collector final-refresh
docker compose run --rm collector probe --date 2020-01-01
```

Stop the services without deleting database data:

```bash
docker compose down
```

To intentionally delete the PostgreSQL volume as well, use `docker compose down --volumes`.
