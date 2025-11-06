# DailyNews

DailyNews is a lightweight newsroom assistant that gathers fresh headlines from multiple regions and languages, normalises the results, and drops them into an analyst-friendly bundle each day. The project is designed for researchers and newsletter writers who want reproducible, query-driven news digests without locking themselves into a SaaS dashboard.

---

## Installation Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-account/dailynews.git
   cd dailynews
   ```

2. **Create and activate a virtual environment** (optional but recommended)
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -e .
   ```

4. **Configure environment variables**
   - `NEWSAPI_KEY` – required, your API key for the NewsAPI.org endpoints (or another provider, depending on your adapter).
   - Optional `.env` file support is baked in via `python-dotenv`, so you can place credentials inside `.env` during development.

5. **Review configuration**
   - `config/run_state_topics.json` holds the query definitions executed on each run. Each entry lets you define the endpoint, languages, query strings, result counts, and sorting.

---

## Usage Instructions

Run the collector once:
```bash
python main.py --topics config/run_state_topics.json --output data/$(date +%Y%m%d)
```

Common flags:

| Flag | Description |
| --- | --- |
| `--topics PATH` | Path to the JSON topic configuration file. |
| `--output DIR` | Directory where the daily bundle will be written (raw JSON + summary CSV/Markdown). |
| `--max-pages N` | Override the default pagination depth. |
| `--since YYYY-MM-DD` | Only capture articles published after the date. |
| `--dry-run` | Print the queries that would be executed without hitting the API. |

Typical workflow:

1. Update `config/run_state_topics.json` to include the languages and keywords you care about.
2. Export `NEWSAPI_KEY`.
3. Run `python main.py`.
4. Inspect the generated bundle under `data/<YYYYMMDD>/` which contains the raw API responses, a stitched CSV, and a Markdown briefing made for quick review.

You can place the command in a cron job or GitHub Action to receive updates automatically.

---

## Technologies Used

- **Python 3.12+**
- **Requests** for resilient HTTP calls (with exponential backoff built in).
- **python-dotenv** for local environment management.
- **Pydantic / dataclasses** (optional) for schema validation of request/response payloads.
- **Rich / Typer** (optional) for CLI ergonomics and coloured console output.

> Exact dependencies are listed in `pyproject.toml`.

---

## Visuals

| Capture | Description |
| --- | --- |
| `docs/daily-summary.png` *(placeholder)* | Example Markdown digest produced for a single day. |
| `docs/topics-config.png` *(placeholder)* | The configuration editor highlighting multilingual query definitions. |

> Replace the placeholders above with actual screenshots or terminal captures once available.

---

## Badges

[![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)](#)
[![Coverage](https://img.shields.io/badge/coverage-90%25-blue.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](#)
[![Python](https://img.shields.io/badge/python-3.12+-3776AB.svg?logo=python&logoColor=white)](#)

> Swap the placeholder shields with your CI/coverage system once wired up.

---

## Project Status / Roadmap

**Current status:** Active development – core CLI fetcher, configuration-driven topics, and daily export pipeline are ready for internal use.

**Upcoming enhancements:**

- [ ] Multi-provider adapters (Guardian API, GDELT, RSS feeds).
- [ ] Deduplication heuristics across overlapping queries/languages.
- [ ] Named-entity recognition pipeline for automated tagging.
- [ ] Web dashboard (Streamlit or Next.js) for quick browsing.
- [ ] GitHub Actions workflow for nightly builds + Slack / email notifications.

Suggestions and pull requests are welcome — open an issue to start the conversation.
