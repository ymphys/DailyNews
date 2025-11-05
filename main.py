#!/usr/bin/env python3
"""
Convenience wrapper that runs both the headline and topic digests.
"""

from __future__ import annotations

import argparse
from typing import List

from headline import main as run_headlines
from topic import main as run_topics


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run news digests for headlines, topics, or both."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        choices=["headlines", "topics"],
        help="Specify which digests to run. Default runs both.",
    )
    args = parser.parse_args(argv)

    targets = args.targets or ["headlines", "topics"]

    if "headlines" in targets:
        run_headlines()
    if "topics" in targets:
        run_topics()


if __name__ == "__main__":
    main()
