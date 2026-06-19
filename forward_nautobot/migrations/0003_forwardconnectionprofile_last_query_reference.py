from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("forward_nautobot", "0002_forwardconnectionprofile_last_snapshot_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="last_query_reference",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
