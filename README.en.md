# Aigupiao News Collector

[简体中文](README.md) | [English](README.en.md)

A long-running Python collector that paginates through the Aigupiao news feed, parses article,
stock, theme, and topic data, and stores it idempotently in PostgreSQL. The default Docker
workflow backfills the latest 60 days once, then performs an hourly paginated synchronization
with a persisted checkpoint and a protective time overlap.

Use this project when you want to accumulate a long-term historical news corpus for a RAG
knowledge base that strengthens an agent's retrieval, context, event tracking, and analysis.
It supplies structured, deduplicated, restart-safe source data for downstream chunking, embedding,
and retrieval; it does not itself provide a vector database or RAG query service.

## Collection behavior

- Historical and incremental requests paginate by `rec_time`, so collection is not limited to
  the newest 20-item response.
- News and its relationships use idempotent UPSERTs, making overlap and retries safe.
- A checkpoint advances only after the entire target window succeeds. A failed cycle is retried
  after restart instead of being incorrectly marked complete.
- Timeouts, rate limits, server failures, malformed JSON, and non-advancing cursors are handled
  explicitly.

### Scheduled synchronization boundaries

`scheduled` is the default Docker mode:

- **Initial cycle:** pages backward until the oldest item reaches
  `current time - INITIAL_BACKFILL_DAYS`, or until the server returns an empty page. Items older
  than the boundary on the final page are not stored.
- **Later cycles:** page backward until the oldest item reaches
  `last successful checkpoint - SYNC_OVERLAP_SECONDS`, or until an empty page is returned.
- **Failure:** exhausted HTTP retries, parsing/database failures, or a cursor that no longer moves
  backward terminate the process without advancing the checkpoint. Docker can then restart it.
- **Final refresh:** after regular synchronization, scheduled mode automatically refreshes through
  the one-calendar-month boundary when `FINAL_REFRESH_INTERVAL` has elapsed (daily by default),
  then freezes due rows. No separate cron job is required.
- **Lifecycle:** after regular synchronization and any due final refresh complete, the process
  sleeps for `SYNC_INTERVAL` seconds and repeats indefinitely.

The “last successful checkpoint” is the Unix timestamp captured at the **start** of the previous
cycle and stored as `aigupiao_scheduled` in `crawler_state`. It is not a page cursor, the timestamp
of the last stored article, or the cycle completion time. Starting from this timestamp covers news
published while the prior cycle was running; the overlap adds boundary protection. Final refreshes
use a separate `aigupiao_final_refresh` checkpoint. Neither checkpoint advances on partial failure.

The default five-minute overlap protects news published at the same boundary second, records
that become visible late, and feeds that change around pagination time. Duplicate reads are
absorbed by the news-ID UPSERT, trading a small amount of repeated work for a safer boundary.

## Setup

Requires Python 3.11+ and PostgreSQL.

<details open>
<summary><strong>Option 1: uv (recommended for local testing)</strong></summary>


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

</details>

<details>
<summary><strong>Option 2: requirements.txt</strong></summary>


```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python -m collector init-db
```

Set `DATABASE_URL` in `.env` before initializing the schema.

</details>

<details>
<summary><strong>Option 3: editable development installation</strong></summary>

For development, install `requirements-dev.txt` and the project in editable mode:

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

</details>

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string | Required except for `probe` |
| `AIGUPIAO_BASE_URL` | Aigupiao feed URL | Built in |
| `AIGUPIAO_REQUEST_INTERVAL` | Delay between paginated requests | `3` seconds |
| `LIVE_INTERVAL` | Delay between `live` requests | `45` seconds |
| `INITIAL_BACKFILL_DAYS` | Initial scheduled history window | `60` days |
| `SYNC_INTERVAL` | Delay after each scheduled cycle | `3600` seconds |
| `SYNC_OVERLAP_SECONDS` | Backward overlap for incremental cycles | `300` seconds |
| `FINAL_REFRESH_INTERVAL` | Minimum interval between successful automatic final refreshes | `86400` seconds |
| `HTTP_TIMEOUT` | HTTP request timeout | `15` seconds |
| `MAX_RETRIES` | Retries for temporary request failures | `5` |
| `MAX_BACKOFF` | Maximum exponential-backoff delay | `60` seconds |

