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

from config_loader import DigestConfigError, get_digest, subscribers_for_digest
from digest_utils import (
    DIGEST_DIR,
    LOGGER,
    build_story_entries,
    collect_articles,
    load_state,
    mask_token,
    parse_newsapi_datetime,
    save_state,
    summarize_articles,
    write_digest,
)

STATE_PATH = Path("config/run_state.json")
LEGACY_STATE_PATH = Path("config/run_state_headlines.json")
HEADLINE_DIGEST_ID = "global_headlines"


def _load_digest_state() -> Dict[str, Any]:
    state = load_state(STATE_PATH, {"digests": {}})
    digests_state: Dict[str, Any] = state.setdefault("digests", {})
    digest_state: Dict[str, Any] = digests_state.get(HEADLINE_DIGEST_ID, {})

    if not digest_state and LEGACY_STATE_PATH.exists():
        legacy = load_state(LEGACY_STATE_PATH, {"news_queries": [], "last_run": None})
        if legacy.get("last_run"):
            digest_state["last_run"] = legacy.get("last_run")
            LOGGER.info(
                "Migrated last_run from legacy headline state file to unified run_state.json."
            )
    digests_state[HEADLINE_DIGEST_ID] = digest_state
    state["digests"] = digests_state
    return state


def _format_subject(digest_cfg: Dict[str, Any], now_local: dt.datetime) -> str:
    email_cfg = digest_cfg.get("email") or {}
    template = email_cfg.get("subject_template")
    if template:
        try:
            return template.format(local_dt=now_local)
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Failed to format subject template '%s': %s", template, exc)
    display_name = digest_cfg.get("display_name") or "Headline Briefing"
    return f"{display_name} - {now_local:%Y-%m-%d %H:%M}"


def _build_filename(prefix: str, timestamp: str) -> str:
    safe_prefix = prefix or "headline-briefing"
    return f"{safe_prefix}-{timestamp}.md"


def main() -> None:
    run_started = dt.datetime.now(dt.timezone.utc)
    try:
        digest_cfg = get_digest(HEADLINE_DIGEST_ID)
    except DigestConfigError as exc:
        LOGGER.error("Cannot load headline digest configuration: %s", exc)
        print("Headline digest configuration error; aborting.")
        return

    state = _load_digest_state()
    digests_state: Dict[str, Any] = state["digests"]
    digest_state: Dict[str, Any] = digests_state.get(HEADLINE_DIGEST_ID, {})

    news_queries: List[Dict[str, Any]] = digest_cfg.get("news_queries") or []
    if not news_queries:
        LOGGER.warning("No headline news queries defined in configuration.")
        print("No headline queries configured; nothing to do.")
        return

    last_run_iso = digest_state.get("last_run")
    last_run_dt = parse_newsapi_datetime(last_run_iso) if last_run_iso else None

    articles, news_meta = collect_articles(news_queries, last_run_dt)
    if not articles:
        LOGGER.info("No articles retrieved for headline digest; nothing to summarize.")
        state["last_run"] = run_started.isoformat()
        save_state(STATE_PATH, state)
        print("No new headline articles found.")
        return

    briefings, openai_usage = summarize_articles(articles)
    if not briefings:
        LOGGER.info("Summarizer returned no briefings for headline digest.")
        state["last_run"] = run_started.isoformat()
        save_state(STATE_PATH, state)
        print("Headline summarization produced no content.")
        return

    now_local = dt.datetime.now()
    ts = now_local.strftime("%Y-%m-%d_%H%M")
    subject = _format_subject(digest_cfg, now_local)
    filename_prefix = (digest_cfg.get("output") or {}).get("filename_prefix", "headline-briefing")
    title = subject
    filename = _build_filename(filename_prefix, ts)
    story_entries = build_story_entries(articles, briefings)
    digest_path = write_digest(title, story_entries, DIGEST_DIR, filename)

    subscribers = subscribers_for_digest(HEADLINE_DIGEST_ID)
    if subscribers:
        send_digest_via_email(Path(digest_path), subject, recipients=subscribers)
    else:
        LOGGER.info("No configured subscribers for digest '%s'; using environment recipients.", HEADLINE_DIGEST_ID)
        send_digest_via_email(Path(digest_path), subject)

    digest_state["last_run"] = run_started.isoformat()
    digests_state[HEADLINE_DIGEST_ID] = digest_state
    state["digests"] = digests_state
    save_state(STATE_PATH, state)

    run_info = {
        "started_at": run_started.isoformat(),
        "digest_id": HEADLINE_DIGEST_ID,
        "digest_display": digest_cfg.get("display_name"),
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
            "recipients": [subscriber.get("email") for subscriber in subscribers],
        },
    }
    LOGGER.info("Headline run summary: %s", json.dumps(run_info, ensure_ascii=False))
    print(f"Wrote headline digest to {digest_path}")


if __name__ == "__main__":
    main()
