#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from forward_nautobot.integrations.forward.dry_run import run_fixture_dry_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Forward dry run against a saved fixture payload."
    )
    parser.add_argument(
        "fixture",
        type=Path,
        help="Path to a JSON fixture mapping model names to Forward rows.",
    )
    parser.add_argument(
        "--models",
        default="",
        help="Comma-separated model names to include. Default: all models in the fixture.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=3,
        help="Number of sample rows to include in the support bundle.",
    )
    parser.add_argument(
        "--sharing-profile",
        choices=("external", "internal"),
        default="external",
        help="Redaction profile for the shared support bundle output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model_names = tuple(
        part.strip() for part in str(args.models or "").split(",") if part.strip()
    )
    result = run_fixture_dry_run(
        args.fixture,
        model_names=model_names or None,
        sample_size=args.sample_size,
        sharing_profile=args.sharing_profile,
    )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
