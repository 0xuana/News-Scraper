# 爱股票新闻采集器

[简体中文](README.md) | [English](README.en.md)

一个面向长期运行的 Python 新闻采集服务。它从爱股票快讯接口分页获取新闻，解析正文、标题、股票、题材和话题关系，并通过 PostgreSQL UPSERT 幂等保存。默认 Docker 工作流持续维护最近 80 天的滚动覆盖，并每小时执行一次带时间重叠的增量同步。历史分页进度持久化在 PostgreSQL 中，因此首次回填中断后会从最后成功提交的页面继续。

当你希望长期积累历史新闻数据，并将其作为 RAG 知识库来增强 Agent 的历史检索、上下文补充、事件追踪和分析能力时，就会需要这个项目。它负责持续沉淀结构化、可去重且可恢复采集的新闻数据，为后续的分块、向量化和检索流程提供稳定数据源；项目本身不包含向量数据库或 RAG 查询服务。

## 主要功能

- 按 `rec_time` 游标回溯历史新闻，支持检查点恢复。
- 持续轮询最新新闻，通过新闻 ID 实现幂等入库。
- 从 `web_content` 读取正文，并从开头的 `【…】` 中提取标题。
- 保留去除空值后的原始 JSON，包括原始内容字段。
- 处理超时、限流、服务端错误和 JSON 解析错误。
- 维护可配置的滚动历史窗口，并在同一事务中提交每页数据及其游标。
- 重启后先追平当前新闻，再恢复未完成的历史分页。
- 支持 Docker Compose 通过 `DATABASE_URL` 连接 PostgreSQL、初始化数据库并运行计划采集。

## 计划同步语义

`scheduled` 是 Docker 的默认运行模式：

- **每次运行**：先同步到 `上次成功检查点 - SYNC_OVERLAP_SECONDS` 以追平当前新闻，再从历史游标继续，直到覆盖滚动边界 `当前时间 - INITIAL_BACKFILL_DAYS`。
- **历史进度**：每页新闻和该页最旧游标在同一事务中保存。重启后从该游标继续，不再重放整个历史窗口。旧版本升级后因没有新标记，会重新建立一次滚动覆盖。
- **历史空页**：一个空页不会立即被当成完成。采集器最多继续探测十次，每次向过去移动十分钟；空页计数和探测游标也能跨重启恢复。
- **成功条件**：当前同步的全部目标页面成功后才推进当前检查点；到达历史边界或连续十次探测为空后，另行保存历史覆盖边界。
- **异常条件**：HTTP 重试耗尽、解析失败、数据库写入失败或分页游标不再向过去移动时，进程退出且不推进检查点；Docker 会按重启策略重新运行。
- **最终刷新**：常规同步成功后，如果从未成功执行最终刷新，或其独立检查点已过去 `FINAL_REFRESH_INTERVAL` 秒，便自动从最新页刷新到一个自然月前的边界，再冻结所有到期记录。默认每 24 小时执行一次，无需另配 cron。
- **进程生命周期**：常规同步和本轮到期的最终刷新均结束后，休眠 `SYNC_INTERVAL` 秒再执行下一轮；整个进程不会因为完成一次同步而退出。

当前同步检查点是上一轮成功同步开始时的 Unix 秒时间，存储在 `aigupiao_scheduled`。历史进度、空页探测次数和已完成覆盖边界使用独立的 `crawler_state` 记录。增大 `INITIAL_BACKFILL_DAYS` 会自动向更早历史扩展。最终刷新继续使用独立的 `aigupiao_final_refresh` 检查点。

再次采集到已存在且尚未冻结的新闻 ID 时，只刷新 `view_num`、`support_num`、`oppose_num`、`comment_num`、`share_num` 和 `agq_share_num`。已保存的正文、元数据、关联关系和原始 JSON 保持不变；已冻结记录完全不可变。

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
uv run ruff check news_collector tests
```

只请求一页真实 API 数据且不写入数据库：

```bash
uv run python -m news_collector probe --date 2026-09-17
```

如果要测试完整入库流程，先复制并配置 `.env`，确保 PostgreSQL 已启动：

```bash
cp .env.example .env
uv run python -m news_collector init-db
uv run python -m news_collector backfill
```

按 `Ctrl+C` 即可停止回溯。再次执行同一命令时，程序会从数据库检查点继续。启动实时采集可执行：

```bash
uv run python -m news_collector live
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
python -m news_collector init-db
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
# 编辑 .env，设置 DATABASE_URL
docker compose up --build -d
docker compose logs -f news-collector
```

默认编排会连接 `DATABASE_URL` 指定的 PostgreSQL，初始化表结构，然后启动计划采集器；它不会创建或管理 PostgreSQL 容器。采集器维护可配置的滚动历史窗口（默认 80 天），每小时进行一次带 5 分钟保护重叠的同步，并从 PostgreSQL 状态恢复中断的历史分页。它还会默认每 24 小时自动执行最终刷新。

Docker 环境完整支持 `scheduled`，而且 `compose.yaml` 中 `news-collector` 服务的默认命令就是 `scheduled`。常用操作如下：

### 生产环境后台运行

在生产环境中使用 detached 模式启动并构建服务：

```bash
# 构建镜像，在后台运行初始化任务和长期 scheduled 服务
docker compose up --build -d

