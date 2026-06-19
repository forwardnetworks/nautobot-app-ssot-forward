from __future__ import annotations

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list[tuple[str, str]] = []

    operations = [
        migrations.CreateModel(
            name="ForwardConnectionProfile",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("name", models.CharField(max_length=128, unique=True)),
                ("base_url", models.URLField(default="https://fwd.app")),
                ("username", models.CharField(blank=True, default="", max_length=255)),
                ("password", models.CharField(blank=True, default="", max_length=255)),
                ("network_id", models.CharField(blank=True, default="", max_length=64)),
                (
                    "snapshot_id",
                    models.CharField(
                        blank=True,
                        default="latestProcessed",
                        max_length=128,
                    ),
                ),
                ("enabled_models", models.JSONField(blank=True, default=list)),
                ("query_contract_version", models.CharField(default="v1", max_length=32)),
                (
                    "default_location_type_name",
                    models.CharField(blank=True, default="", max_length=128),
                ),
                (
                    "default_location_status_name",
                    models.CharField(blank=True, default="", max_length=128),
                ),
                (
                    "default_device_role_name",
                    models.CharField(blank=True, default="", max_length=128),
                ),
                (
                    "default_device_status_name",
                    models.CharField(blank=True, default="", max_length=128),
                ),
                ("delete_policy", models.CharField(default="ignore", max_length=32)),
                ("is_default", models.BooleanField(default=False)),
                ("last_run_at", models.CharField(blank=True, default="", max_length=128)),
                ("last_failure", models.TextField(blank=True, default="")),
                (
                    "last_support_bundle",
                    models.CharField(blank=True, default="", max_length=255),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
    ]
