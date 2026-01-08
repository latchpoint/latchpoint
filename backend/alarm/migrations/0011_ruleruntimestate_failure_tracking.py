"""Add failure tracking fields to RuleRuntimeState for ADR 0057 circuit breaker."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alarm", "0010_move_home_assistant_mqtt_alarm_entity_status"),
    ]

    operations = [
        # Add new status choice (handled by model change, no migration needed for TextChoices)

        # Add failure tracking fields
        migrations.AddField(
            model_name="ruleruntimestate",
            name="consecutive_failures",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="ruleruntimestate",
            name="last_failure_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ruleruntimestate",
            name="next_allowed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="ruleruntimestate",
            name="error_suspended",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="ruleruntimestate",
            name="last_error",
            field=models.TextField(blank=True),
        ),
    ]
