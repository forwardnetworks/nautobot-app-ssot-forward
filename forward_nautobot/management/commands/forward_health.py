"""Pre-flight health check for a Forward connection profile."""

from __future__ import annotations

import json
import os

from django.core.management.base import CommandError

from forward_nautobot.integrations.forward.client import ForwardClient
from forward_nautobot.integrations.forward.health import run_health_check
from forward_nautobot.integrations.forward.registry import DEFAULT_QUERY_DIRECTORY
from forward_nautobot.management.commands.forward_publish_queries import (
    Command as PublishCommand,
)
from forward_nautobot.models import ForwardConnectionProfile


class Command(PublishCommand):
    help = "Check that a profile can reach Forward, see its network and snapshot, and has queries."

    def add_arguments(self, parser):
        # Not the publish command's full set: --audit-only/--overwrite/--fail-on-gap
        # would be accepted and silently do nothing here.
        parser.add_argument("--profile", default="")
        parser.add_argument("--url", default=os.getenv("FORWARD_URL", "https://fwd.app"))
        parser.add_argument("--username", default=os.getenv("FORWARD_USERNAME", ""))
        parser.add_argument("--password", default=os.getenv("FORWARD_PASSWORD", ""))
        parser.add_argument("--network-id", default=os.getenv("FORWARD_NETWORK_ID", ""))
        parser.add_argument("--snapshot-id", default=os.getenv("FORWARD_SNAPSHOT_ID", ""))
        parser.add_argument("--directory", default=DEFAULT_QUERY_DIRECTORY)
        parser.add_argument("--fail-on-warn", action="store_true")

    def handle(self, *args, **options):
        settings = self._connection_settings(options)
        enabled: tuple[str, ...] = ()
        previous_snapshot_id = ""
        profile_name = str(options.get("profile") or "").strip()
        if profile_name:
            record = ForwardConnectionProfile.objects.get(name=profile_name).to_record()
            enabled = tuple(record.enabled_models)
            previous_snapshot_id = str(record.last_snapshot_id or "")
        with ForwardClient(settings) as client:
            report = run_health_check(
                client,
                network_id=settings.network_id,
                snapshot_id=settings.snapshot_id,
                enabled_models=enabled,
                directory=options.get("directory") or DEFAULT_QUERY_DIRECTORY,
                previous_snapshot_id=previous_snapshot_id,
            )
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] == "fail" or (options["fail_on_warn"] and report["status"] == "warn"):
            raise CommandError(f"Forward pre-flight health is {report['status']}.")
