#!/usr/bin/env python3
"""
Helpers for reading configuration files such as config/digest.json and config/subscribers.json.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Type

CONFIG_ROOT = Path("config")
DIGEST_CONFIG_PATH = CONFIG_ROOT / "digest.json"
SUBSCRIBER_CONFIG_PATH = CONFIG_ROOT / "subscribers.json"


class ConfigError(RuntimeError):
    """Base class for configuration related failures."""


class DigestConfigError(ConfigError):
    """Raised when the digest configuration file is missing or malformed."""


class SubscriberConfigError(ConfigError):
    """Raised when the subscriber configuration file is missing or malformed."""


def _deep_copy(value: Any) -> Any:
    """Perform a deep copy using JSON serialization for plain data structures."""
    return json.loads(json.dumps(value))


def _read_json(path: Path, *, error_cls: Type[ConfigError], label: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise error_cls(f"{label} not found at {path}") from exc
    except OSError as exc:
        raise error_cls(f"Unable to read {label} at {path}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise error_cls(f"{label} is not valid JSON: {exc}") from exc


def _clone(entry: Dict[str, Any]) -> Dict[str, Any]:
    # Use JSON round-trip for an inexpensive deep copy of simple structures.
    return _deep_copy(entry)


def _ensure_str_list(
    value: Any,
    *,
    field: str,
    error_cls: Type[ConfigError],
    allow_empty: bool = True,
) -> List[str]:
    if value is None:
        return [] if allow_empty else _raise(error_cls, f"{field} must not be empty.")
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise error_cls(f"{field} must be a list of strings.")
    normalized: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise error_cls(f"{field} entries must be strings: {item!r}")
        normalized.append(item)
    if not normalized and not allow_empty:
        raise error_cls(f"{field} must not be empty.")
    return normalized


def _raise(error_cls: Type[ConfigError], message: str) -> None:
    raise error_cls(message)


def _validate_digest_entry(entry: Dict[str, Any]) -> None:
    required_fields = ("id", "mode", "news_queries")
    for field in required_fields:
        if not entry.get(field):
            raise DigestConfigError(f"Digest entry missing required field '{field}': {entry!r}")

    if not isinstance(entry["news_queries"], list):
        raise DigestConfigError(
            f"Digest '{entry['id']}' has non-list news_queries: {entry['news_queries']!r}"
        )


@lru_cache(maxsize=1)
def load_digests(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Load all digest definitions from disk.

    Returns deep copies so callers can freely mutate the results.
    """
    config_path = path or DIGEST_CONFIG_PATH
    payload = _read_json(config_path, error_cls=DigestConfigError, label="Digest config")
    digests = payload.get("digests")
    if not isinstance(digests, list):
        raise DigestConfigError("Digest config must define a top-level 'digests' list.")

    seen_ids = set()
    normalized: List[Dict[str, Any]] = []

    for entry in digests:
        if not isinstance(entry, dict):
            raise DigestConfigError(f"Digest entries must be objects, got: {entry!r}")
        _validate_digest_entry(entry)

        digest_id = entry["id"]
        if digest_id in seen_ids:
            raise DigestConfigError(f"Duplicate digest id detected: {digest_id}")
        seen_ids.add(digest_id)

        normalized.append(_clone(entry))

    return normalized


