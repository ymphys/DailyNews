#!/usr/bin/env python3
"""
Shared utilities for fetching NewsAPI content, summarizing with OpenAI,
and writing Markdown digests.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from time import sleep
from typing import Any, Dict, List, Optional, Sequence, Tuple
import re

import httpx

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def _configure_logger() -> logging.Logger:
    logger = logging.getLogger("news_digest")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(LOG_DIR / "news_digest.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    logger.addHandler(stream_handler)

    logger.propagate = False
    return logger


LOGGER = _configure_logger()

CONFIG_DIR = Path("config")
CONFIG_DIR.mkdir(exist_ok=True)

DIGEST_DIR = Path("digests")
DIGEST_DIR.mkdir(exist_ok=True)

NEWS_API_KEY = os.environ["NEWSAPI_ORG_KEY"]
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
SESSION = httpx.Client(timeout=30.0)

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
EVERYTHING_MAX_AGE_DAYS = 7
NEWSAPI_MAX_RETRIES = 3
NEWSAPI_RETRY_BASE_SECONDS = 8


def mask_token(token: str, prefix: int = 4, suffix: int = 4) -> str:
    """Return a partially masked version of a token for safe logging."""
    if not token:
        return ""
    if len(token) <= prefix + suffix:
        return token
    return f"{token[:prefix]}...{token[-suffix:]}"


def load_state(state_path: Path, default_state: Dict[str, Any]) -> Dict[str, Any]:
    """Load persisted state or return defaults."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning("Failed to read state file %s (%s); using defaults.", state_path, exc)
            data = {}
    else:
        data = {}

    state = json.loads(json.dumps(default_state))
    state.update({k: v for k, v in data.items() if k in default_state})

    normalized_queries = []
    for query in state.get("news_queries", []):
        updated = dict(query)
        updated.setdefault("endpoint", "top-headlines")
        normalized_queries.append(updated)
    state["news_queries"] = normalized_queries
    return state


def save_state(state_path: Path, state: Dict[str, Any]) -> None:
    """Persist run state to disk."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as fh:
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
        raise RuntimeError("LLM response was not valid JSON") from exc


def _compute_reset_delay(reset_header: str) -> int:
    """Best-effort parse of NewsAPI X-RateLimit-Reset header to seconds."""
    now = dt.datetime.now(dt.timezone.utc)
    try:
        numeric_value = float(reset_header)
        if numeric_value > now.timestamp():
            return max(0, int(numeric_value - now.timestamp()))
        return max(0, int(numeric_value))
    except ValueError:
        pass

    try:
        parsed = reset_header
        if parsed.endswith("Z"):
            parsed = parsed[:-1] + "+00:00"
        when = dt.datetime.fromisoformat(parsed)
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        return max(0, int((when - now).total_seconds()))
    except ValueError:
        LOGGER.debug("Unable to parse X-RateLimit-Reset header: %s", reset_header)
        return NEWSAPI_RETRY_BASE_SECONDS


def make_query_slug(value: Optional[str], fallback: str) -> str:
    """Convert a query value into a filesystem-friendly slug."""
    if not value:
        return fallback

    slug = value.strip().lower()
    slug = slug.replace('"', "").replace("'", "")
    slug = slug.replace("(", "").replace(")", "")
    slug = slug.replace("：", "-").replace("，", "-")
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff\-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-_")

    return slug or fallback


def build_story_lines(briefing: Dict[str, Any], article: Dict[str, Any]) -> List[str]:
    """Return formatted markdown lines for a single story."""
    source = (article.get("source") or {}).get("name", "Unknown source")
    published = article.get("publishedAt") or "N/A"
    url = article.get("url")
    language_code = article.get("query_language")
    language_label = LANGUAGE_LABELS.get(language_code, language_code or "Unknown")
    endpoint = article.get("query_endpoint", "top-headlines")

    lines = [
        f"### {briefing.get('headline', 'Untitled')} — {source}",
        f"- Published: {published}",
        f"- Language: {language_label}",
        f"- Endpoint: {endpoint}",
    ]
    if url:
        lines.append(f"- Original: {url}")
    lines.append("")

    takeaways = briefing.get("key_takeaways") or []
    if takeaways:
        lines.append("**Key Takeaways**")
        for bullet in takeaways:
            lines.append(f"- {bullet}")
        lines.append("")

    clarifications = briefing.get("term_clarifications") or []
    if clarifications:
        lines.append("**Term Explanations**")
        for item in clarifications:
            lines.append(f"- `{item['term']}` — {item['explanation']}")
        lines.append("")

    english_brief = (briefing.get("english_brief") or "").strip()
    if english_brief:
        lines.append("**English Brief**")
        lines.append("")
        lines.append(english_brief)
        lines.append("")

    chinese_brief = (briefing.get("chinese_brief") or "").strip()
    if chinese_brief:
        lines.append("**简体中文摘要**")
        lines.append("")
        lines.append(chinese_brief)
        lines.append("")

    return lines


def render_digest(title: str, story_entries: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]]) -> str:
    """Create a Markdown digest string for the provided stories."""
    lines = [
        f"# {title}",
        "",
        "## Stories",
        "",
    ]
    for briefing, article in story_entries:
        lines.extend(build_story_lines(briefing, article))
    return "\n".join(lines).strip() + "\n"


def build_story_entries(
    articles: Sequence[Dict[str, Any]], briefings: Sequence[Dict[str, Any]]
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Match briefings with their source articles by ID."""
    article_lookup = {idx: article for idx, article in enumerate(articles)}
    story_entries: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for briefing in briefings:
        article = article_lookup.get(briefing.get("id"))
        if article is None:
            LOGGER.warning("Missing article for briefing id=%s; skipping.", briefing.get("id"))
            continue
        story_entries.append((briefing, article))
    return story_entries


