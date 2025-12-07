# DailyNews

DailyNews 是一个以配置驱动的新闻摘要管道：用 NewsAPI 拉取全球头条与主题文章，靠 OpenAI/DeepSeek 撰写中英双语简报，再通过 SMTP 邮件发送给订阅者。项目着重支持可自定义的 digest、按人分发的路由以及图文并茂的邮件。

## 亮点
- 列表化 `config/digest.json` 与 `config/subscribers.json`，可独立定义多个 digest 与订阅者，支持语言/时区/投递频率等字段。
- 同时支持 `top-headlines` 与 `everything` 查询，按 `last_run` 跳过重复内容并根据 `newsapi.max_age_days` 限定抓取窗口。
- 调用 DeepSeek（`DEEPSEEK_API_KEY`）或 OpenAI `responses`（`OPENAI_API_KEY`）生成结构化摘要，输出中包含标题、中文摘要、英文摘要、专业术语解释与要点。
- 生成的 Markdown 除了保存在 `digests/`，还会借助 `markdown` + `BeautifulSoup` 转成 HTML，并尝试用 Playwright 截图每条 story 生成图文卡片，发送到邮件里。
- 可通过 `scripts/run_daily_headlines.sh`、`scripts/run_topics.sh` 等脚本搭配 cron 执行，日志写入 `logs/news_digest.log`，状态写入 `config/run_state.json` 以驱动增量抓取。

## 快速开始
1. 克隆仓库并安装依赖（推荐使用 `uv`，也可用 `pip` 安装 `pyproject.toml` 所列的依赖）：

   ```bash
   git clone https://github.com/ymphys/dailynews.git
   cd dailynews
   uv sync
   python -m playwright install chromium
   ```

2. 根据实际环境创建 `.env` 或其他方式导入以下必需的环境变量：

   ```bash
   NEWSAPI_ORG_KEY=your_newsapi_token
   DEEPSEEK_API_KEY=your_deepseek_token          # 或者 OPENAI_API_KEY=your_openai_token
   DAILYNEWS_EMAIL_FROM=sender@example.com
   DAILYNEWS_EMAIL_APP_PW=smtp_authorization_token
   DAILYNEWS_EMAIL_TO=fallback@example.com
   ```

3. 可选地设置：

   ```bash
   DAILYNEWS_EMAIL_DRY_RUN=1   # 只生成摘要但不发送邮件，用于本地测试
   ```

## 环境变量与 SMTP
| 变量 | 说明 |
| --- | --- |
| `NEWSAPI_ORG_KEY` | 必需，NewsAPI 的密钥。 |
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` | 至少一项配置，用于生成双语摘要；DeepSeek 优先。 |
| `DAILYNEWS_EMAIL_FROM` | 发送邮箱地址（默认 `smtp.qq.com:587`，可在 `mailer.py` 调整）。 |
| `DAILYNEWS_EMAIL_APP_PW` | 邮箱的客户端授权码。 |
| `DAILYNEWS_EMAIL_TO` | 当 digest 没有订阅者时的兜底收件人地址，支持用 `,` 分隔多个地址。 |
| `DAILYNEWS_EMAIL_DRY_RUN` | 设为任意值可跳过 SMTP 发送，用于调试。 |

## 配置概览

### `config/digest.json`
每条 digest 记录包括 `id`、`mode`（`headlines` 或 `topic`）、`news_queries`、邮件模板与输出配置。常用字段：

| 字段 | 说明 |
| --- | --- |
| `news_queries` | 一组 NewsAPI payload（可选 `endpoint`、`language`、`country` 等）。 |
| `email.subject_template` | 用 `str.format(local_dt=...)` 的方式渲染邮件主题。 |
| `newsapi.max_age_days` | 控制 `everything` 查询最大回溯天数（默认 2）。 |
| `output.filename_prefix` | 写入 `digests/` 的 Markdown 前缀。 |
| `schedule` | 描述默认投递时间/时区，仅做文档说明。 |

### `config/subscribers.json`
包含默认设置与订阅用户列表，字段如 `id`、`email`、`digests`、`languages`、`send_time`。默认值会合并到每条记录中。详见 `docs/subscriber-requirements.md` 来了解可设置的元数据。

### 运行状态
`config/run_state.json` 自动记录每个 digest 的 `last_run`，用于 `collect_articles` 在下一次运行时跳过旧文章。legacy 文件 `run_state_headlines.json` 和 `run_state_topics.json` 会在首次执行时自动迁移。

## 执行入口

- 全量执行：`uv run main.py`
- 仅运行头条：`uv run main.py headlines`
- 仅运行主题：`uv run main.py topics`

每次运行会生成 Markdown 文件：按 `config` 中的 `filename_prefix` + 时间戳命名，保存在 `digests/`。生成后会调用 `mailer.send_digest_via_email`，根据 `config/subscribers.json` 匹配收件人；如无匹配则回退到 `DAILYNEWS_EMAIL_TO`。

## 邮件投递流程
- Markdown → HTML：用 `markdown` 库转换，并通过 `BeautifulSoup` 分段。
- 图文卡片：若安装了 Playwright，会将每条故事截图为 `digests/<slug>/story-##.png`，并把图片嵌入邮件 `<img>`。
- SMTP：默认用 `smtp.qq.com:587`（可在 `mailer.py` 调整），每个收件人都能设置 `name` 显示名，失败会记录日志。可设置 `DAILYNEWS_EMAIL_DRY_RUN` 绕过发送。
- 日志：`logs/news_digest.log` 记录 run 信息、NewsAPI 请求、OpenAI/DeepSeek token usage 与收件人列表。

## 自定义 Digest
1. 在 `config/digest.json` 复制一条 digest，修改 `id`、`display_name`、`email.subject_template`、`news_queries` 等字段。
2. 在 `config/subscribers.json` 的某个订阅者里把 `digests` 列表加入新 `id`；可以同时指定 `languages`、`frequency`、`send_time`。
3. 运行 `uv run main.py topics`（或 `headlines`）确认 Markdown 生成。
4. 关闭 `DAILYNEWS_EMAIL_DRY_RUN` 就能发真正的邮件。

## 维护脚本
- `scripts/run_daily_headlines.sh`、`scripts/run_topics.sh`：加载私有环境变量（例如 `.dailynews_env`），再用 `uv run main.py headlines/topics` 写入 `logs/cron.log`，适合 crontab。
- `scripts/run_dailynews_template.sh`：可用于自定义的调度模板（内容同 `main.py`）。

## 资源
- 配置校验 / 加载：`config_loader.py`
- 摘要与 Digest 生成逻辑：`digest_utils.py`
- 订阅者要求：`docs/subscriber-requirements.md`

## 许可
MIT 许可。查看 [LICENSE](LICENSE) 获取详情。
