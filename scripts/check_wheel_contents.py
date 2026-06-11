#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forward_nautobot.integrations.forward.queries import QUERY_FILENAMES


EXPECTED_FILES = (
    "forward_nautobot/forms.py",
    "forward_nautobot/models.py",
    "forward_nautobot/views.py",
    "forward_nautobot/migrations/__init__.py",
    "forward_nautobot/migrations/0001_initial.py",
    "forward_nautobot/integrations/forward/dry_run.py",
    "forward_nautobot/integrations/forward/write_executor.py",
    "forward_nautobot/integrations/forward/write_path.py",
    "forward_nautobot/management/commands/forward_dry_run.py",
    "forward_nautobot/integrations/forward/queries/README.md",
) + tuple(f"forward_nautobot/integrations/forward/queries/{name}" for name in QUERY_FILENAMES)


def _resolve_wheel_path(value: str | None) -> Path:
    if value:
        return Path(value)
    dist_dir = Path("dist")
    wheels = sorted(dist_dir.glob("*.whl"), key=lambda path: path.stat().st_mtime)
    if not wheels:
        raise FileNotFoundError("No wheel found in dist/.")
    return wheels[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check bundled wheel contents.")
    parser.add_argument("--wheel-path", default="", help="Path to a built wheel.")
    args = parser.parse_args(argv)

    wheel_path = _resolve_wheel_path(args.wheel_path or None)
    with ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    failures = [
        f"missing wheel file: {expected}"
        for expected in EXPECTED_FILES
        if expected not in names
    ]

    if failures:
        print(f"Wheel contents check failed for {wheel_path}:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Wheel contents check passed for {wheel_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
