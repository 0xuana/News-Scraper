# Aigupiao News Collector

[简体中文](README.md) | [English](README.en.md)

A modular Python service that collects Aigupiao news, removes unnecessary comment/user data,
and stores idempotent records and stock/theme relationships in PostgreSQL.

## Setup

Requires Python 3.11+ and PostgreSQL.

### uv workflow (recommended for local testing)

The committed `uv.lock` lets `uv` create `.venv` and install locked dependencies. Install
`uv` by following the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/),
then synchronize the project with its test tools:

```bash
uv sync --extra dev
```

Run the offline unit tests and lint checks without activating the virtual environment:

```bash
uv run pytest
uv run ruff check collector tests
```

Probe one real API page without writing to PostgreSQL:

```bash
uv run python -m collector probe --date 2026-09-17
```

To test database persistence, copy and configure the environment file, start PostgreSQL, and
run the initialization and backfill commands:

```bash
cp .env.example .env
uv run python -m collector init-db
uv run python -m collector backfill
```

Press `Ctrl+C` to stop backfill. A later invocation resumes from the stored checkpoint. Run the
live collector with:

```bash
uv run python -m collector live
```

### pip workflow

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python -m collector init-db
```

Set `DATABASE_URL` in `.env` before initializing the schema.

For development, install `requirements-dev.txt` and the project in editable mode:

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

## Run

```bash
.venv/bin/python -m collector backfill
.venv/bin/python -m collector backfill --before 1789617870
.venv/bin/python -m collector live
.venv/bin/python -m collector scheduled
.venv/bin/python -m collector final-refresh
.venv/bin/python -m collector probe --date 2020-01-01
```

Backfill resumes from `crawler_state`; its news writes and cursor update share one transaction.
Live mode always requests the newest page and relies on the news primary key for idempotency.
Scheduled mode initially paginates through the latest 60 days, then synchronizes every hour
from the last successful checkpoint with a five-minute overlap. It advances the checkpoint
only after a complete cycle, so container restarts safely resume incremental collection.

Run `final-refresh` daily (for example, from cron or a systemd timer). It walks backward from
the newest page through the one-calendar-month boundary, refreshes engagement and metadata,
then sets `finalized_at` on due rows. Finalized rows and their relationships are immutable.

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
and then runs the scheduled collector. Its initial history window, synchronization interval,
and overlap are configured with `INITIAL_BACKFILL_DAYS`, `SYNC_INTERVAL`, and
`SYNC_OVERLAP_SECONDS`. PostgreSQL data is retained in the `postgres-data` named
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

## License

This project is licensed under the [Apache License 2.0](LICENSE).
