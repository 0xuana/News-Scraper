# Aigupiao News Collector

[简体中文](README.md) | [English](README.en.md)

A long-running Python news collection service. It paginates through the Aigupiao news feed, parses article bodies, titles, stocks, themes, and topic relationships, and stores them idempotently in PostgreSQL with UPSERTs. The default Docker workflow maintains rolling coverage of the latest 80 days and performs an hourly incremental synchronization with a protective time overlap. Page-level historical progress is persisted in PostgreSQL so an interrupted first backfill resumes from its last committed page.

Use this project when you want to accumulate a long-term historical news corpus and use it as a RAG knowledge base to strengthen an agent's historical retrieval, context enrichment, event tracking, and analysis. It continuously provides structured, deduplicated, restart-safe news data for downstream chunking, embedding, and retrieval; the project itself does not include a vector database or RAG query service.

## Key features

- Paginate backward through historical news by the `rec_time` cursor with checkpoint-based resume support.
- Continuously poll the latest news and write idempotently by news ID.
- Read article bodies from `web_content` and extract titles from a leading `【…】` block.
- Preserve cleaned raw JSON, including original content fields, after removing empty values.
- Handle timeouts, rate limits, server errors, and JSON parsing failures.
- Maintain a configurable rolling-history window with an atomic page-and-cursor checkpoint.
- Catch up current news first after a restart, then resume unfinished historical pagination.
- Connect to PostgreSQL through `DATABASE_URL`, initialize the database, and run scheduled collection with Docker Compose.

## Scheduled synchronization semantics

`scheduled` is the default Docker operating mode:

- **Every run:** synchronize current news through `last successful checkpoint - SYNC_OVERLAP_SECONDS` first, then resume the historical cursor until the rolling `current time - INITIAL_BACKFILL_DAYS` boundary is covered.
- **Historical progress:** save each page and its oldest cursor in one transaction. A restart resumes that cursor instead of replaying the entire historical window. Existing installations without this new marker establish the rolling window once after upgrading.
- **Empty history:** an empty historical page is not immediately considered complete. The collector makes up to ten empty probes, moving ten minutes older each time; the counter and probe cursor also survive restarts.
- **Success:** save the current-sync checkpoint only after all its target pages succeed, and save an independent historical coverage boundary after reaching it or exhausting the ten probes.
- **Failure:** exhausted HTTP retries, parsing failures, database write failures, or a pagination cursor that no longer moves backward terminate the process without advancing the checkpoint. Docker then restarts it according to the service restart policy.
- **Final refresh:** after regular synchronization, automatically refresh from the newest page through the one-calendar-month boundary and freeze all due records when no final refresh has succeeded before or when the independent checkpoint is at least `FINAL_REFRESH_INTERVAL` seconds old. This runs every 24 hours by default, so no separate cron job is required.
- **Coverage audit:** with `scheduled --verify-coverage`, merge all successful request intervals within the latest `INITIAL_BACKFILL_DAYS` every 24 hours, log gaps at DEBUG level, and page backward from the right edge of every gap. A network failure does not advance the checkpoint and is retried after 30 minutes.
- **Process lifecycle:** after regular synchronization and any final refresh due in that cycle complete, sleep for `SYNC_INTERVAL` seconds before starting the next cycle. Completing one cycle does not terminate the process.

The current-sync checkpoint is the Unix timestamp captured at the start of the previous successful cycle and stored in `aigupiao_scheduled`. Historical progress, empty-probe count, and completed coverage use separate `crawler_state` rows. Increasing `INITIAL_BACKFILL_DAYS` automatically extends the oldest coverage. Final refreshes use the independent `aigupiao_final_refresh` checkpoint.

When a known, non-finalized news ID is collected again, only `view_num`, `support_num`, `oppose_num`, `comment_num`, `share_num`, and `agq_share_num` are refreshed. Stored article content, metadata, relationships, and raw JSON remain unchanged. Finalized rows are immutable.

The overlap window defaults to five minutes. It protects news published in the same boundary second, records that become visible after a short delay, and feed changes around pagination time. News-ID UPSERTs absorb duplicate reads, trading a small amount of repeated work for a safer synchronization boundary.

