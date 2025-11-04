#!/usr/bin/env python3
"""
Convenience wrapper that runs both the headline and topic digests.
"""

from __future__ import annotations

from headline import main as run_headlines
from topic import main as run_topics


def main() -> None:
    run_headlines()
    run_topics()


if __name__ == "__main__":
    main()
