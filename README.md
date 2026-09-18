# 爱股票新闻采集器

[简体中文](README.md) | [English](README.en.md)

一个面向长期运行的 Python 新闻采集服务。它从爱股票快讯接口分页获取新闻，解析正文、标题、股票、题材和话题关系，并通过 PostgreSQL UPSERT 幂等保存。默认 Docker 工作流首次回填最近 60 天，之后每小时执行一次带时间重叠的增量同步；同步检查点持久化在数据库中，因此网络失败或容器重启不会让已完成的历史回填从头开始。

当你希望长期积累历史新闻数据，并将其作为 RAG 知识库来增强 Agent 的历史检索、上下文补充、事件追踪和分析能力时，就会需要这个项目。它负责持续沉淀结构化、可去重且可恢复采集的新闻数据，为后续的分块、向量化和检索流程提供稳定数据源；项目本身不包含向量数据库或 RAG 查询服务。

## 主要功能

- 按 `rec_time` 游标回溯历史新闻，支持检查点恢复。
- 持续轮询最新新闻，通过新闻 ID 实现幂等入库。
- 从 `web_content` 读取正文，并从开头的 `【…】` 中提取标题。
- 保留去除空值后的原始 JSON，包括原始内容字段。
- 处理超时、限流、服务端错误和 JSON 解析错误。
- 支持有边界的首次历史回填，以及不会因单页 20 条限制而漏数的分页增量同步。
- 只有整轮同步成功后才推进检查点；失败轮次会在重启后安全重试。
- 支持 Docker Compose 一键启动 PostgreSQL、初始化数据库并运行计划采集。

## 计划同步语义

`scheduled` 是 Docker 的默认运行模式：

- **首次运行**：从最新页向历史翻页。当页面最旧新闻时间到达 `当前时间 - INITIAL_BACKFILL_DAYS`，或者 API 返回空页时，本轮结束。跨越边界的页面只保存边界以内的数据。
- **后续运行**：从最新页向历史翻页。当页面最旧新闻时间到达 `上次成功检查点 - SYNC_OVERLAP_SECONDS`，或者 API 返回空页时，本轮结束。
- **成功条件**：只有全部目标页面解析并写入成功后，才把本轮开始时间保存为新检查点。
- **异常条件**：HTTP 重试耗尽、解析失败、数据库写入失败或分页游标不再向过去移动时，进程退出且不推进检查点；Docker 会按重启策略重新运行。
- **最终刷新**：常规同步成功后，如果从未成功执行最终刷新，或其独立检查点已过去 `FINAL_REFRESH_INTERVAL` 秒，便自动从最新页刷新到一个自然月前的边界，再冻结所有到期记录。默认每 24 小时执行一次，无需另配 cron。
- **进程生命周期**：常规同步和本轮到期的最终刷新均结束后，休眠 `SYNC_INTERVAL` 秒再执行下一轮；整个进程不会因为完成一次同步而退出。

这里的“上次成功检查点”是上一轮**开始时**由系统时钟取得的 Unix 秒时间，存储在 `crawler_state` 的 `aigupiao_scheduled` 记录中；它不是上一页游标、最后写入新闻的时间，也不是该轮结束时间。使用开始时间可以覆盖上一轮执行期间新发布的新闻，再减去重叠窗口以保护分页边界。最终刷新使用独立的 `aigupiao_final_refresh` 检查点，表示上一次“刷新到一个月边界并冻结到期记录”全部成功时对应的启动时间。任何中途失败都不会更新相应检查点。

时间重叠窗口默认是 5 分钟。它可以覆盖同一秒发布的边界新闻、接口短暂延迟可见的数据，以及同步时刻附近的分页变化。重叠数据通过新闻 ID 的 UPSERT 去重，因此用少量重复读取换取更可靠的边界完整性。

## 环境要求

- Python 3.11 或更高版本
- PostgreSQL
- 可选：Docker 和 Docker Compose

## 安装方案

<details open>
<summary><strong>方案一：使用 uv（推荐用于本地测试）</strong></summary>


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

</details>

<details>
<summary><strong>方案二：使用 requirements.txt</strong></summary>


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

</details>

<details>
<summary><strong>方案三：pip 开发环境</strong></summary>


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

</details>

<details>
<summary><strong>方案四：Docker Compose（推荐用于部署）</strong></summary>


```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f news-collector
```

