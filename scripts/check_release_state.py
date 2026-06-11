#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import tomllib


def main() -> int:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = str(pyproject["tool"]["poetry"]["version"]).strip()
    ref_type = str(os.environ.get("GITHUB_REF_TYPE") or "").strip()
    ref_name = str(os.environ.get("GITHUB_REF_NAME") or "").strip()

    if ref_type == "tag" and ref_name not in {version, f"v{version}"}:
        print(
            f"Release state check failed: tag {ref_name!r} does not match package version {version!r}."
        )
        return 1

    print(
        "Release state check passed"
        + (f" for tag {ref_name!r}." if ref_type == "tag" else " (not running on a release tag).")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
