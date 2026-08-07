from __future__ import annotations

from django.db import migrations, models


def set_v2_contract(apps, schema_editor):
    del schema_editor
    profile_model = apps.get_model("forward_nautobot", "ForwardConnectionProfile")
    profile_model.objects.filter(query_contract_version="v1").update(query_contract_version="v2")


class Migration(migrations.Migration):
    dependencies = [
        ("forward_nautobot", "0006_forwardconnectionprofile_last_support_bundle_json"),
    ]

    operations = [
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="device_vendors",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="device_types",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="device_models",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="last_scope_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AlterField(
            model_name="forwardconnectionprofile",
            name="query_contract_version",
            field=models.CharField(default="v2", max_length=32),
        ),
        migrations.RunPython(set_v2_contract, migrations.RunPython.noop),
    ]
