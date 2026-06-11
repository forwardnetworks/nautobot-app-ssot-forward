#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forward_nautobot.integrations.forward.contract_diff import diff_contract_snapshots
from forward_nautobot.integrations.forward.contract_diff import snapshot_contracts_from_git_ref
from forward_nautobot.integrations.forward.contract_diff import snapshot_current_contracts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a bundled contract diff report.")
    parser.add_argument(
        "--baseline-ref",
        default=os.environ.get("CONTRACT_DIFF_BASE_REF", "HEAD~1"),
        help="Git ref to compare against.",
    )
    parser.add_argument(
        "--output",
        default="dist/contract-diff-report.json",
        help="Path to write the diff report JSON.",
    )
    args = parser.parse_args(argv)

    current = snapshot_current_contracts()
    baseline = snapshot_contracts_from_git_ref(args.baseline_ref, repo_root=REPO_ROOT)
    report = diff_contract_snapshots(current, baseline)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True), encoding="utf-8")

    print(f"Contract diff report written to {output_path}.")
    print(f"Changed files: {len(report.entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