def write_digest(
    title: str,
    story_entries: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]],
    output_dir: Path,
    filename: str,
) -> str:
    """Write a Markdown digest file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    content = render_digest(title, story_entries)
    destination = output_dir / filename
    with open(destination, "w", encoding="utf-8") as fh:
        fh.write(content)
    LOGGER.info("Saved digest to %s", destination)
    return str(destination)


def chunked(seq: Sequence[Any], size: int) -> List[List[Any]]:
    """Yield successive slices from seq of length size."""
    return [list(seq[i : i + size]) for i in range(0, len(seq), size)]


def fetch_news(
    params: Dict[str, Any],
    endpoint: str = "top-headlines",
    *,
    max_retries: int = NEWSAPI_MAX_RETRIES,
    retry_base_seconds: int = NEWSAPI_RETRY_BASE_SECONDS,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Fetch news articles and return them with response metadata for logging."""
    url = f"https://newsapi.org/v2/{endpoint}"
    LOGGER.info("Requesting %s with params=%s", endpoint, params)

    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = SESSION.get(url, headers={"X-Api-Key": NEWS_API_KEY}, params=params)
            resp.raise_for_status()
            break
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            headers = exc.response.headers
            if status == 429 and attempt < max_retries:
                retry_after_header = headers.get("Retry-After")
                wait_seconds = retry_base_seconds * attempt

                if retry_after_header:
                    try:
                        wait_seconds = max(wait_seconds, int(float(retry_after_header)))
                    except ValueError:
                        LOGGER.debug("Unable to parse Retry-After header: %s", retry_after_header)

                reset_header = headers.get("X-RateLimit-Reset")
                if reset_header:
                    wait_seconds = max(wait_seconds, _compute_reset_delay(reset_header))

                LOGGER.warning(
                    "Rate limit hit for %s (attempt %s/%s). Sleeping %s seconds before retry.",
                    endpoint,
                    attempt,
                    max_retries,
                    wait_seconds,
                )
                sleep(wait_seconds)
                last_error = exc
                continue

            last_error = exc
            break
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < max_retries:
                wait_seconds = retry_base_seconds * attempt
                LOGGER.warning(
                    "HTTP error fetching %s (attempt %s/%s): %s. Retrying in %s seconds.",
                    endpoint,
                    attempt,
                    max_retries,
                    exc,
                    wait_seconds,
                )
                sleep(wait_seconds)
                continue
            break
    else:
        raise RuntimeError("Failed to contact NewsAPI after retries.") from last_error

    if last_error and "resp" not in locals():
        raise last_error

    data = resp.json()
    articles = data.get("articles", [])
    meta = {
        "endpoint": endpoint,
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
    queries: Sequence[Dict[str, Any]],
    published_after: Optional[dt.datetime],
    *,
    everything_max_age_days: int = EVERYTHING_MAX_AGE_DAYS,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Execute multiple NewsAPI queries, filter by timestamp, and deduplicate by URL."""
    all_articles: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    for idx, query in enumerate(queries):
        params = dict(query)
        raw_query = dict(query)
        endpoint = params.pop("endpoint", "top-headlines")
        language = params.get("language") or raw_query.get("language")
        country = raw_query.get("country")

        if endpoint == "everything":
            has_search_filter = any(
                key in params for key in ("q", "sources", "domains", "excludeDomains")
            )
            if not has_search_filter:
                LOGGER.warning(
                    "Skipping 'everything' query without search filters: %s", query
                )
                continue
            if published_after and "from" not in params:
                cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=everything_max_age_days)
                from_value = published_after
                if from_value.tzinfo is None:
                    from_value = from_value.replace(tzinfo=dt.timezone.utc)
                if from_value < cutoff:
                    original_from = from_value
                    LOGGER.info(
                        "Clamping 'from' for query %s to %s-day window (was %s).",
                        idx,
                        everything_max_age_days,
                        original_from.isoformat(),
                    )
                    from_value = cutoff
                params["from"] = from_value.isoformat()

        articles, meta = fetch_news(params, endpoint=endpoint)
        meta["language"] = language
        if not language and country:
            meta["country"] = country
        meta["query_index"] = idx
        meta["query_params"] = raw_query
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

            article["query_language"] = language or country
            article["query_endpoint"] = endpoint
            article["query_index"] = idx
            article["query_params"] = raw_query
            article["query_q"] = raw_query.get("q")
            filtered.append(article)

        LOGGER.info(
            "Retained %s articles for endpoint=%s, language=%s after filtering.",
            len(filtered),
            endpoint,
            language or "unknown",
        )
        all_articles.extend(filtered)

    return all_articles, metas


def summarize_articles(
    articles: Sequence[Dict[str, Any]],
    *,
    batch_size: int = SUMMARY_BATCH_SIZE,
    max_attempts: int = MAX_SUMMARY_ATTEMPTS,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Summarize articles with DeepSeek or OpenAI, returning structured bilingual briefs."""
    if not articles:
        return [], {}

    from openai import OpenAI

    def _build_llm_client() -> Tuple[Any, str]:
        if DEEPSEEK_API_KEY:
            return (
                OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com"),
                "deepseek",
            )
        if not OPENAI_API_KEY:
            raise RuntimeError(
                "Neither DEEPSEEK_API_KEY nor OPENAI_API_KEY is configured for summarization."
            )
        return OpenAI(api_key=OPENAI_API_KEY), "responses"

    client, api_mode = _build_llm_client()

    def _invoke_llm(messages: List[Dict[str, str]]) -> Tuple[Any, str]:
        if api_mode == "deepseek":
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                max_tokens=2000,
                stream=False,
            )
            choices = getattr(response, "choices", None) or []
            content = ""
            if choices:
                choice = choices[0]
                message = getattr(choice, "message", None)
                if not message and isinstance(choice, dict):
                    message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content", "") or ""
                else:
                    content = getattr(message, "content", "") or ""
            return response, content

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=messages,
            max_output_tokens=2000,
        )
        return response, getattr(response, "output_text", "") or ""

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
            "query_endpoint": article.get("query_endpoint"),
        }
        for idx, article in enumerate(articles)
    ]

    instructions = (
        "你正在撰写全球新闻摘要。请为每篇文章完成以下内容：\n"
        "- 提炼一个适用于简报的标题。\n"
        "- 用英语提供2到4条关键要点。\n"
        "- 解释可能存在疑问的专业术语、缩写或命名实体。\n"
        "- 以英语写一段简洁叙述，概述背景与影响。\n"
        "- 提供一段自然的简体中文版本，涵盖相同要点。\n"
        "请返回如下结构的JSON对象：\n"
        "{\n"
        "  \"briefings\": [\n"
        "    {\n"
        "      \"id\": <整型文章ID>,\n"
        "      \"headline\": \"<字符串>\",\n"
        "      \"key_takeaways\": [\"<字符串>\", ...],\n"
        "      \"term_clarifications\": [\n"
        "        {\"term\": \"<字符串>\", \"explanation\": \"<字符串>\"}, ...\n"
        "      ],\n"
        "      \"english_brief\": \"<字符串>\",\n"
        "      \"chinese_brief\": \"<字符串>\"\n"
        "    }, ...\n"
        "  ],\n"
        "  \"summary_notes\": \"<字符串，可选>\"\n"
        "}\n"
        "仅返回有效的JSON对象。"
    )
    all_briefings: List[Dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    model_used: Optional[str] = None

    batches = chunked(prepared_articles, batch_size)
    LOGGER.info("Summarizing %s articles across %s batches.", len(prepared_articles), len(batches))

    def process_batch(batch: List[Dict[str, Any]], label: str) -> List[Dict[str, Any]]:
        nonlocal total_input_tokens, total_output_tokens, model_used

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

        for attempt in range(1, max_attempts + 1):
            response, raw_output = _invoke_llm(messages)

            usage = getattr(response, "usage", None)
            if usage:
                total_input_tokens += getattr(usage, "input_tokens", 0) or 0
                total_output_tokens += getattr(usage, "output_tokens", 0) or 0
                candidate_model = getattr(response, "model", None)
                if not candidate_model and api_mode == "deepseek":
                    candidate_model = "deepseek-chat"
                if candidate_model:
                    model_used = candidate_model

            try:
                structured = parse_structured_output(raw_output or "")
            except RuntimeError:
                snippet = (raw_output or "")[:500].replace("\n", " ")
                LOGGER.warning(
                    "Batch %s attempt %s produced invalid JSON (snippet=%s...)",
                    label,
                    attempt,
                    snippet,
                )
                if attempt == max_attempts:
                    if len(batch) > 1:
                        LOGGER.warning(
                            "Splitting batch %s (size=%s) after repeated JSON failures.",
                            label,
                            len(batch),
                        )
                        split_index = max(1, len(batch) // 2)
                        left = batch[:split_index]
                        right = batch[split_index:]
                        left_briefings = process_batch(left, f"{label}.L")
                        right_briefings = process_batch(right, f"{label}.R")
                        return left_briefings + right_briefings
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
                continue

            briefings = structured.get("briefings", [])
            return briefings

        raise RuntimeError("Failed to obtain structured summary after retries.")

    for idx, batch in enumerate(batches, start=1):
        batch_briefings = process_batch(batch, str(idx))
        all_briefings.extend(batch_briefings)
        LOGGER.info(
            "Completed batch %s/%s (briefings=%s).",
            idx,
            len(batches),
            len(all_briefings),
        )

    usage_data = {
        "model": model_used,
        "input_tokens": total_input_tokens or None,
        "output_tokens": total_output_tokens or None,
        "total_tokens": (total_input_tokens + total_output_tokens) or None,
    }

    LOGGER.info(
        "LLM summarization completed across %s batches (model=%s, total_tokens=%s)",
        len(batches),
        usage_data["model"],
        usage_data["total_tokens"],
    )

    return all_briefings, usage_data

__all__ = [
    "LOGGER",
    "CONFIG_DIR",
    "DIGEST_DIR",
    "LANGUAGE_LABELS",
    "SUMMARY_BATCH_SIZE",
    "MAX_SUMMARY_ATTEMPTS",
    "EVERYTHING_MAX_AGE_DAYS",
    "NEWSAPI_MAX_RETRIES",
    "NEWSAPI_RETRY_BASE_SECONDS",
    "mask_token",
    "load_state",
    "save_state",
    "parse_newsapi_datetime",
    "make_query_slug",
    "build_story_lines",
    "render_digest",
    "build_story_entries",
    "write_digest",
    "collect_articles",
    "summarize_articles",
    "fetch_news",
]
