"""Seed a Forward profile and point to the packaged fixture data."""

from __future__ import annotations

import json

try:
    from django.core.management.base import BaseCommand
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path

    class _Stdout:
        def write(self, message: str) -> None:
            print(message)

    class BaseCommand:  # type: ignore[too-many-ancestors]
        """Fallback command base when Django is not installed."""

        help = ""

        def __init__(self) -> None:
            self.stdout = _Stdout()


from ...fixture_support import fixture_path, fixture_payload, seed_profile


class Command(BaseCommand):
    help = "Seed the canonical Forward profile."

    def handle(self, *args, **options):
        profile = seed_profile()
        result = {
            "profile_name": profile.name if profile is not None else "replay",
            "is_default": bool(profile.is_default) if profile is not None else True,
            "write_ready": bool(profile.write_ready) if profile is not None else True,
            "enabled_models": list(profile.enabled_models) if profile is not None else [],
            "fixture_path": fixture_path(),
            "fixture_models": sorted(fixture_payload().keys()),
        }
        self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
