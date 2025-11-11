# DailyNews

DailyNews generates Markdown news digests by querying NewsAPI, summarising the results with OpenAI, and delivering the output by email.  
The project now supports configurable digests and per-subscriber routing so each recipient can receive the topics they care about.

## Features
- Global headline and topic-specific digests driven by `config/digest.json`
- Bilingual (ZH/EN) query definitions seeded for AI, China Economy, Science & Tech, and Gold/FX
- Markdown output with HTML conversion for email delivery
- SMTP delivery through QQ (or any host configured via environment variables)
- Dry-run mode for safe testing without sending mail

## Quick Start

```bash
git clone https://github.com/ymphys/dailynews.git
cd dailynews
uv sync
```

Create a `.env` file (or export variables) with the required keys:

```bash
NEWSAPI_ORG_KEY=your_newsapi_token
OPENAI_API_KEY=your_openai_token
DAILYNEWS_EMAIL_FROM=sender@example.com
DAILYNEWS_EMAIL_APP_PW=app_password_or_token
DAILYNEWS_EMAIL_TO=fallback@example.com   # used when a digest has no subscribers
```

Optional for testing (skip SMTP send but still generate output/logs):

```bash
DAILYNEWS_EMAIL_DRY_RUN=1
```

## Configuration Overview

### `config/digest.json`
Each entry describes a digest that can be executed by the CLI.

| Field | Purpose |
| ----- | ------- |
| `id` | Unique identifier used by subscribers and logs (`global_headlines`, `ai`, …) |
| `mode` | Either `headlines` or `topic`; determines which runner executes the digest |
| `news_queries` | Array of NewsAPI payloads; edit to change coverage or add new topics |
| `email.subject_template` | Python-style format string (e.g. `"AI Briefing - {local_dt:%Y-%m-%d %H:%M}"`) |
| `output.filename_prefix` | Prefix used when writing the Markdown digest file |
| `newsapi.max_age_days` | (Optional) Caps article age for `everything` queries |

### `config/subscribers.json`

```json
{
  "defaults": {
    "name": "zjb",
    "frequency": "daily",
    "send_time": "08:00",
    "timezone": "Asia/Shanghai",
    "languages": ["zh-Hans", "en"]
  },
  "subscribers": [
    {
      "id": "zjb",
      "email": "1047962614@qq.com",
      "digests": ["global_headlines", "science_tech", "ai"]
    },
    {
      "id": "nodels",
      "email": "jiabaozhang098@gmail.com",
      "digests": ["global_headlines", "china_economy", "gold_fx"]
    }
  ]
}
```

- `defaults` supplies optional fallbacks (used when a subscriber omits a value).
- `subscribers` is an array; each subscriber needs an `id`, `email`, and at least one digest id in `digests`.
- Add or remove subscribers by editing this file—no code changes required.
- When a digest resolves to zero subscribers, the mailer falls back to `DAILYNEWS_EMAIL_TO`.

- `config/run_state.json` is generated automatically and stores `last_run` timestamps per digest. Legacy files
  `config/run_state_headlines.json` and `config/run_state_topics.json` are migrated on first run and no longer used.

## Running Digests

```bash
uv run main.py            # generate all digests (headlines + topics)
uv run main.py headlines  # only global headlines
uv run main.py topics     # all topic digests
```

Output Markdown files are stored under `digests/` with the prefix specified in `config/digest.json`.  
After each digest is written, the application calls `mailer.send_digest_via_email` to deliver the content to the resolved subscribers.

## Adding a New Digest
1. Duplicate an entry in `config/digest.json` and adjust:
   - `id` (lowercase slug, e.g. `entertainment`)
   - `display_name`, `subject_template`, `filename_prefix`
   - `news_queries` payloads (language, keywords, etc.)
2. Assign subscribers to the new digest by updating their `digests` array in `config/subscribers.json`.
3. Run `uv run main.py topics` (or `headlines` depending on `mode`) to verify a Markdown file is generated.
4. Remove `DAILYNEWS_EMAIL_DRY_RUN` to send real emails once satisfied.

## Mail Delivery Notes
- `mailer.send_digest_via_email` now accepts structured recipients (list of `{email, name}`) and sets friendly headers automatically.
- QQ SMTP is configured as the default (`smtp.qq.com:587`), but you can change `SMTP_HOST`/`SMTP_PORT_TLS` in `mailer.py` if needed.
- Logs include recipient counts and the digest id for auditing.

## Repository Scripts
- `headline.py` executes the `global_headlines` digest.
- `topic.py` iterates every digest with `"mode": "topic"`.
- `config_loader.py` validates and caches configuration files for both digests and subscribers.

## Contributing
Pull requests are welcome! Please open an issue to discuss any large changes, especially if they touch the config schema or delivery flow.

## License
This project is released under the MIT License. See [LICENSE](LICENSE) for details.
