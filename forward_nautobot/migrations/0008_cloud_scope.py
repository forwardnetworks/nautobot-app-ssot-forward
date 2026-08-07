from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("forward_nautobot", "0007_device_scope_filters")]

    operations = [
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="sync_mode",
            field=models.CharField(default="network", max_length=16),
        ),
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="cloud_types",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="forwardconnectionprofile",
            name="cloud_account_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
