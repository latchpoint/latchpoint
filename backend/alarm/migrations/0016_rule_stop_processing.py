from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alarm", "0015_remove_credential_settings_entries"),
    ]

    operations = [
        migrations.AddField(
            model_name="rule",
            name="stop_processing",
            field=models.BooleanField(default=False),
        ),
    ]
