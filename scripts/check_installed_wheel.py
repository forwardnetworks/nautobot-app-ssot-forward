#!/usr/bin/env python3
"""Run source-absent installed-wheel acceptance on supported Nautobot versions."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "development/docker-compose.wheel.yml"
SUPPORTED_NAUTOBOT_VERSIONS = ("3.1.8", "3.2.2")


def _default_wheel_path() -> Path:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(pyproject["tool"]["poetry"]["version"]).strip()
    return REPO_ROOT / "dist" / f"nautobot_app_ssot_forward-{version}-py3-none-any.whl"


def _run(argv: list[str], *, env: dict[str, str]) -> None:
    subprocess.run(argv, cwd=REPO_ROOT, env=env, check=True)


def run_acceptance(*, wheel_path: Path, versions: tuple[str, ...], keep: bool = False) -> None:
    wheel_path = wheel_path.resolve()
    if not wheel_path.is_file():
        raise FileNotFoundError(f"Installed-wheel acceptance requires: {wheel_path}")
    with tempfile.TemporaryDirectory(prefix="forward-wheel-acceptance-") as context_value:
        context = Path(context_value)
        shutil.copy2(wheel_path, context / wheel_path.name)
        shutil.copy2(REPO_ROOT / "development/Dockerfile.wheel", context / "Dockerfile")
        shutil.copy2(REPO_ROOT / "nautobot_config.py", context / "nautobot_config.py")
        shutil.copy2(
            REPO_ROOT / "development/installed_wheel_probe.py",
            context / "installed_wheel_probe.py",
        )

        for nautobot_version in versions:
            version_token = nautobot_version.replace(".", "")
            project = f"fwdnbwheel{version_token}"
            env = os.environ.copy()
            env.update(
                {
                    "NAUTOBOT_VERSION": nautobot_version,
                    "PYTHON_VERSION": "3.12",
                    "WHEEL_CONTEXT": str(context),
                }
            )
            compose = [
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                str(COMPOSE_FILE),
            ]
            print(f"\n=== installed wheel: Nautobot {nautobot_version} ===", flush=True)
            try:
                _run(
                    [
                        *compose,
                        "up",
                        "-d",
                        "--build",
                        "--wait",
                        "--wait-timeout",
                        "600",
                    ],
                    env=env,
                )
                _run(
                    [
                        *compose,
                        "exec",
                        "-T",
                        "nautobot",
                        "python",
                        "/opt/forward-wheel-acceptance/installed_wheel_probe.py",
                    ],
                    env=env,
                )
            finally:
                if not keep:
                    _run([*compose, "down", "-v", "--remove-orphans"], env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-path", type=Path, default=_default_wheel_path())
    parser.add_argument(
        "--versions",
        nargs="+",
        default=list(SUPPORTED_NAUTOBOT_VERSIONS),
        help="supported Nautobot versions to validate",
    )
    parser.add_argument("--keep", action="store_true", help="leave disposable stacks running")
    args = parser.parse_args(argv)
    run_acceptance(
        wheel_path=args.wheel_path,
        versions=tuple(args.versions),
        keep=bool(args.keep),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
