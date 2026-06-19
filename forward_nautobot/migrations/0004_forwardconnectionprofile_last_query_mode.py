from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("forward_nautobot", "0003_forwardconnectionprofile_last_query_reference"),
    ]

    operations = [
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="last_query_mode",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
