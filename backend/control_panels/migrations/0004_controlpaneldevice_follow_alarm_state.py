from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("control_panels", "0003_rename_control_pan_integra_8bd633_idx_control_pan_integra_6a0c65_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="controlpaneldevice",
            name="follow_alarm_state",
            field=models.BooleanField(default=True),
        ),
    ]
