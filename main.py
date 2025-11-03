#!/usr/bin/env python3
"""
Pull news from NewsAPI, summarize with OpenAI, emit a Markdown digest.
Requires env vars: NEWSAPI_ORG_KEY, OPENAI_API_KEY.
Adds run logging, bilingual briefs, terminology explanations, and deep links.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

NEWS_API_KEY = os.environ["NEWSAPI_ORG_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
SESSION = httpx.Client(timeout=30.0)

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

CONFIG_DIR = Path("config")
STATE_PATH = CONFIG_DIR / "run_state.json"

LOGGER = logging.getLogger("news_digest")
if not LOGGER.handlers:
    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(LOG_DIR / "news_digest.log")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    LOGGER.addHandler(stream_handler)

    LOGGER.propagate = False

DEFAULT_STATE = {
    "news_queries": [
        {"language": "en", "pageSize": 40},
        {"language": "zh", "pageSize": 40},
    ],
    "last_run": None,
}

LANGUAGE_LABELS = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "he": "Hebrew",
    "it": "Italian",
    "nl": "Dutch",
    "no": "Norwegian",
    "pt": "Portuguese",
    "ru": "Russian",
    "sv": "Swedish",
    "ud": "Undefined",
    "zh": "Chinese",
}

SUMMARY_BATCH_SIZE = 4
MAX_SUMMARY_ATTEMPTS = 3


def mask_token(token: str, prefix: int = 4, suffix: int = 4) -> str:
    """Return a partially masked version of a token for safe logging."""
    if not token:
        return ""
    if len(token) <= prefix + suffix:
        return token
    return f"{token[:prefix]}...{token[-suffix:]}"


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(exist_ok=True)


def load_state() -> Dict[str, Any]:
    """Load persisted state or return defaults."""
    ensure_config_dir()
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning("Failed to read state file (%s); using defaults.", exc)
            data = {}
    else:
        data = {}
    state = DEFAULT_STATE.copy()
    state.update({k: v for k, v in data.items() if k in DEFAULT_STATE})
    return state


def save_state(state: Dict[str, Any]) -> None:
    """Persist run state to disk."""
    ensure_config_dir()
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def parse_newsapi_datetime(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return dt.datetime.fromisoformat(value)
    except ValueError:
        LOGGER.debug("Unparsable publishedAt value: %s", value)
        return None


def strip_markdown_code_fence(payload: str) -> str:
    """Remove surrounding markdown code fences if present."""
    text = payload.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.strip().startswith("json"):
                text = text.strip()[4:].lstrip()
    return text.strip()


def parse_structured_output(raw_output: str) -> Dict[str, Any]:
    """Parse the model output into JSON, logging diagnostics on failure."""
    cleaned = strip_markdown_code_fence(raw_output)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        LOGGER.error("Failed to parse model output as JSON: %s", cleaned)
        raise RuntimeError("OpenAI response was not valid JSON") from exc


def fetch_news(params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Fetch news articles and return them with response metadata for logging."""
    LOGGER.info("Requesting news with params=%s", params)
    resp = SESSION.get(
        "https://newsapi.org/v2/top-headlines",
        headers={"X-Api-Key": NEWS_API_KEY},
        params=params,
    )
    resp.raise_for_status()
    data = resp.json()
    articles = data.get("articles", [])
    meta = {
        "request_params": params,
        "status": data.get("status"),
        "total_results": data.get("totalResults"),
        "rate_limit": {
            "limit": resp.headers.get("X-RateLimit-Limit"),
            "remaining": resp.headers.get("X-RateLimit-Remaining"),
            "reset": resp.headers.get("X-RateLimit-Reset"),
        },
    }
    LOGGER.info(
        "NewsAPI returned %s articles (status=%s, remaining=%s)",
        len(articles),
        meta["status"],
        meta["rate_limit"]["remaining"],
    )
    return articles, meta