Every successfully parsed and committed API request creates a row in `request_coverage` containing a UUID, collector mode, requested `before`, request time, page news IDs, and Unix-time coverage bounds. The upper bound is `before`, or the request time when `before=0`; the lower bound is the oldest page `rec_time`, matching the next historical cursor. Empty pages are audited with equal bounds and do not invent a verified interval. News, checkpoints, and request coverage are committed in one transaction, so a failed database write cannot leave false coverage evidence.

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
# Edit .env and set DATABASE_URL
docker compose up --build -d
docker compose logs -f news-collector
```

The default stack connects to the PostgreSQL service specified by `DATABASE_URL`, initializes its schema, and then starts the scheduled collector. It does not create or manage a PostgreSQL container. It maintains the configured rolling history window (80 days by default), synchronizes hourly with a five-minute protective overlap, and resumes interrupted historical pagination from PostgreSQL state. It also performs an automatic final refresh every 24 hours by default.

Docker fully supports `scheduled`; the `news-collector` service defaults to `scheduled --verify-coverage`, enabling the daily integrity check. Common operations are:

### Run in production

Build and start the services in detached mode for production:

```bash
# Build the image and run initialization and the long-lived scheduled service in the background
docker compose up --build -d

# Check service status and continuously follow scheduled logs
docker compose ps
docker compose logs -f news-collector

# Stop and remove this Compose project's containers and network
docker compose down
```

`-d` means detached mode: the containers continue running after the command returns, and closing the terminal does not stop the collector. While running `docker compose logs -f news-collector`, pressing `Ctrl+C` only exits the log viewer; it does not stop the container. Because `news-collector` uses `restart: unless-stopped`, it recovers after a crash or after Docker starts during a system reboot. Running `docker compose down` explicitly stops and removes the services.

For debugging or reloading configuration, you can also use:

```bash
# Restart from the same database checkpoints after a configuration change or failure
docker compose restart news-collector

# Foreground debugging only; scheduled runs until you press Ctrl+C
docker compose run --rm news-collector scheduled
```

Use `docker compose up --build -d` to manage the long-running deployment. The final `run --rm` command is only for explicit verification or temporary debugging and does not replace the Compose service restart policy.

</details>

## Configuration

Review the settings in `.env` before initializing the database:

| Variable | Scope and exact behavior | Default |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string used by `init-db` and every database-writing command; only `probe` does not require it | None; required |
| `AIGUPIAO_BASE_URL` | Aigupiao API endpoint used by every networked command | Built in |
| `AIGUPIAO_REQUEST_INTERVAL` | Seconds to sleep between adjacent requests during `backfill`, `scheduled` pagination, and `final-refresh`; must be greater than zero | `3` |
| `LIVE_INTERVAL` | Seconds `live` sleeps after each newest-page request; must be greater than zero | `45` |
| `INITIAL_BACKFILL_DAYS` | Required rolling-history window measured in 24-hour days; increasing it automatically extends historical coverage; must be a positive integer | `80` days |
| `SYNC_INTERVAL` | Seconds `scheduled` sleeps after regular synchronization and any due final refresh before starting the next cycle; must be greater than zero | `3600` |
| `SYNC_OVERLAP_SECONDS` | Extra seconds a later `scheduled` cycle reads before the last successful checkpoint; may be `0` | `300` |
| `FINAL_REFRESH_INTERVAL` | Minimum seconds between successful automatic final refreshes in `scheduled`; an independent database checkpoint preserves this across restarts; must be greater than zero | `86400` |
| `COVERAGE_CHECK_INTERVAL` | Minimum seconds between successful integrity checks when `--verify-coverage` is enabled | `86400` |
| `COVERAGE_RETRY_INTERVAL` | Seconds to wait before another integrity check after a network failure or unresolved gap | `1800` |
| `HTTP_TIMEOUT` | Timeout in seconds for one HTTP request; must be greater than zero | `15` |
| `MAX_RETRIES` | Maximum additional attempts after the first request fails with a temporary HTTP or network error; may be `0` | `5` |
| `MAX_BACKOFF` | Maximum seconds allowed for exponential-backoff and `Retry-After` waits; must be greater than zero | `60` |

Copy `.env.example` and adjust it as needed, for example:

```dotenv
DATABASE_URL=postgresql://postgres:change-me@localhost:5432/news

AIGUPIAO_BASE_URL=https://apis.aigupiao.com/Express/express_list/
AIGUPIAO_REQUEST_INTERVAL=3
LIVE_INTERVAL=45
INITIAL_BACKFILL_DAYS=80
SYNC_INTERVAL=3600
SYNC_OVERLAP_SECONDS=300
FINAL_REFRESH_INTERVAL=86400
COVERAGE_CHECK_INTERVAL=86400
COVERAGE_RETRY_INTERVAL=1800
HTTP_TIMEOUT=15
MAX_RETRIES=5
MAX_BACKOFF=60
```

URL-encode passwords containing characters such as `@`, `:`, or `/` inside connection URLs. Replace the example password in production.

Both `uv run` on the host and Compose containers use `DATABASE_URL` unchanged. Set its hostname for the actual deployment and ensure PostgreSQL is reachable from the environment running the command; `localhost` inside a container refers to that container itself.

## Running

Prefer `uv run`. It guarantees that commands execute in the project's locked `.venv` environment without requiring manual activation:

```bash
uv sync --extra dev
uv run news-collector init-db
uv run news-collector scheduled
uv run news-collector scheduled --verify-coverage

