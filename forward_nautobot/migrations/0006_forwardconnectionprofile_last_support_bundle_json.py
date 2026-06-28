from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("forward_nautobot", "0005_forwardconnectionprofile_verify_tls"),
    ]

    operations = [
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="last_support_bundle_json",
            field=models.TextField(blank=True, default=""),
        ),
    ]