def reload_digests(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Clear the cache and reload digests from disk."""
    load_digests.cache_clear()
    return load_digests(path=path)


def get_digest(digest_id: str, *, path: Optional[Path] = None) -> Dict[str, Any]:
    """Return a single digest definition by id."""
    for entry in load_digests(path=path):
        if entry["id"] == digest_id:
            return _clone(entry)
    raise DigestConfigError(f"Digest id '{digest_id}' not found.")


def digests_by_mode(mode: str, *, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return all digest definitions that match the provided mode."""
    matches = [entry for entry in load_digests(path=path) if entry.get("mode") == mode]
    return [_clone(entry) for entry in matches]


def iter_digest_ids(*, path: Optional[Path] = None) -> Iterable[str]:
    """Yield digest ids in order of appearance."""
    for entry in load_digests(path=path):
        yield entry["id"]


@lru_cache(maxsize=1)
def load_subscribers(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load subscribers with defaults applied."""
    config_path = path or SUBSCRIBER_CONFIG_PATH
    payload = _read_json(
        config_path,
        error_cls=SubscriberConfigError,
        label="Subscriber config",
    )

    defaults = payload.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise SubscriberConfigError("Subscriber defaults must be an object.")
    defaults_copy = _clone(defaults) if defaults else {}

    raw_subs = payload.get("subscribers") or []
    if not isinstance(raw_subs, list):
        raise SubscriberConfigError("Subscriber config must define a 'subscribers' list.")

    normalized: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_emails = set()

    for idx, entry in enumerate(raw_subs):
        if not isinstance(entry, dict):
            raise SubscriberConfigError(f"Subscriber entry at index {idx} is not an object: {entry!r}")

        merged = _deep_copy(defaults_copy) if defaults_copy else {}
        for key, value in entry.items():
            merged[key] = _deep_copy(value) if isinstance(value, (dict, list)) else value

        subscriber_id = merged.get("id") or merged.get("email") or f"subscriber_{idx + 1}"
        if subscriber_id in seen_ids:
            raise SubscriberConfigError(f"Duplicate subscriber id detected: {subscriber_id}")
        seen_ids.add(subscriber_id)
        merged["id"] = subscriber_id

        email = merged.get("email")
        if not email or not isinstance(email, str):
            raise SubscriberConfigError(f"Subscriber '{subscriber_id}' must provide a valid email.")
        if email in seen_emails:
            raise SubscriberConfigError(f"Duplicate subscriber email detected: {email}")
        seen_emails.add(email)

        merged["digests"] = _ensure_str_list(
            merged.get("digests"),
            field=f"subscriber '{subscriber_id}' digests",
            error_cls=SubscriberConfigError,
        )
        merged["languages"] = _ensure_str_list(
            merged.get("languages"),
            field=f"subscriber '{subscriber_id}' languages",
            error_cls=SubscriberConfigError,
        )
        merged["active"] = bool(merged.get("active", True))

        normalized.append(merged)

    return {
        "defaults": defaults_copy,
        "subscribers": normalized,
    }


def reload_subscribers(path: Optional[Path] = None) -> Dict[str, Any]:
    """Clear the cache and reload subscribers from disk."""
    load_subscribers.cache_clear()
    return load_subscribers(path=path)


def subscribers_for_digest(
    digest_id: str,
    *,
    path: Optional[Path] = None,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    """Return subscribers enrolled for the specified digest id."""
    data = load_subscribers(path=path)
    matches: List[Dict[str, Any]] = []
    for entry in data.get("subscribers", []):
        if digest_id in entry.get("digests", []):
            if not include_inactive and not entry.get("active", True):
                continue
            matches.append(_clone(entry))
    return matches


def recipient_addresses_for_digest(
    digest_id: str,
    *,
    path: Optional[Path] = None,
    include_inactive: bool = False,
) -> List[str]:
    """Return email addresses for subscribers of a digest."""
    recipients = []
    for subscriber in subscribers_for_digest(
        digest_id,
        path=path,
        include_inactive=include_inactive,
    ):
        email = subscriber.get("email")
        if email:
            recipients.append(email)
    return recipients


__all__ = [
    "CONFIG_ROOT",
    "DIGEST_CONFIG_PATH",
    "SUBSCRIBER_CONFIG_PATH",
    "ConfigError",
    "DigestConfigError",
    "SubscriberConfigError",
    "digests_by_mode",
    "get_digest",
    "iter_digest_ids",
    "load_digests",
    "reload_digests",
    "load_subscribers",
    "reload_subscribers",
    "subscribers_for_digest",
    "recipient_addresses_for_digest",
]
