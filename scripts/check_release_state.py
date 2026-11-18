#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

INIT_PY = Path("forward_nautobot/__init__.py")
README = Path("README.md")
_CURRENT_ROW = re.compile(r"^\|\s*`(\d+\.\d+\.\d+)`\s*\|.*\|\s*Current\s*\|\s*$", re.MULTILINE)


def readme_current_versions(text: str) -> list[str]:
    """Versions the README compatibility table marks as ``Current``."""
    return _CURRENT_ROW.findall(text)


def read_init_version() -> str | None:
    """Return the `version = "..."` declared on ForwardNautobotConfig, or None."""
    text = INIT_PY.read_text(encoding="utf-8")
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1).strip() if match else None


def main() -> int:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = str(pyproject["tool"]["poetry"]["version"]).strip()

    # Gate 1: pyproject and the AppConfig version must not drift apart.
    init_version = read_init_version()
    if init_version is None:
        print(
            "Release state check failed: could not read version from forward_nautobot/__init__.py."
        )
        return 1
    if init_version != version:
        print(
            "Release state check failed: version drift — "
            f"pyproject.toml={version!r} but forward_nautobot/__init__.py={init_version!r}."
        )
        return 1

    # Gate 1b: the README's compatibility table must name this release as current.
    # Nothing else touches that row, so without this check it silently goes stale.
    current = readme_current_versions(README.read_text(encoding="utf-8"))
    if current != [version]:
        print(
            "Release state check failed: the README compatibility table marks "
            f"{current or 'no version'} as Current but the package version is {version!r}."
        )
        return 1

    # Gate 2: when running on a release tag, it must match the package version.
    ref_type = str(os.environ.get("GITHUB_REF_TYPE") or "").strip()
    ref_name = str(os.environ.get("GITHUB_REF_NAME") or "").strip()
    if ref_type == "tag" and ref_name not in {version, f"v{version}"}:
        print(
            f"Release state check failed: tag {ref_name!r} does not match package version {version!r}."
        )
        return 1

    print(
        f"Release state check passed (version {version!r} consistent across pyproject + AppConfig)"
        + (f"; tag {ref_name!r}." if ref_type == "tag" else "; not running on a release tag.")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
