#!/usr/bin/env python3
"""Local CI mirror — run the same gate set GitHub CI runs, before pushing.

Mirrors .github/workflows/ci.yml so a release is verified locally first.
Each gate is a (label, argv) pair; the runner prints a pass/fail summary and
exits non-zero if any gate fails. Use --fast to skip the slow build + wheel
checks during iteration.

Usage:
    python scripts/ci_local.py            # full mirror
    python scripts/ci_local.py --fast     # skip build/wheel
    python scripts/ci_local.py --no-sensitive   # skip all-history scan (slow)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PY = sys.executable


def _gates(*, fast: bool, sensitive: bool) -> list[tuple[str, list[str]]]:
    gates: list[tuple[str, list[str]]] = []
    if sensitive:
        gates.append(
            ("sensitive-content", [PY, "scripts/check_sensitive_content.py", "--all-history"])
        )
    gates += [
        ("repo-harness", [PY, "scripts/check_harness.py"]),
        ("release-state", [PY, "scripts/check_release_state.py"]),
        ("query-contracts", [PY, "scripts/check_query_contracts.py"]),
        (
            "contract-diff",
            [
                PY,
                "scripts/generate_contract_diff_report.py",
                "--baseline-ref",
                "HEAD~1",
                "--output",
                "dist/contract-diff-report.json",
            ],
        ),
        ("pytest", [PY, "-m", "pytest", "-q", "-m", "not integration"]),
    ]
    if not fast:
        gates += [
            ("build", [PY, "-m", "build"]),
            ("wheel-contents", [PY, "scripts/check_wheel_contents.py"]),
        ]
    return gates


def run_gates(*, fast: bool, sensitive: bool) -> int:
    results: list[tuple[str, bool, float]] = []
    overall_ok = True
    for label, argv in _gates(fast=fast, sensitive=sensitive):
        print(f"\n=== {label} ===")
        started = time.monotonic()
        rc = subprocess.run(argv, cwd=REPO_ROOT).returncode
        elapsed = time.monotonic() - started
        ok = rc == 0
        overall_ok = overall_ok and ok
        results.append((label, ok, elapsed))
        if not ok:
            print(f"--- {label} FAILED (rc={rc}) ---")

    print("\n" + "=" * 48)
    print("CI mirror summary:")
    for label, ok, elapsed in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}  ({elapsed:.1f}s)")
    print("=" * 48)
    return 0 if overall_ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local CI gate mirror.")
    parser.add_argument("--fast", action="store_true", help="skip build + wheel-contents")
    parser.add_argument(
        "--no-sensitive",
        dest="sensitive",
        action="store_false",
        help="skip the all-history sensitive-content scan",
    )
    args = parser.parse_args(argv)
    return run_gates(fast=args.fast, sensitive=args.sensitive)


if __name__ == "__main__":
    raise SystemExit(main())
