#!/usr/bin/env python3
"""Release automation for nautobot-app-ssot-forward.

Encodes the full release flow so version drift and stale tags cannot recur
(v0.2.0 shipped with __init__.py left at 0.1.1, and its tag went stale two
commits after the bump — both classes of error this script removes).

The version lives in TWO places that must move in lockstep:
  - pyproject.toml         [tool.poetry] version
  - forward_nautobot/__init__.py  ForwardNautobotConfig.version

Stages:
  prepare  - bump both versions, scaffold the release plan file
  verify   - run the local CI mirror (scripts/ci_local.py)
  publish  - branch, push, wait for GitHub CI, fast-forward main, tag the
             RELEASE COMMIT, create the GitHub release  (ONLY with --publish)

Default run is prepare + verify. Rollout never happens without --publish, so a
default run is a safe dry build.

Usage:
    python scripts/release.py 0.3.0 --summary "perf + gitops hardening"
    python scripts/release.py 0.3.0 --summary "..." --publish
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
INIT_PY = REPO_ROOT / "forward_nautobot/__init__.py"
PLAN_DIR = REPO_ROOT / "docs/03_Plans/active"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ReleaseError(RuntimeError):
    pass


# ---- pure, unit-tested helpers -------------------------------------------------


def bump_version_text(text: str, old: str, new: str, *, key: str = "version") -> str:
    """Replace exactly one `key = "old"` assignment with `key = "new"`.

    Raises if the assignment is not found exactly once, so a drifted or already
    bumped file fails loud instead of silently no-op'ing.
    """
    pattern = re.compile(rf'({re.escape(key)}\s*=\s*")' + re.escape(old) + r'(")')
    new_text, n = pattern.subn(rf"\g<1>{new}\g<2>", text)
    if n != 1:
        raise ReleaseError(f'expected exactly one `{key} = "{old}"` to bump, found {n}')
    return new_text


def read_pyproject_version(text: str) -> str:
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ReleaseError("could not read current version from pyproject.toml")
    return match.group(1)


def read_init_version(text: str) -> str:
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ReleaseError("could not read current version from __init__.py")
    return match.group(1)


def plan_filename(version: str, date: str) -> str:
    return f"{date}-release-{version}.md"


def plan_scaffold(version: str, summary: str, date: str) -> str:
    return (
        f"# Release {version}\n\n"
        f"Date: {date}\n"
        f"Summary: {summary}\n\n"
        "## Changes\n\n"
        "- _TBD_\n\n"
        "## Verification\n\n"
        "- `python scripts/ci_local.py`\n"
        "- Live WF smoke (locations write, skip path, diff path)\n\n"
        "## Rollout\n\n"
        f'- `python scripts/release.py {version} --summary "{summary}" --publish`\n'
    )


# ---- side-effecting stages -----------------------------------------------------


def run(cmd: list[str], *, check: bool = True) -> int:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if check and result.returncode != 0:
        raise ReleaseError(f"command failed ({result.returncode}): {' '.join(cmd)}")
    return result.returncode


def _today() -> str:
    # Date is injected, never computed, so behavior is reproducible in tests.
    out = subprocess.run(["date", "+%Y-%m-%d"], cwd=REPO_ROOT, capture_output=True, text=True)
    return out.stdout.strip()


def stage_prepare(version: str, summary: str, *, write: bool, date: str) -> None:
    py_text = PYPROJECT.read_text(encoding="utf-8")
    init_text = INIT_PY.read_text(encoding="utf-8")
    old_py = read_pyproject_version(py_text)
    old_init = read_init_version(init_text)
    if old_py != old_init:
        raise ReleaseError(
            f"version already drifted before bump: pyproject={old_py!r} init={old_init!r}; "
            "reconcile manually first."
        )
    print(f"[prepare] bump {old_py} -> {version} (pyproject + __init__)")
    new_py = bump_version_text(py_text, old_py, version, key="version")
    new_init = bump_version_text(init_text, old_init, version, key="version")
    plan_path = PLAN_DIR / plan_filename(version, date)
    if write:
        PYPROJECT.write_text(new_py, encoding="utf-8")
        INIT_PY.write_text(new_init, encoding="utf-8")
        if not plan_path.exists():
            plan_path.write_text(plan_scaffold(version, summary, date), encoding="utf-8")
        print(f"[prepare] wrote versions + plan {plan_path.relative_to(REPO_ROOT)}")
    else:
        print("[prepare] dry-run; no files written")


def stage_verify() -> None:
    print("[verify] running local CI mirror")
    run([sys.executable, "scripts/ci_local.py"])


def stage_publish(version: str, *, summary: str) -> None:
    tag = f"v{version}"
    branch = f"release/{version}"
    print(f"[publish] branch {branch}, tag {tag} on the release commit")
    run(["git", "checkout", "-b", branch])
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", f"release: cut {tag}\n\n{summary}"])
    run(["git", "push", "-u", "origin", branch])
    # Wait for CI on the branch before fast-forwarding main.
    run(["gh", "run", "watch", "--exit-status"], check=False)
    run(["git", "checkout", "main"])
    run(["git", "merge", "--ff-only", branch])
    run(["git", "push", "origin", "main"])
    # Tag the release commit (now HEAD of main), never a stale earlier commit.
    run(["git", "tag", tag])
    run(["git", "push", "origin", tag])
    run(["gh", "release", "create", tag, "--title", tag, "--notes", summary])
    print(f"[publish] {tag} released")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release automation.")
    parser.add_argument("version", help="new semver version, e.g. 0.3.0")
    parser.add_argument("--summary", default="", help="one-line release summary")
    parser.add_argument("--publish", action="store_true", help="run the publish stage (gated)")
    parser.add_argument("--no-verify", action="store_true", help="skip the local CI mirror")
    parser.add_argument("--dry-run", action="store_true", help="prepare without writing files")
    args = parser.parse_args(argv)

    if not SEMVER_RE.match(args.version):
        print(f"error: version {args.version!r} is not X.Y.Z")
        return 2

    date = _today()
    try:
        stage_prepare(args.version, args.summary, write=not args.dry_run, date=date)
        if not args.no_verify:
            stage_verify()
        if args.publish:
            if args.dry_run:
                raise ReleaseError("--publish cannot be combined with --dry-run")
            stage_publish(args.version, summary=args.summary or f"release {args.version}")
        else:
            print("\nPrepare + verify complete. Re-run with --publish to roll out.")
    except ReleaseError as exc:
        print(f"release failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
