# 爱股票新闻采集器

[简体中文](README.md) | [English](README.en.md)

一个模块化的 Python 新闻采集服务，用于持续采集爱股票新闻，并将去重后的新闻及其股票、题材和话题关系存储到 PostgreSQL。

## 主要功能

- 按 `rec_time` 游标回溯历史新闻，支持检查点恢复。
- 持续轮询最新新闻，通过新闻 ID 实现幂等入库。
- 从 `web_content` 读取正文，并从开头的 `【…】` 中提取标题。
- 保留去除空值后的原始 JSON，包括原始内容字段。
- 处理超时、限流、服务端错误和 JSON 解析错误。
- 支持 Docker Compose 一键启动 PostgreSQL、初始化数据库并运行实时采集。

## 环境要求

- Python 3.11 或更高版本
- PostgreSQL
- 可选：Docker 和 Docker Compose

## 安装方案

### 方案一：使用 uv（推荐用于本地测试）

项目已提供 `uv.lock`，`uv` 会自动创建 `.venv` 并安装锁定版本的依赖。如果还没有安装 `uv`，Linux 和 macOS 可使用：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows PowerShell：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装项目和开发测试依赖：

```bash
uv sync --extra dev
```

运行不访问生产 API、也不需要 PostgreSQL 的本地测试：

```bash
uv run pytest
uv run ruff check collector tests
```

只请求一页真实 API 数据且不写入数据库：

```bash
uv run python -m collector probe --date 2026-09-17
```

如果要测试完整入库流程，先复制并配置 `.env`，确保 PostgreSQL 已启动：

```bash
cp .env.example .env
uv run python -m collector init-db
uv run python -m collector backfill
```

按 `Ctrl+C` 即可停止回溯。再次执行同一命令时，程序会从数据库检查点继续。启动实时采集可执行：

```bash
uv run python -m collector live
```

详细安装方式可查看 [uv 官方安装文档](https://docs.astral.sh/uv/getting-started/installation/)。

### 方案二：使用 requirements.txt

适合直接运行采集器：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python -m collector init-db
```

Windows PowerShell 的虚拟环境激活命令：

```powershell
.venv\Scripts\Activate.ps1
```

### 方案三：pip 开发环境

`requirements-dev.txt` 在运行依赖之外包含 pytest 和 Ruff：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e .
cp .env.example .env
```

也可以直接通过项目元数据安装开发依赖：

```bash
python -m pip install -e '.[dev]'
```

`requirements.txt` 和 `requirements-dev.txt` 与 `pyproject.toml` 中的依赖范围保持一致。修改项目依赖时，请同步更新这些文件。

### 方案四：Docker Compose

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f collector
```

默认编排会启动 PostgreSQL，等待健康检查通过，初始化表结构，然后启动计划采集器。首次运行会分页回填最近 60 天；完成后每小时分页同步上次成功时间以来的新闻，并额外重叠 5 分钟以保护时间边界。同步检查点保存在 PostgreSQL 中，容器重启后不会重复执行完整的 60 天回填。数据保存在 `postgres-data` 命名卷中。

## 配置

初始化数据库前，请检查 `.env` 中的配置：

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL 连接字符串 | 无，非 `probe` 命令必填 |
| `AIGUPIAO_BASE_URL` | 爱股票 API 地址 | 项目内置地址 |
| `AIGUPIAO_REQUEST_INTERVAL` | 回溯和最终刷新的请求间隔 | `3` 秒 |
| `LIVE_INTERVAL` | 实时采集轮询间隔 | `45` 秒 |
| `INITIAL_BACKFILL_DAYS` | 计划模式首次回填天数 | `60` 天 |
| `SYNC_INTERVAL` | 计划模式同步间隔 | `3600` 秒 |
| `SYNC_OVERLAP_SECONDS` | 每轮同步向前重叠的保护窗口 | `300` 秒 |
| `HTTP_TIMEOUT` | HTTP 请求超时 | `15` 秒 |
| `MAX_RETRIES` | 临时错误最大重试次数 | `5` |
| `MAX_BACKOFF` | 指数退避最大等待时间 | `60` 秒 |

Docker Compose 会在容器内使用 `db` 作为数据库主机名，并覆盖主机环境中的 `DATABASE_URL`。

## 运行

```bash
python -m collector backfill
python -m collector backfill --before 1789617870
python -m collector live
python -m collector scheduled
python -m collector final-refresh
python -m collector probe --date 2020-01-01
```

`backfill` 会从 `crawler_state` 恢复进度，每批新闻和检查点在同一事务中写入。`live` 始终请求最新页，并依靠新闻表主键去重。`scheduled` 首次回填配置的历史窗口，之后按同步间隔分页覆盖上次成功时间以来的数据；只有整轮成功后才推进检查点。

建议每日运行一次 `final-refresh`，例如通过 cron 或 systemd timer。

Docker 环境下可以使用一次性容器运行这些命令：

```bash
docker compose run --rm collector backfill
docker compose run --rm collector backfill --before 1789617870
docker compose run --rm collector final-refresh
docker compose run --rm collector probe --date 2020-01-01
```

## 验证

```bash
ruff check collector tests
pytest
```

测试使用 mock 和本地 JSON 样本，不会请求生产 API。

## 停止 Docker 服务

```bash
docker compose down
```

上述命令会保留数据库卷。只有确定需要删除 PostgreSQL 数据时，才使用 `docker compose down --volumes`。

## 开源许可证

本项目使用 [Apache License 2.0](LICENSE)。
