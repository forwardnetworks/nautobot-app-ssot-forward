#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    "AGENTS.md",
    "ARCHITECTURE.md",
    "README.md",
    "docs/00_Project_Knowledge/README.md",
    "docs/03_Plans/active/2026-06-11-forward-nautobot-production-readiness-checklist.md",
    "docs/03_Plans/active/2026-06-11-forward-nautobot-future-improvements.md",
    "forward_nautobot/migrations/0001_initial.py",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "scripts/check_sensitive_content.py",
    "scripts/check_query_contracts.py",
    "scripts/generate_contract_diff_report.py",
    "scripts/check_wheel_contents.py",
    "scripts/check_release_state.py",
]

PLAN_REQUIRED_HEADINGS = [
    "## Goal",
    "## Scope",
    "## Checklist",
    "## Next Tranche",
    "## Exit Criteria",
]

ROADMAP_REQUIRED_HEADINGS = [
    "## Goal",
    "## Baseline",
    "## Roadmap",
    "## 100% Production Quality",
    "## Out of Scope",
    "## Next Step",
]

REQUIRED_TEXT = {
    "ARCHITECTURE.md": [
        "Nautobot 3.1",
        "contract fields unnormalized",
        "Support-bundle capture",
    ],
    "README.md": [
        "Forward API client",
        "GitHub Actions CI",
    ],
    "docs/00_Project_Knowledge/README.md": [
        "check_sensitive_content.py",
        "check_harness.py",
    ],
    ".github/workflows/ci.yml": [
        "check_sensitive_content.py",
        "check_harness.py",
        "check_query_contracts.py",
        "generate_contract_diff_report.py",
        "check_wheel_contents.py",
        "pytest",
        "build",
    ],
    ".github/workflows/release.yml": [
        "check_sensitive_content.py",
        "check_harness.py",
        "check_release_state.py",
        "check_query_contracts.py",
        "generate_contract_diff_report.py",
        "check_wheel_contents.py",
        "softprops/action-gh-release",
    ],
}


def _check_required_paths(failures: list[str]) -> None:
    for relative_path in REQUIRED_PATHS:
        if not (REPO_ROOT / relative_path).exists():
            failures.append(f"missing required path: {relative_path}")


def _check_required_text(failures: list[str]) -> None:
    for relative_path, fragments in REQUIRED_TEXT.items():
        path = REPO_ROOT / relative_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment not in text:
                failures.append(f"{relative_path} must mention: {fragment}")


def _check_plan_headings(failures: list[str]) -> None:
    plan_path = (
        REPO_ROOT
        / "docs/03_Plans/active/2026-06-11-forward-nautobot-production-readiness-checklist.md"
    )
    if not plan_path.exists():
        return
    text = plan_path.read_text(encoding="utf-8")
    for heading in PLAN_REQUIRED_HEADINGS:
        if heading not in text:
            failures.append(f"{plan_path.relative_to(REPO_ROOT)} must include heading: {heading}")


def _check_roadmap_headings(failures: list[str]) -> None:
    roadmap_path = (
        REPO_ROOT / "docs/03_Plans/active/2026-06-11-forward-nautobot-future-improvements.md"
    )
    if not roadmap_path.exists():
        return
    text = roadmap_path.read_text(encoding="utf-8")
    for heading in ROADMAP_REQUIRED_HEADINGS:
        if heading not in text:
            failures.append(
                f"{roadmap_path.relative_to(REPO_ROOT)} must include heading: {heading}"
            )


def main() -> int:
    failures: list[str] = []
    _check_required_paths(failures)
    _check_required_text(failures)
    _check_plan_headings(failures)
    _check_roadmap_headings(failures)

    if failures:
        print("Harness check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Harness check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