def collect_articles(
    queries: List[Dict[str, Any]],
    published_after: Optional[dt.datetime],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Execute multiple NewsAPI queries, filter by timestamp, and deduplicate by URL."""
    all_articles: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    for query in queries:
        params = dict(query)
        language = params.get("language")
        articles, meta = fetch_news(params)
        meta["language"] = language
        metas.append(meta)

        filtered: List[Dict[str, Any]] = []
        for article in articles:
            published_at = parse_newsapi_datetime(article.get("publishedAt"))
            if published_after and published_at and published_at <= published_after:
                continue

            url = article.get("url")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)

            article["query_language"] = language
            filtered.append(article)

        LOGGER.info(
            "Retained %s articles for language=%s after filtering.",
            len(filtered),
            language or "unknown",
        )
        all_articles.extend(filtered)

    return all_articles, metas


def chunked(seq: List[Any], size: int) -> List[List[Any]]:
    """Yield successive slices from seq of length size."""
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def summarize_articles(
    articles: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    """Summarize articles with OpenAI, returning structured bilingual briefs."""
    if not articles:
        return [], "", {}

    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    prepared_articles = [
        {
            "id": idx,
            "title": article.get("title"),
            "source": (article.get("source") or {}).get("name"),
            "published_at": article.get("publishedAt"),
            "description": article.get("description"),
            "content": article.get("content"),
            "url": article.get("url"),
            "query_language": article.get("query_language"),
        }
        for idx, article in enumerate(articles)
    ]

    instructions = (
        "You are producing a world news digest. For each article, craft:\n"
        "- A headline suitable for a briefing.\n"
        "- 2-4 key takeaways in English.\n"
        "- Explanations for any specialized terms, acronyms, or named entities that may be unclear.\n"
        "- A compact narrative paragraph in English capturing context and implications.\n"
        "- A natural Simplified Chinese translation of that paragraph.\n"
        "Include any details necessary for readers who do not speak the article's original language.\n"
        "Return a JSON object with this shape:\n"
        "{\n"
        '  "briefings": [\n'
        "    {\n"
        '      "id": <int article id>,\n'
        '      "headline": "<string>",\n'
        '      "key_takeaways": ["<string>", ...],\n'
        '      "term_clarifications": [\n'
        "        {\"term\": \"<string>\", \"explanation\": \"<string>\"}, ...\n"
        "      ],\n"
        '      "english_brief": "<string>",\n'
        '      "chinese_brief": "<string>"\n'
        "    }, ...\n"
        "  ],\n"
        '  "summary_notes": "<string, optional>"\n'
        "}\n"
        "Respond with valid JSON only (no markdown code fences)."
    )

    all_briefings: List[Dict[str, Any]] = []
    notes: List[str] = []
    total_input_tokens = 0
    total_output_tokens = 0
    model_used: Optional[str] = None

    batches = chunked(prepared_articles, SUMMARY_BATCH_SIZE)
    LOGGER.info("Summarizing %s articles across %s batches.", len(prepared_articles), len(batches))

    for idx, batch in enumerate(batches, start=1):
        payload = json.dumps(
            {
                "instructions": instructions,
                "articles": batch,
            },
            ensure_ascii=False,
        )

        messages = [
            {
                "role": "system",
                "content": "You write bilingual world news briefs with contextual explanations.",
            },
            {
                "role": "user",
                "content": payload,
            },
        ]

        structured: Optional[Dict[str, Any]] = None

        for attempt in range(1, MAX_SUMMARY_ATTEMPTS + 1):
            completion = client.responses.create(
                model="gpt-4.1-mini",
                input=messages,
                max_output_tokens=2000,
            )

            usage = getattr(completion, "usage", None)
            if usage:
                total_input_tokens += getattr(usage, "input_tokens", 0) or 0
                total_output_tokens += getattr(usage, "output_tokens", 0) or 0
                model_used = getattr(completion, "model", model_used)

            raw_output = completion.output_text
            try:
                structured = parse_structured_output(raw_output)
                break
            except RuntimeError:
                snippet = raw_output[:500].replace("\n", " ")
                LOGGER.warning(
                    "Batch %s attempt %s produced invalid JSON (snippet=%s...)",
                    idx,
                    attempt,
                    snippet,
                )
                if attempt == MAX_SUMMARY_ATTEMPTS:
                    raise
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply was not valid JSON. "
                            "Re-send the briefing for the same articles strictly as valid JSON. "
                            "Return only the JSON object."
                        ),
                    }
                )

        if structured is None:
            raise RuntimeError("Failed to obtain structured summary after retries.")

        all_briefings.extend(structured.get("briefings", []))
        summary_note = structured.get("summary_notes", "")
        if summary_note:
            notes.append(summary_note.strip())

        LOGGER.info("Completed batch %s/%s (briefings=%s).", idx, len(batches), len(all_briefings))

    summary_notes = "\n\n".join(filter(None, notes))
    usage_data = {
        "model": model_used,
        "input_tokens": total_input_tokens or None,
        "output_tokens": total_output_tokens or None,
        "total_tokens": (total_input_tokens + total_output_tokens) or None,
    }

    LOGGER.info(
        "OpenAI summarization completed across %s batches (model=%s, total_tokens=%s)",
        len(batches),
        usage_data["model"],
        usage_data["total_tokens"],
    )

    return all_briefings, summary_notes, usage_data


def save_markdown(
    articles: List[Dict[str, Any]],
    briefings: List[Dict[str, Any]],
    summary_notes: str,
    output_dir: str = "digests",
) -> str:
    """
    Persist a Markdown digest that includes original URLs and bilingual analysis.
    """
    os.makedirs(output_dir, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    path = f"{output_dir}/world-briefing-{ts}.md"

    article_lookup = {idx: article for idx, article in enumerate(articles)}

    lines = [
        f"# World News Briefing — {dt.datetime.now():%Y-%m-%d %H:%M}",
        "",
    ]

    if summary_notes:
        lines.extend(
            [
                "## Analyst Notes",
                summary_notes,
                "",
            ]
        )

    lines.append("## Stories")
    lines.append("")

    for briefing in briefings:
        article = article_lookup.get(briefing["id"], {})
        source_name = (article.get("source") or {}).get("name", "Unknown source")
        published = article.get("publishedAt")
        url = article.get("url")
        language_code = article.get("query_language")
        language_label = LANGUAGE_LABELS.get(language_code, language_code or "Unknown")

        lines.extend(
            [
                f"### {briefing['headline']} — {source_name}",
                f"- Published: {published or 'N/A'}",
                f"- Language: {language_label}",
            ]
        )
        if url:
            lines.append(f"- Original: {url}")
        lines.append("")

        lines.append("**Key Takeaways**")
        for bullet in briefing.get("key_takeaways", []):
            lines.append(f"- {bullet}")
        lines.append("")

        clarifications = briefing.get("term_clarifications") or []
        if clarifications:
            lines.append("**Term Explanations**")
            for item in clarifications:
                lines.append(f"- `{item['term']}` — {item['explanation']}")
            lines.append("")

        lines.append("**English Brief**")
        lines.append("")
        lines.append(briefing.get("english_brief", "").strip())
        lines.append("")

        lines.append("**简体中文摘要**")
        lines.append("")
        lines.append(briefing.get("chinese_brief", "").strip())
        lines.append("")

    markdown_content = "\n".join(lines).strip() + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(markdown_content)

    LOGGER.info("Saved digest to %s", path)
    return path


if __name__ == "__main__":
    run_started = dt.datetime.now(dt.timezone.utc)
    state = load_state()
    last_run_iso = state.get("last_run")
    last_run_dt = parse_newsapi_datetime(last_run_iso) if last_run_iso else None
    news_queries = state.get("news_queries") or DEFAULT_STATE["news_queries"]

    articles, news_meta = collect_articles(news_queries, last_run_dt)
    briefings, summary_notes, openai_usage = summarize_articles(articles)
    out_path = save_markdown(articles, briefings, summary_notes)

    state["last_run"] = run_started.isoformat()
    save_state(state)

    run_info = {
        "started_at": run_started.isoformat(),
        "newsapi": {
            "key": mask_token(NEWS_API_KEY),
            "last_run_filter": last_run_iso,
            "requests": news_meta,
        },
        "openai": {
            "key": mask_token(OPENAI_API_KEY),
            "usage": openai_usage,
        },
        "outputs": {
            "digest_path": out_path,
            "articles_summarized": len(briefings),
        },
    }

    LOGGER.info("Run summary: %s", json.dumps(run_info, ensure_ascii=False))
    print(f"Wrote digest to {out_path}")
