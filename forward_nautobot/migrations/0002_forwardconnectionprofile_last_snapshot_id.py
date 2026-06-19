from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("forward_nautobot", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="last_snapshot_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
    ]
