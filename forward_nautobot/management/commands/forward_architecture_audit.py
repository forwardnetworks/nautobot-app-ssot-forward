"""Print the slice-registry consistency report."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from forward_nautobot.integrations.forward.architecture_audit import build_architecture_audit


class Command(BaseCommand):
    help = "Cross-check the model slice registry against the packaged queries and contracts."

    def add_arguments(self, parser):
        parser.add_argument("--fail-on-warn", action="store_true")

    def handle(self, *args, **options):
        report = build_architecture_audit()
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] == "fail" or (options["fail_on_warn"] and report["status"] == "warn"):
            raise CommandError(f"Architecture audit is {report['status']}.")
