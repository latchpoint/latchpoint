from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alarm", "0016_rule_stop_processing"),
    ]

    operations = [
        migrations.AddField(
            model_name="rule",
            name="stop_group",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Optional named group for stop_processing scoping. "
                    "stop_processing only blocks lower-priority rules sharing this group."
                ),
                max_length=64,
            ),
        ),
    ]
