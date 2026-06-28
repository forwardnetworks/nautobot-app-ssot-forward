#!/usr/bin/env python3
"""Grade a Forward support bundle offline → pass / warn / fail + first-order actions.

Operates on a saved (optionally redacted) bundle JSON, so it needs no Nautobot/DB.

Usage:
    python scripts/grade_support_bundle.py --input-json bundle.json
    cat bundle.json | python scripts/grade_support_bundle.py --input-json -
    python scripts/grade_support_bundle.py --input-json b.json --fail-on warn
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forward_nautobot.integrations.forward.support import (  # noqa: E402
    _GRADE_RANK,
    grade_support_bundle,
)


def _load(path: str) -> dict:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", required=True, help="Bundle JSON path, or - for stdin.")
    parser.add_argument(
        "--thresholds", default="", help="Optional JSON object overriding grade thresholds."
    )
    parser.add_argument(
        "--fail-on",
        choices=("warn", "fail"),
        default="fail",
        help="Minimum status that yields a non-zero exit code (default: fail).",
    )
    parser.add_argument("--json", action="store_true", help="Emit the full grade as JSON.")
    args = parser.parse_args(argv)

    bundle = _load(args.input_json)
    thresholds = json.loads(args.thresholds) if args.thresholds else None
    grade = grade_support_bundle(bundle, thresholds=thresholds)

    if args.json:
        print(json.dumps(grade, indent=2, sort_keys=True))
    else:
        print(f"Overall: {grade['status'].upper()}")
        for check in grade["checks"]:
            print(f"  [{check['status']:>4}] {check['name']}: {check['detail']}")
        if grade["first_order_actions"]:
            print("First-order actions:")
            for action in grade["first_order_actions"]:
                print(f"  - {action}")

    return 2 if _GRADE_RANK[grade["status"]] >= _GRADE_RANK[args.fail_on] else 0


if __name__ == "__main__":
    raise SystemExit(main())
