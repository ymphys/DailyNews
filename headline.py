#!/usr/bin/env python3
"""
Generate a briefing from NewsAPI top-headlines queries.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, List
from mailer import send_digest_via_email

from digest_utils import (
    DIGEST_DIR,
    LOGGER,
    build_story_entries,
    collect_articles,
    mask_token,
    parse_newsapi_datetime,
    save_state,
    load_state,
    summarize_articles,
    write_digest,
)

STATE_PATH = Path("config/run_state_headlines.json")

DEFAULT_STATE: Dict[str, Any] = {
    "news_queries": [
        {"endpoint": "top-headlines", "country": "us", "pageSize": 30},
        {"endpoint": "top-headlines", "country": "fr", "pageSize": 30},
        {"endpoint": "top-headlines", "country": "de", "pageSize": 30},
    ],
    "last_run": None,
}


def main() -> None:
    run_started = dt.datetime.now(dt.timezone.utc)
    state = load_state(STATE_PATH, DEFAULT_STATE)
    news_queries: List[Dict[str, Any]] = state.get("news_queries") or DEFAULT_STATE["news_queries"]

    last_run_iso = state.get("last_run")
    last_run_dt = parse_newsapi_datetime(last_run_iso) if last_run_iso else None

    articles, news_meta = collect_articles(news_queries, last_run_dt)
    if not articles:
        LOGGER.info("No articles retrieved for headline digest; nothing to summarize.")
        state["last_run"] = run_started.isoformat()
        save_state(STATE_PATH, state)
        print("No new headline articles found.")
        return

    briefings, summary_notes, openai_usage = summarize_articles(articles)
    if not briefings:
        LOGGER.info("Summarizer returned no briefings for headline digest.")
        state["last_run"] = run_started.isoformat()
        save_state(STATE_PATH, state)
        print("Headline summarization produced no content.")
        return

    now_local = dt.datetime.now()
    ts = now_local.strftime("%Y-%m-%d_%H%M")
    title = f"Headline Briefing — {now_local:%Y-%m-%d %H:%M}"
    filename = f"headline-briefing-{ts}.md"
    story_entries = build_story_entries(articles, briefings)
    digest_path = write_digest(title, story_entries, DIGEST_DIR, filename)
    
    subject = title  # or customize
    send_digest_via_email(Path(digest_path), subject)

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
            "usage": openai_usage,
        },
        "outputs": {
            "digest_path": digest_path,
            "articles_summarized": len(briefings),
            "summary_notes": summary_notes,
        },
    }
    LOGGER.info("Headline run summary: %s", json.dumps(run_info, ensure_ascii=False))
    print(f"Wrote headline digest to {digest_path}")


if __name__ == "__main__":
    main()