# Other commands, used only when needed
uv run news-collector backfill
uv run news-collector backfill --before 1789617870
uv run news-collector live
uv run news-collector final-refresh
uv run news-collector probe --date 2020-01-01
```

If you do not use `uv run`, activate a virtual environment in which this project is installed before invoking `news-collector`. Do not directly use an unverified system `python -m`:

```bash
# Linux / macOS
source .venv/bin/activate
news-collector scheduled

# Windows PowerShell
.venv\Scripts\Activate.ps1
news-collector scheduled
```

| Command or argument | Meaning and behavior |
| --- | --- |
| `init-db` | Idempotently apply the bundled PostgreSQL schema and exit without collecting news |
| `backfill` | Resume from its dedicated per-page checkpoint and continue paginating into history; save each page and its next-page cursor in one transaction, then exit on an empty page |
| `backfill --before UNIX_TIMESTAMP` | Ignore the saved backfill checkpoint and start from the specified Unix-second cursor; `0` starts from the newest page. The override value itself is not written to the database before collection |
| `live` | Always fetch the newest page with `before=0` without paginating; repeat after `LIVE_INTERVAL` and deduplicate with news-ID UPSERTs |
| `scheduled` | Synchronize current news first, resume page-level rolling-history progress, and automatically run `final-refresh` on its independent cadence; runs indefinitely |
| `scheduled --verify-coverage` | Add a daily audit of request coverage over the latest `INITIAL_BACKFILL_DAYS`, automatically repair gaps, and retry failures after 30 minutes by default |
| `final-refresh` | Force one final refresh immediately regardless of whether the automatic refresh is due; update data through the one-calendar-month boundary, freeze due rows, save its independent checkpoint, and exit |
| `probe --date YYYY-MM-DD` | Convert 00:00 on that date in Asia/Shanghai into the `before` cursor, request and parse one page, and print the cursor and item count as JSON without connecting or writing to the database |

### How the commands relate

- `init-db` is a prerequisite for every database-writing mode; `probe` is the only command that does not connect to the database. Docker Compose runs `init-db` automatically first.
- `scheduled` is the recommended long-running everyday mode. It maintains a **resumable rolling-history window**, runs periodic incremental synchronization, and automatically invokes `final-refresh` according to `FINAL_REFRESH_INTERVAL`. You normally do not need a separate long-running `live` process or an external `final-refresh` timer.
- `backfill` is not the same job as the initial backfill inside `scheduled`. It has an independent checkpoint and no day boundary, so it continues through all available history. Run it separately only when you need data older than `INITIAL_BACKFILL_DAYS`.
- `live` polls only the newest page and is useful when you need lower latency than `SYNC_INTERVAL`; `scheduled` already refreshes current data periodically. Running both does not create duplicate rows because of UPSERTs, but it does create duplicate requests and writes.
- Explicit `final-refresh` forces a refresh immediately without checking whether the automatic refresh is due. It is intended for maintenance, diagnostics, or immediately freezing due data.
- `probe` is fully independent: it fetches one page and prints statistics to validate the API and a date cursor.

A typical deployment needs one `init-db` run followed by one long-running `scheduled` process. Avoid multiple concurrent `scheduled` processes, and do not unnecessarily run `backfill` or a manual `final-refresh` in parallel with an active `scheduled` cycle, because doing so wastes API and database resources. Use `uv run news-collector COMMAND --help` for subcommand help.

Run these commands in one-shot Docker containers:

```bash
docker compose run --rm news-collector backfill
docker compose run --rm news-collector backfill --before 1789617870
docker compose run --rm news-collector final-refresh
docker compose run --rm news-collector probe --date 2020-01-01
```

`scheduled` is a long-running task. In Docker, the recommended startup method is `docker compose up --build -d` as described above, so it should not normally be treated as a one-shot command.

## Verification

```bash
uv run ruff check news_collector tests
uv run pytest
```

Tests use mocks and local JSON fixtures; they never contact the production API.

## Stopping Docker services

```bash
docker compose down
```

Compose does not manage PostgreSQL, so this command only stops the collector containers and does not delete database data.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
