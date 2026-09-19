# Aigupiao News Collector

[简体中文](README.md) | [English](README.en.md)

A long-running Python news collection service. It paginates through the Aigupiao news feed, parses article bodies, titles, stocks, themes, and topic relationships, and stores them idempotently in PostgreSQL with UPSERTs. The default Docker workflow backfills the latest 60 days once and then performs an hourly incremental synchronization with a protective time overlap. Synchronization checkpoints are persisted in the database, so network failures or container restarts do not restart a completed historical backfill from the beginning.

Use this project when you want to accumulate a long-term historical news corpus and use it as a RAG knowledge base to strengthen an agent's historical retrieval, context enrichment, event tracking, and analysis. It continuously provides structured, deduplicated, restart-safe news data for downstream chunking, embedding, and retrieval; the project itself does not include a vector database or RAG query service.

## Key features

- Paginate backward through historical news by the `rec_time` cursor with checkpoint-based resume support.
- Continuously poll the latest news and write idempotently by news ID.
- Read article bodies from `web_content` and extract titles from a leading `【…】` block.
- Preserve cleaned raw JSON, including original content fields, after removing empty values.
- Handle timeouts, rate limits, server errors, and JSON parsing failures.
- Support a bounded initial historical backfill and paginated incremental synchronization that is not limited by the API's 20-item page size.
- Advance a checkpoint only after the entire synchronization cycle succeeds; safely retry failed cycles after restart.
- Start PostgreSQL, initialize the database, and run scheduled collection with one Docker Compose command.

## Scheduled synchronization semantics

`scheduled` is the default Docker operating mode:

- **Initial run:** page backward from the newest page. The cycle ends when the oldest news item on a page reaches `current time - INITIAL_BACKFILL_DAYS`, or when the API returns an empty page. On a page that crosses the boundary, only items inside the configured window are stored.
- **Later runs:** page backward from the newest page until the oldest item reaches `last successful checkpoint - SYNC_OVERLAP_SECONDS`, or until the API returns an empty page.
- **Success:** save the cycle start time as the new checkpoint only after every target page has been parsed and written successfully.
- **Failure:** exhausted HTTP retries, parsing failures, database write failures, or a pagination cursor that no longer moves backward terminate the process without advancing the checkpoint. Docker then restarts it according to the service restart policy.
- **Final refresh:** after regular synchronization, automatically refresh from the newest page through the one-calendar-month boundary and freeze all due records when no final refresh has succeeded before or when the independent checkpoint is at least `FINAL_REFRESH_INTERVAL` seconds old. This runs every 24 hours by default, so no separate cron job is required.
- **Process lifecycle:** after regular synchronization and any final refresh due in that cycle complete, sleep for `SYNC_INTERVAL` seconds before starting the next cycle. Completing one cycle does not terminate the process.

The “last successful checkpoint” is the Unix timestamp captured from the system clock at the **start** of the previous cycle and stored in the `aigupiao_scheduled` row of `crawler_state`. It is not the previous page cursor, the timestamp of the last stored article, or the cycle completion time. Using the start time covers news published while the previous cycle was running, and subtracting the overlap protects the pagination boundary. Final refreshes use an independent `aigupiao_final_refresh` checkpoint representing the start time associated with the last fully successful “refresh through the one-month boundary and freeze due records” operation. A partial failure advances neither corresponding checkpoint.

The overlap window defaults to five minutes. It protects news published in the same boundary second, records that become visible after a short delay, and feed changes around pagination time. News-ID UPSERTs absorb duplicate reads, trading a small amount of repeated work for a safer synchronization boundary.

## Requirements

- Python 3.11 or later
- PostgreSQL
- Optional: Docker and Docker Compose

## Installation options

<details open>
<summary><strong>Option 1: uv (recommended for local testing)</strong></summary>


The committed `uv.lock` lets `uv` create `.venv` and install locked dependencies automatically. If `uv` is not installed, use the following command on Linux and macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Install the project and development/test dependencies:

```bash
uv sync --extra dev
```

Run local tests and lint checks without contacting the production API or requiring PostgreSQL:

```bash
uv run pytest
uv run ruff check news_collector tests
```

Request one real API page without writing to the database:

```bash
uv run python -m news_collector probe --date 2026-09-17
```

To test the complete persistence workflow, copy and configure `.env`, make sure PostgreSQL is running, and then initialize the database and start backfill:

```bash
cp .env.example .env
uv run python -m news_collector init-db
uv run python -m news_collector backfill
```

Press `Ctrl+C` to stop backfill. Running the same command again resumes from the database checkpoint. Start live collection with:

```bash
uv run python -m news_collector live
```

See the [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) for more installation options.

</details>

<details>
<summary><strong>Option 2: requirements.txt</strong></summary>


Use this option to run the collector directly:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python -m news_collector init-db
```

Activate the virtual environment on Windows PowerShell with:

```powershell
.venv\Scripts\Activate.ps1
```

</details>

<details>
<summary><strong>Option 3: pip development environment</strong></summary>


`requirements-dev.txt` includes pytest and Ruff in addition to runtime dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e .
cp .env.example .env
```

You can also install development dependencies directly from the project metadata:

```bash
python -m pip install -e '.[dev]'
```

`requirements.txt` and `requirements-dev.txt` use the same dependency ranges as `pyproject.toml`. Keep all three files synchronized when changing project dependencies.

</details>

<details>
<summary><strong>Option 4: Docker Compose (recommended for deployment)</strong></summary>


```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f news-collector
```