# 确认服务状态并持续查看 scheduled 日志
docker compose ps
docker compose logs -f news-collector

# 停止并移除当前 Compose 项目的容器和网络
docker compose down
```

`-d` 表示 detached（后台）模式：命令返回后容器仍会继续运行，关闭终端不会停止采集器。执行 `docker compose logs -f news-collector` 时按 `Ctrl+C` 只会退出日志查看，不会停止容器。`news-collector` 配置了 `restart: unless-stopped`，因此异常退出或 Docker 服务随系统重启后会自动恢复；执行 `docker compose down` 则会明确停止并移除服务。

调试或重新加载配置时还可以使用：

```bash
# 配置修改或异常退出后，使用同一数据库检查点重新启动
docker compose restart news-collector

# 仅用于前台调试；scheduled 会一直运行，按 Ctrl+C 停止
docker compose run --rm news-collector scheduled
```

部署时应使用 `docker compose up --build -d` 管理长期服务；最后一条 `run --rm` 命令只是显式验证或临时调试 `scheduled`，不会替代 Compose 服务的重启策略。

</details>

## 配置

初始化数据库前，请检查 `.env` 中的配置：

| 变量 | 适用范围及具体行为 | 默认值 |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL 连接字符串；供 `init-db` 及所有写库采集命令使用，只有 `probe` 不需要 | 无，必填 |
| `AIGUPIAO_BASE_URL` | 所有联网命令请求的爱股票 API 端点 | 项目内置地址 |
| `AIGUPIAO_REQUEST_INTERVAL` | `backfill`、`scheduled` 分页及 `final-refresh` 相邻请求之间的休眠秒数；必须大于 0 | `3` |
| `LIVE_INTERVAL` | `live` 每次请求最新页后的休眠秒数；必须大于 0 | `45` |
| `INITIAL_BACKFILL_DAYS` | 以 24 小时天数计算的滚动历史窗口；增大该值会自动向更早历史扩展；必须为正整数 | `80` 天 |
| `SYNC_INTERVAL` | `scheduled` 完成常规同步及到期最终刷新后，到下一轮开始前的休眠秒数；必须大于 0 | `3600` |
| `SYNC_OVERLAP_SECONDS` | `scheduled` 后续轮次在上次成功检查点之前额外回溯的秒数；可为 `0` | `300` |
| `FINAL_REFRESH_INTERVAL` | `scheduled` 两次成功自动最终刷新之间至少间隔的秒数；重启后仍由独立数据库检查点判断；必须大于 0 | `86400` |
| `HTTP_TIMEOUT` | 单次 HTTP 请求超时秒数；必须大于 0 | `15` |
| `MAX_RETRIES` | 首次请求失败后，对临时 HTTP/网络错误追加重试的最多次数；可为 `0` | `5` |
| `MAX_BACKOFF` | 指数退避及 `Retry-After` 等待的秒数上限；必须大于 0 | `60` |

可复制 `.env.example` 后按需修改，例如：

```dotenv
DATABASE_URL=postgresql://postgres:change-me@localhost:5432/news

AIGUPIAO_BASE_URL=https://apis.aigupiao.com/Express/express_list/
AIGUPIAO_REQUEST_INTERVAL=3
LIVE_INTERVAL=45
INITIAL_BACKFILL_DAYS=80
SYNC_INTERVAL=3600
SYNC_OVERLAP_SECONDS=300
FINAL_REFRESH_INTERVAL=86400
HTTP_TIMEOUT=15
MAX_RETRIES=5
MAX_BACKOFF=60
```

如果密码包含 `@`、`:`、`/` 等字符，连接 URL 中的密码需要进行 URL 编码。生产环境请替换示例密码。

主机上的 `uv run` 和 Compose 容器都原样使用 `DATABASE_URL`。请根据实际部署填写主机名，并确保 PostgreSQL 可从运行命令的环境访问；容器中的 `localhost` 指向容器本身。

## 运行

推荐使用 `uv run`，它会确保命令在项目锁定的 `.venv` 环境中执行，无需手动激活虚拟环境：

```bash
uv sync --extra dev
uv run news-collector init-db
uv run news-collector scheduled

