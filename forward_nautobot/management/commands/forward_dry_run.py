"""Run a fixture-backed Forward dry run from the Nautobot CLI."""

from __future__ import annotations

import json
import argparse
from pathlib import Path

try:
    from django.core.management.base import BaseCommand
    from django.core.management.base import CommandParser
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    class _Stdout:
        def write(self, message: str) -> None:
            print(message)

    class BaseCommand:  # type: ignore[too-many-ancestors]
        """Fallback command base when Django is not installed."""

        help = ""

        def __init__(self) -> None:
            self.stdout = _Stdout()

    CommandParser = argparse.ArgumentParser  # type: ignore[assignment]

from ...integrations.forward.dry_run import run_fixture_dry_run


class Command(BaseCommand):
    help = "Run a Forward dry run against a saved fixture payload."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "fixture",
            type=Path,
            help="Path to a JSON fixture mapping model names to Forward rows.",
        )
        parser.add_argument(
            "--models",
            default="",
            help="Comma-separated model names to include. Default: all models in the fixture.",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=3,
            help="Number of sample rows to include in the support bundle.",
        )
        parser.add_argument(
            "--sharing-profile",
            choices=("external", "internal"),
            default="external",
            help="Redaction profile for the shared support bundle output.",
        )
        parser.add_argument(
            "--output",
            type=Path,
            default=None,
            help="Optional path for the full JSON replay artifact.",
        )
        parser.add_argument(
            "--shared-output",
            type=Path,
            default=None,
            help="Optional path for the redacted shareable support artifact.",
        )

    def handle(self, *args, **options):
        fixture = options["fixture"]
        model_names = tuple(
            part.strip()
            for part in str(options.get("models") or "").split(",")
            if part.strip()
        )
        result = run_fixture_dry_run(
            fixture,
            model_names=model_names or None,
            sample_size=options["sample_size"],
            sharing_profile=options["sharing_profile"],
        )
        payload = json.dumps(result.as_dict(), indent=2, sort_keys=True)
        self.stdout.write(payload)
        output_path = options.get("output")
        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(payload + "\n", encoding="utf-8")
        shared_output_path = options.get("shared_output")
        if shared_output_path is not None:
            shared_output_path = Path(shared_output_path)
            shared_output_path.parent.mkdir(parents=True, exist_ok=True)
            shared_payload = json.dumps(
                result.support_bundle_shared, indent=2, sort_keys=True
            )
            shared_output_path.write_text(shared_payload + "\n", encoding="utf-8")
