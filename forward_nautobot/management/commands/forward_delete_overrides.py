"""List applied delete overrides, newest first."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from forward_nautobot.models import ForwardDeleteOverride


class Command(BaseCommand):
    help = "Show who forced deletes past the governor, when, and why."

    def add_arguments(self, parser):
        parser.add_argument("--profile", default="")
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        rows = ForwardDeleteOverride.objects.all()
        profile = str(options.get("profile") or "").strip()
        if profile:
            rows = rows.filter(profile_name=profile)
        out = [
            {
                "at": row.created_at.isoformat(),
                "profile": row.profile_name,
                "user": row.user,
                "reason": row.reason,
                "snapshot_id": row.snapshot_id,
                "overridden": row.overridden,
            }
            for row in rows[: max(1, int(options["limit"]))]
        ]
        self.stdout.write(json.dumps(out, indent=2, sort_keys=True))