The default stack starts PostgreSQL, waits for its health check, initializes the schema, and then starts the scheduled collector. The first run paginates through the latest 60 days; later runs synchronize hourly from the last successful time with a five-minute protective overlap. It also performs an automatic final refresh every 24 hours by default. Both checkpoints are stored in PostgreSQL, so a container restart does not repeat the complete 60-day backfill or a final refresh that is not yet due. Data is retained in the `postgres-data` named volume.

Docker fully supports `scheduled`, and it is the default command of the `news-collector` service in `compose.yaml`. Common operations are:

```bash
# Recommended: start PostgreSQL, initialization, and the long-running scheduled service
docker compose up --build -d

# Check service status and continuously follow scheduled logs
docker compose ps
docker compose logs -f news-collector

# Restart from the same database checkpoints after a configuration change or failure
docker compose restart news-collector

# Foreground debugging only; scheduled runs until you press Ctrl+C
docker compose run --rm news-collector scheduled
```

Use `docker compose up -d` to manage the long-running deployment. The final `run --rm` command is only for explicit verification or temporary debugging and does not replace the Compose service restart policy.

</details>

## Configuration

Review the settings in `.env` before initializing the database:

| Variable | Scope and exact behavior | Default |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string used by `init-db` and every database-writing collection command; only `probe` does not require it | None; required |
| `AIGUPIAO_BASE_URL` | Aigupiao API endpoint used by every networked command | Built in |
| `AIGUPIAO_REQUEST_INTERVAL` | Seconds to sleep between adjacent requests during `backfill`, `scheduled` pagination, and `final-refresh`; must be greater than zero | `3` |
| `LIVE_INTERVAL` | Seconds `live` sleeps after each newest-page request; must be greater than zero | `45` |
| `INITIAL_BACKFILL_DAYS` | History window, measured backward from the cycle start time, saved when `scheduled` has no synchronization checkpoint; must be a positive integer | `60` days |
| `SYNC_INTERVAL` | Seconds `scheduled` sleeps after regular synchronization and any due final refresh before starting the next cycle; must be greater than zero | `3600` |
| `SYNC_OVERLAP_SECONDS` | Extra seconds a later `scheduled` cycle reads before the last successful checkpoint; may be `0` | `300` |
| `FINAL_REFRESH_INTERVAL` | Minimum seconds between successful automatic final refreshes in `scheduled`; an independent database checkpoint preserves this across restarts; must be greater than zero | `86400` |
| `HTTP_TIMEOUT` | Timeout in seconds for one HTTP request; must be greater than zero | `15` |
| `MAX_RETRIES` | Maximum additional attempts after the first request fails with a temporary HTTP or network error; may be `0` | `5` |
| `MAX_BACKOFF` | Maximum seconds allowed for exponential-backoff and `Retry-After` waits; must be greater than zero | `60` |

Copy `.env.example` and adjust it as needed, for example:

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

URL-encode passwords containing characters such as `@`, `:`, or `/` inside `DATABASE_URL`. Replace the example password in production.

Docker Compose uses `db` as the database hostname inside containers and overrides the host environment's `DATABASE_URL`.

## Running

The Python package directory and module name are both `news_collector`, so source environments use `python -m news_collector`. An installed project also provides the equivalent `news-collector` command, for example `news-collector scheduled`.

```bash
python -m news_collector backfill
python -m news_collector backfill --before 1789617870
python -m news_collector live
python -m news_collector scheduled
python -m news_collector final-refresh
python -m news_collector probe --date 2020-01-01
```

| Command or argument | Meaning and behavior |
| --- | --- |
| `init-db` | Idempotently apply the bundled PostgreSQL schema and exit without collecting news |
| `backfill` | Resume from its dedicated per-page checkpoint and continue paginating into history; save each page and its next-page cursor in one transaction, then exit on an empty page |
| `backfill --before UNIX_TIMESTAMP` | Ignore the saved backfill checkpoint and start from the specified Unix-second cursor; `0` starts from the newest page. The override value itself is not written to the database before collection |
| `live` | Always fetch the newest page with `before=0` without paginating; repeat after `LIVE_INTERVAL` and deduplicate with news-ID UPSERTs |
| `scheduled` | Backfill a bounded window initially, then synchronize from the previous successful cycle start minus the overlap, while automatically running `final-refresh` on its independent cadence; runs indefinitely |
| `final-refresh` | Force one final refresh immediately regardless of whether the automatic refresh is due; update data through the one-calendar-month boundary, freeze due rows, save its independent checkpoint, and exit |
| `probe --date YYYY-MM-DD` | Convert 00:00 on that date in Asia/Shanghai into the `before` cursor, request and parse one page, and print the cursor and item count as JSON without connecting or writing to the database |

Use `python -m news_collector COMMAND --help` to see the same behavior and argument details for each subcommand. Normally, `scheduled` is the only long-running process required; explicit `final-refresh` remains available for immediate refreshes, diagnostics, or maintenance.

Run these commands in one-shot Docker containers:

```bash
docker compose run --rm news-collector scheduled
docker compose run --rm news-collector backfill
docker compose run --rm news-collector backfill --before 1789617870
docker compose run --rm news-collector final-refresh
docker compose run --rm news-collector probe --date 2020-01-01
```

`scheduled` is a long-running task. In Docker, the recommended startup method is `docker compose up --build -d` as described above, so it should not normally be treated as a one-shot command.

## Verification

```bash
ruff check news_collector tests
pytest
```

Tests use mocks and local JSON fixtures; they never contact the production API.

## Stopping Docker services

```bash
docker compose down
```

This command preserves the database volume. Use `docker compose down --volumes` only when you intentionally want to delete the PostgreSQL data.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
