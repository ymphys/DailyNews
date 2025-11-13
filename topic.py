#!/usr/bin/env python3
"""
Generate briefings for thematic NewsAPI "everything" queries.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from mailer import send_digest_via_email

from config_loader import DigestConfigError, digests_by_mode, subscribers_for_digest
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
LEGACY_STATE_PATH = Path("config/run_state_topics.json")
TOPIC_MODE = "topic"
TOPIC_DEFAULT_MAX_AGE_DAYS = 2

def _format_subject(digest_cfg: Dict[str, Any], now_local: dt.datetime) -> str:
    email_cfg = digest_cfg.get("email") or {}
    template = email_cfg.get("subject_template")
    if template:
        try:
            return template.format(local_dt=now_local)
        except Exception as exc:  # pragma: no cover
            LOGGER.warning(
                "Failed to format subject template '%s' for digest '%s': %s",
                template,
                digest_cfg.get("id"),
                exc,
            )
    display_name = digest_cfg.get("display_name") or digest_cfg.get("id") or "Topic Briefing"
    return f"{display_name} - {now_local:%Y-%m-%d %H:%M}"


def _resolve_filename_prefix(digest_cfg: Dict[str, Any]) -> str:
    output_cfg = digest_cfg.get("output") or {}
    return output_cfg.get("filename_prefix") or digest_cfg.get("id") or "topic-briefing"


def _resolve_max_age_days(digest_cfg: Dict[str, Any]) -> Optional[int]:
    newsapi_cfg = digest_cfg.get("newsapi") or {}
    value = newsapi_cfg.get("max_age_days")
    if value is None:
        return TOPIC_DEFAULT_MAX_AGE_DAYS
    try:
        return int(value)
    except (TypeError, ValueError):  # pragma: no cover
        LOGGER.warning(
            "Invalid max_age_days value '%s' for digest '%s'; using default %s.",
            value,
            digest_cfg.get("id"),
            TOPIC_DEFAULT_MAX_AGE_DAYS,
        )
        return TOPIC_DEFAULT_MAX_AGE_DAYS


def main() -> None:
    run_started = dt.datetime.now(dt.timezone.utc)
    try:
        topic_digests = digests_by_mode(TOPIC_MODE)
    except DigestConfigError as exc:
        LOGGER.error("Cannot load topic digests: %s", exc)
        print("Topic digest configuration error; aborting.")
        return

    if not topic_digests:
        LOGGER.warning("No topic digests configured; nothing to do.")
        print("No topic digests configured.")
        return

    state = load_state(STATE_PATH, {"digests": {}})
    digests_state: Dict[str, Any] = state.setdefault("digests", {})

    output_paths: List[str] = []
    outputs_summary: List[Dict[str, Any]] = []
    aggregated_news_meta: List[Any] = []
    openai_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    openai_model: Optional[str] = None

    for digest_cfg in topic_digests:
        digest_id = digest_cfg.get("id") or "<unknown>"
        news_queries = digest_cfg.get("news_queries") or []
        if not news_queries:
            LOGGER.warning("Digest '%s' has no news queries defined; skipping.", digest_id)
            continue

        digest_state: Dict[str, Any] = digests_state.get(digest_id, {})
        if not digest_state and LEGACY_STATE_PATH.exists():
            legacy = load_state(LEGACY_STATE_PATH, {"news_queries": [], "last_run": None})
            if legacy.get("last_run"):
                digest_state["last_run"] = legacy.get("last_run")
                LOGGER.info(
                    "Migrated last_run from legacy topic state file for digest '%s'.",
                    digest_id,
                )
        digests_state[digest_id] = digest_state

        digest_last_run_iso = digest_state.get("last_run")
        digest_last_run_dt = parse_newsapi_datetime(digest_last_run_iso) if digest_last_run_iso else None
        max_age_days = _resolve_max_age_days(digest_cfg)

        articles, news_meta = collect_articles(
            news_queries,
            digest_last_run_dt,
            everything_max_age_days=max_age_days,
        )
        aggregated_news_meta.extend(news_meta or [])

        if not articles:
            LOGGER.info("No articles retrieved for digest '%s'; skipping.", digest_id)
            continue

        briefings, usage = summarize_articles(articles)
        if not briefings:
            LOGGER.info("Summarizer returned no briefings for digest '%s'; skipping.", digest_id)
            continue

        if usage:
            if usage.get("model"):
                openai_model = usage.get("model")
            for token_key in ("input_tokens", "output_tokens", "total_tokens"):
                openai_totals[token_key] += usage.get(token_key) or 0

        now_local = dt.datetime.now()
        ts = now_local.strftime("%Y-%m-%d_%H%M")
        subject = _format_subject(digest_cfg, now_local)
        filename_prefix = _resolve_filename_prefix(digest_cfg)
        filename = f"{filename_prefix}-{ts}.md"
        title = subject

        story_entries = build_story_entries(articles, briefings)
        digest_path = write_digest(title, story_entries, DIGEST_DIR, filename)

        subscribers = subscribers_for_digest(digest_id)
        if subscribers:
            send_digest_via_email(Path(digest_path), subject, recipients=subscribers)
        else:
            LOGGER.info("No configured subscribers for digest '%s'; using environment recipients.", digest_id)
            send_digest_via_email(Path(digest_path), subject)
        output_paths.append(digest_path)

        outputs_summary.append(
            {
                "digest_id": digest_id,
                "digest_display": digest_cfg.get("display_name"),
                "digest_path": digest_path,
                "articles_summarized": len(briefings),
                "recipients": [subscriber.get("email") for subscriber in subscribers],
            }
        )

        digest_state["last_run"] = run_started.isoformat()
        digests_state[digest_id] = digest_state

    state["digests"] = digests_state
    save_state(STATE_PATH, state)

    run_info = {
        "started_at": run_started.isoformat(),
        "digest_ids": [entry.get("digest_id") for entry in outputs_summary],
        "newsapi": {
            "key": mask_token(os.environ.get("NEWSAPI_ORG_KEY", "")),
            "last_run_filter": {k: v.get("last_run") for k, v in digests_state.items()},
            "requests": aggregated_news_meta,
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
