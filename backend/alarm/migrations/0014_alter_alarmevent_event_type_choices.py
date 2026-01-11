from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alarm", "0013_ruleruntimestate_when_edge_tracking"),
    ]

    operations = [
        migrations.AlterField(
            model_name="alarmevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("armed", "Armed"),
                    ("disarmed", "Disarmed"),
                    ("pending", "Pending"),
                    ("triggered", "Triggered"),
                    ("code_used", "Code used"),
                    ("sensor_triggered", "Sensor triggered"),
                    ("failed_code", "Failed code"),
                    ("state_changed", "State changed"),
                    ("integration_offline", "Integration offline"),
                    ("integration_recovered", "Integration recovered"),
                    ("scheduler_task_failed", "Scheduler task failed"),
                    ("scheduler_task_stuck", "Scheduler task stuck"),
                ],
                max_length=32,
            ),
        ),
    ]

