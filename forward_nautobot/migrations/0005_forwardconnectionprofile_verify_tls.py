from __future__ import annotations

from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("forward_nautobot", "0004_forwardconnectionprofile_last_query_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="verify_tls",
            field=models.BooleanField(default=True),
        ),
    ]
