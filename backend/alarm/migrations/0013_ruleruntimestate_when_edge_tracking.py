from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alarm", "0012_alter_alarmevent_event_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="ruleruntimestate",
            name="last_when_matched",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ruleruntimestate",
            name="last_when_transition_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

