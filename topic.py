#!/usr/bin/env python3
"""
Generate briefings for thematic NewsAPI "everything" queries.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from digest_utils import (
    DIGEST_DIR,
    LOGGER,
    build_story_entries,
    collect_articles,
    load_state,
    make_query_slug,
    mask_token,
    parse_newsapi_datetime,
    save_state,
    summarize_articles,
    write_digest,
)

STATE_PATH = Path("config/run_state_topics.json")

DEFAULT_STATE: Dict[str, Any] = {
    "news_queries": [
        {
            "endpoint": "everything",
            "q": '("中国" OR "中国经济") AND (经济 OR 贸易 OR 增长)',
            "searchIn": "title,description",
            "language": "zh",
            "pageSize": 40,
            "sortBy": "publishedAt",
        },
        {
            "endpoint": "everything",
            "q": '("China" OR "Chinese") AND (economy OR trade OR growth)',
            "searchIn": "title,description",
            "language": "en",
            "pageSize": 40,
            "sortBy": "publishedAt",
        },
        {
            "endpoint": "everything",
            "q": '("中国" OR "中国科技") AND ("人工智能" OR "AI" OR "生成式")',
            "searchIn": "title,description,content",
            "language": "zh",
            "pageSize": 40,
            "sortBy": "publishedAt",
        },
        {
            "endpoint": "everything",
            "q": '("China" OR "Chinese") AND ("artificial intelligence" OR "AI")',
            "searchIn": "title,description",
            "language": "en",
            "pageSize": 40,
            "sortBy": "publishedAt",
        },
        {
            "endpoint": "everything",
            "q": '("黄金" OR "贵金属") AND ("美元" OR "美元汇率")',
            "searchIn": "title,description",
            "language": "zh",
            "pageSize": 40,
            "sortBy": "publishedAt",
        },
        {
            "endpoint": "everything",
            "q": '("gold" OR "precious metal") AND ("USD" OR "dollar")',
            "searchIn": "title,description",
            "language": "en",
            "pageSize": 40,
            "sortBy": "publishedAt",
        },
    ],
    "last_run": None,
}

TOPIC_MAX_AGE_DAYS = 1

def main() -> None:
    run_started = dt.datetime.now(dt.timezone.utc)
    state = load_state(STATE_PATH, DEFAULT_STATE)
    news_queries: List[Dict[str, Any]] = state.get("news_queries") or DEFAULT_STATE["news_queries"]

    last_run_iso = state.get("last_run")
    last_run_dt = parse_newsapi_datetime(last_run_iso) if last_run_iso else None

    articles, news_meta = collect_articles(
        news_queries,
        last_run_dt,
        everything_max_age_days=TOPIC_MAX_AGE_DAYS,
    )

    grouped_articles: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for article in articles:
        grouped_articles[article.get("query_index", -1)].append(article)

    now_local = dt.datetime.now()
    ts = now_local.strftime("%Y-%m-%d_%H%M")

    output_paths: List[str] = []
    openai_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    openai_model: Optional[str] = None
    outputs_summary: List[Dict[str, Any]] = []

    for idx, query in enumerate(news_queries):
        query_articles = grouped_articles.get(idx, [])
        if not query_articles:
            LOGGER.info("No new articles for topic query %s: %s", idx, query)
            continue

        briefings, summary_notes, usage = summarize_articles(query_articles)
        if not briefings:
            LOGGER.info("Summarizer returned no briefings for topic query %s.", idx)
            continue

        slug = make_query_slug(query.get("q"), f"topic-{idx}")
        title_topic = query.get("q") or query.get("sources") or f"Topic {idx + 1}"
        title = f"{title_topic} Briefing — {now_local:%Y-%m-%d %H:%M}"
        filename = f"{slug}-briefing-{ts}.md"

        story_entries = build_story_entries(query_articles, briefings)
        digest_path = write_digest(title, story_entries, DIGEST_DIR, filename)
        output_paths.append(digest_path)

        outputs_summary.append(
            {
                "query_index": idx,
                "query": query,
                "digest_path": digest_path,
                "articles_summarized": len(briefings),
                "summary_notes": summary_notes,
            }
        )

        if usage:
            if usage.get("model"):
                openai_model = usage.get("model")
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                openai_totals[key] += usage.get(key) or 0

    state["last_run"] = run_started.isoformat()
    save_state(STATE_PATH, state)

    run_info = {
        "started_at": run_started.isoformat(),
        "newsapi": {
            "key": mask_token(os.environ.get("NEWSAPI_ORG_KEY", "")),
            "last_run_filter": last_run_iso,
            "requests": news_meta,
        },
        "openai": {
            "key": mask_token(os.environ.get("OPENAI_API_KEY", "")),
            "model": openai_model,
            "usage": openai_totals,
        },
        "outputs": outputs_summary,
    }
    LOGGER.info("Topic run summary: %s", json.dumps(run_info, ensure_ascii=False))

    if output_paths:
        print(f"Wrote {len(output_paths)} topic digests:")
        for path in output_paths:
            print(f" - {path}")
    else:
        print("No topic digests generated.")


if __name__ == "__main__":
    main()