Copy `.env.example` and adjust it, for example:

```dotenv
DATABASE_URL=postgresql://postgres:change-me@localhost:5432/news
POSTGRES_DB=news
POSTGRES_USER=postgres
POSTGRES_PASSWORD=change-me
POSTGRES_PORT=5432

AIGUPIAO_BASE_URL=https://apis.aigupiao.com/Express/express_list/
AIGUPIAO_REQUEST_INTERVAL=3
LIVE_INTERVAL=45
INITIAL_BACKFILL_DAYS=60
SYNC_INTERVAL=3600
SYNC_OVERLAP_SECONDS=300
FINAL_REFRESH_INTERVAL=86400
HTTP_TIMEOUT=15
MAX_RETRIES=5
MAX_BACKOFF=60
```

URL-encode passwords containing characters such as `@`, `:`, or `/` inside `DATABASE_URL`, and
replace the example password in production.

## Run

```bash
.venv/bin/python -m collector backfill
.venv/bin/python -m collector backfill --before 1789617870
.venv/bin/python -m collector live
.venv/bin/python -m collector scheduled
.venv/bin/python -m collector final-refresh
.venv/bin/python -m collector probe --date 2020-01-01
```

| Command or argument | Meaning and behavior |
| --- | --- |
| `init-db` | Idempotently applies the bundled PostgreSQL schema and exits without collecting |
| `backfill` | Resumes its per-page cursor and paginates indefinitely into history until an empty page |
| `backfill --before UNIX_TIMESTAMP` | Ignores the saved backfill cursor for this run; `0` starts at the newest page |
| `live` | Repeatedly fetches only `before=0`, without pagination, sleeping `LIVE_INTERVAL` between polls |
| `scheduled` | Runs bounded checkpointed synchronization plus automatic checkpointed final refreshes indefinitely |
| `final-refresh` | Forces a refresh through the one-month boundary now, freezes due rows, saves its checkpoint, and exits |
| `probe --date YYYY-MM-DD` | Uses 00:00 on that date in Asia/Shanghai as the one-page cursor, prints JSON, and never opens the database |

Use `python -m collector COMMAND --help` for the same command-specific details. Normally,
`scheduled` is the only long-running process required; explicit `final-refresh` remains useful for
an immediate maintenance run.

## Verify

```bash
.venv/bin/ruff check .
.venv/bin/pytest
```

Tests use mocks and local JSON fixtures; they never call the production API.

## Docker

<details>
<summary><strong>Option 4: Docker Compose (recommended for deployment)</strong></summary>

Copy the example environment file and change the PostgreSQL password before using the
configuration outside local development:

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f news-collector
```

The default stack starts PostgreSQL, waits for it to become healthy, initializes the schema,
and then runs the scheduled collector. Its initial history window, synchronization interval,
overlap, and automatic final-refresh cadence are configured with `INITIAL_BACKFILL_DAYS`,
`SYNC_INTERVAL`, `SYNC_OVERLAP_SECONDS`, and `FINAL_REFRESH_INTERVAL`. PostgreSQL data is retained in the `postgres-data` named
volume. `DATABASE_URL` from `.env` is intended for commands run on the host; Compose replaces
it with the internal `db` hostname for containers.

Run other collector modes as one-shot containers:

```bash
docker compose run --rm news-collector backfill
docker compose run --rm news-collector backfill --before 1789617870
docker compose run --rm news-collector final-refresh
docker compose run --rm news-collector probe --date 2020-01-01
```

Stop the services without deleting database data:

```bash
docker compose down
```

To intentionally delete the PostgreSQL volume as well, use `docker compose down --volumes`.

</details>

## License

This project is licensed under the [Apache License 2.0](LICENSE).
