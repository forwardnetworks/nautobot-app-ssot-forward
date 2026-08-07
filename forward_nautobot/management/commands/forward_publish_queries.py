"""Publish and verify the plugin's bundled NQE contracts."""

from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError

from forward_nautobot.integrations.forward.client import ForwardClient
from forward_nautobot.integrations.forward.models import ForwardConnectionSettings
from forward_nautobot.integrations.forward.query_publishing import (
    audit_bundled_queries,
    publish_bundled_queries,
)
from forward_nautobot.integrations.forward.registry import DEFAULT_QUERY_DIRECTORY
from forward_nautobot.models import ForwardConnectionProfile


class Command(BaseCommand):
    help = "Idempotently publish bundled Forward NQEs and prove committed source parity."

    def add_arguments(self, parser):
        parser.add_argument("--profile", default="")
        parser.add_argument("--url", default=os.getenv("FORWARD_URL", "https://fwd.app"))
        parser.add_argument("--username", default=os.getenv("FORWARD_USERNAME", ""))
        parser.add_argument("--password", default=os.getenv("FORWARD_PASSWORD", ""))
        parser.add_argument("--network-id", default=os.getenv("FORWARD_NETWORK_ID", ""))
        parser.add_argument("--snapshot-id", default=os.getenv("FORWARD_SNAPSHOT_ID", ""))
        parser.add_argument("--directory", default=DEFAULT_QUERY_DIRECTORY)
        parser.add_argument("--audit-only", action="store_true")
        parser.add_argument("--overwrite", action="store_true")
        parser.add_argument("--fail-on-gap", action="store_true")

    def handle(self, *args, **options):
        settings = self._connection_settings(options)
        with ForwardClient(settings) as client:
            if options["audit_only"]:
                report = audit_bundled_queries(client, directory=options["directory"])
            else:
                report = publish_bundled_queries(
                    client,
                    directory=options["directory"],
                    overwrite=bool(options["overwrite"]),
                )
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if options["fail_on_gap"] and report.get("status") != "pass":
            raise CommandError("Bundled Forward NQE publication/source audit has gaps.")

    @staticmethod
    def _connection_settings(options) -> ForwardConnectionSettings:
        profile_name = str(options.get("profile") or "").strip()
        if profile_name:
            try:
                profile = ForwardConnectionProfile.objects.get(name=profile_name)
            except ForwardConnectionProfile.DoesNotExist as exc:
                raise CommandError(f"Forward profile `{profile_name}` was not found.") from exc
            return profile.to_connection_settings()

        username = str(options.get("username") or "").strip()
        password = str(options.get("password") or "")
        if not username or not password:
            raise CommandError(
                "Provide --profile or both --username/--password (or FORWARD_USERNAME/FORWARD_PASSWORD)."
            )
        return ForwardConnectionSettings(
            base_url=str(options.get("url") or "https://fwd.app").strip(),
            username=username,
            password=password,
            network_id=str(options.get("network_id") or "").strip(),
            snapshot_id=str(options.get("snapshot_id") or "").strip() or "latestProcessed",
        )
