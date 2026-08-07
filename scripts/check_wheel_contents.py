#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import tomllib
from email.parser import BytesParser
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
    "forward_nautobot/migrations/0007_device_scope_filters.py",
    "forward_nautobot/integrations/forward/dry_run.py",
    "forward_nautobot/integrations/forward/query_publishing.py",
    "forward_nautobot/integrations/forward/write_executor.py",
    "forward_nautobot/integrations/forward/write_path.py",
    "forward_nautobot/management/commands/forward_dry_run.py",
    "forward_nautobot/management/commands/forward_publish_queries.py",
    "forward_nautobot/integrations/forward/queries/README.md",
) + tuple(f"forward_nautobot/integrations/forward/queries/{name}" for name in QUERY_FILENAMES)


def _package_version() -> str:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["tool"]["poetry"]["version"]).strip()


def _resolve_wheel_path(value: str | None, *, version: str) -> Path:
    if value:
        return Path(value)
    dist_dir = Path("dist")
    wheels = sorted(
        dist_dir.glob(f"nautobot_app_ssot_forward-{version}-*.whl"),
        key=lambda path: path.stat().st_mtime,
    )
    if not wheels:
        raise FileNotFoundError(f"No nautobot-app-ssot-forward {version} wheel found in dist/.")
    return wheels[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check bundled wheel contents.")
    parser.add_argument("--wheel-path", default="", help="Path to a built wheel.")
    args = parser.parse_args(argv)

    version = _package_version()
    wheel_path = _resolve_wheel_path(args.wheel_path or None, version=version)
    with ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())
        metadata_names = sorted(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = (
            BytesParser().parsebytes(wheel.read(metadata_names[0])) if metadata_names else None
        )

    failures = [
        f"missing wheel file: {expected}" for expected in EXPECTED_FILES if expected not in names
    ]
    if metadata is None:
        failures.append("missing wheel distribution METADATA")
    elif metadata.get("Version") != version:
        failures.append(
            f"wheel metadata version {metadata.get('Version')!r} does not match {version!r}"
        )

    if failures:
        print(f"Wheel contents check failed for {wheel_path}:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Wheel contents check passed for {wheel_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