默认编排会启动 PostgreSQL，等待健康检查通过，初始化表结构，然后启动计划采集器。首次运行会分页回填最近 60 天；完成后每小时分页同步上次成功时间以来的新闻，并额外重叠 5 分钟以保护时间边界。它还会默认每 24 小时自动执行最终刷新。两类检查点均保存在 PostgreSQL 中，容器重启后不会重复执行完整的 60 天回填或尚未到期的最终刷新。数据保存在 `postgres-data` 命名卷中。

</details>

## 配置

初始化数据库前，请检查 `.env` 中的配置：

| 变量 | 适用范围及具体行为 | 默认值 |
| --- | --- | --- |
| `DATABASE_URL` | `init-db` 及所有写库采集命令使用的 PostgreSQL 连接字符串；只有 `probe` 不需要 | 无，必填 |
| `AIGUPIAO_BASE_URL` | 所有联网命令请求的爱股票 API 端点 | 项目内置地址 |
| `AIGUPIAO_REQUEST_INTERVAL` | `backfill`、`scheduled` 分页及 `final-refresh` 相邻请求之间的休眠秒数；必须大于 0 | `3` |
| `LIVE_INTERVAL` | `live` 每次请求最新页后的休眠秒数；必须大于 0 | `45` |
| `INITIAL_BACKFILL_DAYS` | `scheduled` 没有同步检查点时，从本轮开始时间向前保存的自然秒数窗口；必须为正整数 | `60` 天 |
| `SYNC_INTERVAL` | `scheduled` 完成常规同步及到期最终刷新后，到下一轮开始前的休眠秒数；必须大于 0 | `3600` |
| `SYNC_OVERLAP_SECONDS` | `scheduled` 后续轮次在上次成功检查点之前额外回溯的秒数；可为 `0` | `300` |
| `FINAL_REFRESH_INTERVAL` | `scheduled` 两次成功自动最终刷新之间至少间隔的秒数；重启后仍由独立数据库检查点判断；必须大于 0 | `86400` |
| `HTTP_TIMEOUT` | 单次 HTTP 请求超时秒数；必须大于 0 | `15` |
| `MAX_RETRIES` | 首次请求失败后，对临时 HTTP/网络错误追加重试的最多次数；可为 `0` | `5` |
| `MAX_BACKOFF` | 指数退避及 `Retry-After` 等待的秒数上限；必须大于 0 | `60` |

可复制 `.env.example` 后按需修改，例如：

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

如果密码包含 `@`、`:`、`/` 等字符，`DATABASE_URL` 中的密码需要进行 URL 编码。生产环境请替换示例密码。

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

| 命令或参数 | 含义和行为 |
| --- | --- |
| `init-db` | 幂等应用内置 PostgreSQL schema 后退出，不采集新闻 |
| `backfill` | 从专用逐页检查点恢复并一直向历史翻页；每一页新闻和下一页游标在同一事务中保存，空页时退出 |
| `backfill --before UNIX_TIMESTAMP` | 忽略已存 backfill 检查点，从指定 Unix 秒游标开始；传 `0` 表示从最新页开始。该覆盖值本身不会先写入数据库 |
| `live` | 始终以 `before=0` 获取最新一页，不向历史翻页；每次等待 `LIVE_INTERVAL` 后重复，依靠新闻 ID UPSERT 去重 |
| `scheduled` | 首次回填有界窗口，之后从上次成功轮次开始时间减去重叠量进行同步，并按独立周期自动执行 `final-refresh`；长期运行不主动退出 |
| `final-refresh` | 立即强制执行一次最终刷新，不理会自动刷新是否到期；更新一个自然月边界内的数据，冻结到期记录并保存独立检查点后退出 |
| `probe --date YYYY-MM-DD` | 将上海时区该日 `00:00` 转成 `before` 游标，只请求并解析一页，以 JSON 输出游标和条数；不连接或写入数据库 |

各子命令也可用 `python -m collector COMMAND --help` 查看上述行为和参数。通常只需长期运行 `scheduled`；手动 `final-refresh` 保留给立即刷新、排障或维护场景。

Docker 环境下可以使用一次性容器运行这些命令：

```bash
docker compose run --rm news-collector backfill
docker compose run --rm news-collector backfill --before 1789617870
docker compose run --rm news-collector final-refresh
docker compose run --rm news-collector probe --date 2020-01-01
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