# 其他按需命令
uv run news-collector backfill
uv run news-collector backfill --before 1789617870
uv run news-collector live
uv run news-collector final-refresh
uv run news-collector probe --date 2020-01-01
```

如果不用 `uv run`，必须先激活已安装本项目的虚拟环境，再调用 `news-collector`。不要直接使用未确认来源的系统 `python -m`：

```bash
# Linux / macOS
source .venv/bin/activate
news-collector scheduled

# Windows PowerShell
.venv\Scripts\Activate.ps1
news-collector scheduled
```

| 命令或参数 | 含义和行为 |
| --- | --- |
| `init-db` | 幂等应用内置 PostgreSQL schema 后退出，不采集新闻 |
| `backfill` | 从专用逐页检查点恢复并一直向历史翻页；每一页新闻和下一页游标在同一事务中保存，空页时退出 |
| `backfill --before UNIX_TIMESTAMP` | 忽略已存 backfill 检查点，从指定 Unix 秒游标开始；传 `0` 表示从最新页开始。该覆盖值本身不会先写入数据库 |
| `live` | 始终以 `before=0` 获取最新一页，不向历史翻页；每次等待 `LIVE_INTERVAL` 后重复，依靠新闻 ID UPSERT 去重 |
| `scheduled` | 先同步当前新闻，再恢复逐页滚动历史进度，并按独立周期自动执行 `final-refresh`；长期运行不主动退出 |
| `final-refresh` | 立即强制执行一次最终刷新，不理会自动刷新是否到期；更新一个自然月边界内的数据，冻结到期记录并保存独立检查点后退出 |
| `probe --date YYYY-MM-DD` | 将上海时区该日 `00:00` 转成 `before` 游标，只请求并解析一页，以 JSON 输出游标和条数；不连接或写入数据库 |

### 命令之间的关系

- `init-db` 是所有写库模式的前置步骤；`probe` 是唯一不连接数据库的命令。Docker Compose 会自动先执行 `init-db`。
- `scheduled` 是推荐的日常长期模式。它维护**可恢复的滚动历史窗口**，完成周期增量同步，并按 `FINAL_REFRESH_INTERVAL` 自动调用 `final-refresh`，因此一般不需要再单独长期运行 `live` 或另配 `final-refresh` 定时任务。
- `backfill` 与 `scheduled` 的首次回填不是同一个任务。`backfill` 使用独立检查点、没有天数边界，会持续向全部可用历史翻页；只有确实需要超过 `INITIAL_BACKFILL_DAYS` 的更老数据时才单独运行。
- `live` 只轮询最新一页，适合需要比 `SYNC_INTERVAL` 更低延迟的场景；`scheduled` 已经周期性覆盖最新数据。两者同时运行不会因 UPSERT 产生重复行，但会增加重复请求和写入。
- 手动 `final-refresh` 会立即强制刷新，不检查自动刷新是否到期；它主要用于维护、排障或希望马上冻结到期数据的场景。
- `probe` 完全独立，只请求一页并打印统计，可用于验证 API 和日期游标。

典型部署只需要：`init-db` 一次，然后长期运行一个 `scheduled`。避免同时启动多个 `scheduled`，也不要在一个 `scheduled` 正在执行时无必要地并行启动 `backfill` 或手动 `final-refresh`，以免重复消耗 API 和数据库资源。可用 `uv run news-collector COMMAND --help` 查看子命令帮助。

Docker 环境下可以使用一次性容器运行这些命令：

```bash
docker compose run --rm news-collector backfill
docker compose run --rm news-collector backfill --before 1789617870
docker compose run --rm news-collector final-refresh
docker compose run --rm news-collector probe --date 2020-01-01
```

`scheduled` 是长期任务，Docker 下的推荐启动方式是前文的 `docker compose up --build -d`，因此不把它归入上述一次性命令。

## 验证

```bash
uv run ruff check news_collector tests
uv run pytest
```

测试使用 mock 和本地 JSON 样本，不会请求生产 API。

## 停止 Docker 服务

```bash
docker compose down
```

Compose 不管理 PostgreSQL，因此上述命令只停止采集器容器，不会删除数据库数据。

## 开源许可证

本项目使用 [Apache License 2.0](LICENSE)。
