import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("forward_nautobot", "0008_cloud_scope")]

    operations = [
        migrations.CreateModel(
            name="ForwardDeleteOverride",
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
                ("profile_name", models.CharField(blank=True, default="", max_length=128)),
                ("user", models.CharField(blank=True, default="", max_length=255)),
                ("reason", models.TextField(blank=True, default="")),
                ("snapshot_id", models.CharField(blank=True, default="", max_length=128)),
                ("overridden", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "profile",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="delete_overrides",
                        to="forward_nautobot.forwardconnectionprofile",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
