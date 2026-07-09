"""Emit Forward Field Integration metrics in Prometheus text-exposition format.

Read-only; safe to run on a schedule (node_exporter textfile collector or a scrape
sidecar):

    nautobot-server forward_metrics > /var/lib/node_exporter/forward.prom
"""

from __future__ import annotations

from datetime import UTC, datetime

from django.core.management.base import BaseCommand

from forward_nautobot.integrations.forward.metrics import render_prometheus
from forward_nautobot.models import ForwardConnectionProfile


class Command(BaseCommand):
    help = (
        "Emit forward_nautobot metrics in Prometheus text-exposition format on "
        "stdout. Read-only; safe to run on a schedule."
    )

    def handle(self, *args, **options):
        records = [profile.to_record() for profile in ForwardConnectionProfile.objects.all()]

        ssot_sync_count = None
        try:
            from nautobot_ssot.models import Sync

            ssot_sync_count = Sync.objects.count()
        except Exception:  # pragma: no cover - ssot optional / absent
            ssot_sync_count = None

        text = render_prometheus(
            records,
            now_epoch=datetime.now(UTC).timestamp(),
            ssot_sync_count=ssot_sync_count,
        )
        self.stdout.write(text)
