# Repository Guidelines

## Project Structure & Module Organization

This repository is in its bootstrap phase; `REQUIREMENTS.md` defines the intended implementation. Keep application code under `collector/`, with the CLI entry point in `collector/__main__.py`. Separate responsibilities into `collector/aigupiao/` (HTTP client and response parsing), `collector/collectors/` (backfill and live loops), `collector/db/` (models and persistence), and `collector/utils/` (retry and logging helpers). Place tests in `tests/`, mirroring module names such as `tests/test_parser.py`. Keep generated artifacts and secrets out of source control.

## Build, Test, and Development Commands

No packaging configuration is committed yet. When bootstrapping it, provide a reproducible virtual-environment workflow and keep these required interfaces stable:

- `python -m collector backfill` — resume historical collection from the stored checkpoint.
- `python -m collector live` — poll the newest feed continuously.
- `python -m collector probe --date 2020-01-01` — inspect API history near a date.
- `pytest` — run the full unit-test suite; production HTTP calls must be mocked.

Document any added setup, lint, migration, or test commands in the README and packaging metadata.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation and type hints on public interfaces. Use `snake_case` for modules, functions, variables, and database columns; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants. Keep HTTP, parsing, persistence, and orchestration logic in separate modules. Prefer small functions with explicit inputs over hidden global state. If Ruff or another formatter is introduced, commit its configuration and run it before opening a pull request.

## Testing Guidelines

Use pytest and name files `test_<module>.py` and tests `test_<behavior>()`. Cover grouped-response flattening, duplicates, cursor progress, empty pages, retries, malformed JSON, transactional rollback, and checkpoint restart. Database tests must verify that failed writes never advance the checkpoint.

## Commit & Pull Request Guidelines

The repository has no commit history yet. Use focused Conventional Commit-style messages, for example `feat(parser): flatten dated news groups` or `test(db): preserve checkpoint on rollback`. Keep each commit independently valid. Pull requests should describe behavior changes, link the relevant issue, list verification commands, and call out schema or configuration changes; screenshots are needed only for user-visible output.

## Security & Configuration

Read credentials and tuning values from environment variables such as `DATABASE_URL`, `HTTP_TIMEOUT`, and `MAX_RETRIES`. Never commit `.env` files, user IP data, or live API responses containing personal information. Respect `Retry-After` and do not add proxy rotation or anti-bot bypasses.
