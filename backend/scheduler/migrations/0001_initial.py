from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SchedulerTaskHealth",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task_name", models.CharField(max_length=128)),
                ("instance_id", models.CharField(max_length=128)),
                ("enabled", models.BooleanField(default=True)),
                ("schedule_type", models.CharField(blank=True, max_length=32)),
                ("schedule_payload", models.JSONField(blank=True, default=dict)),
                ("max_runtime_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("next_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_started_at", models.DateTimeField(blank=True, null=True)),
                ("last_finished_at", models.DateTimeField(blank=True, null=True)),
                ("last_duration_seconds", models.FloatField(blank=True, null=True)),
                ("is_running", models.BooleanField(default=False)),
                ("consecutive_failures", models.PositiveIntegerField(default=0)),
                ("last_error_message", models.TextField(blank=True)),
                ("last_heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["task_name", "instance_id"], name="scheduler_ta_task_na_99a1a7_idx"),
                    models.Index(fields=["instance_id"], name="scheduler_ta_instance_4d110a_idx"),
                    models.Index(fields=["task_name"], name="scheduler_ta_task_na_e9b1bf_idx"),
                    models.Index(fields=["is_running"], name="scheduler_ta_is_runn_05c2a6_idx"),
                    models.Index(fields=["consecutive_failures"], name="scheduler_ta_consec_51ed4b_idx"),
                    models.Index(fields=["updated_at"], name="scheduler_ta_updated_8a1056_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="SchedulerTaskRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task_name", models.CharField(max_length=128)),
                ("instance_id", models.CharField(max_length=128)),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("running", "Running"), ("success", "Success"), ("failure", "Failure"), ("skipped", "Skipped"), ("timeout", "Timeout")], max_length=16)),
                ("duration_seconds", models.FloatField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                ("error_traceback", models.TextField(blank=True)),
                ("consecutive_failures_at_start", models.PositiveIntegerField(default=0)),
                ("thread_name", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["task_name", "-started_at"], name="scheduler_ta_task_na_4f5f1e_idx"),
                    models.Index(fields=["instance_id", "-started_at"], name="scheduler_ta_instance_312a86_idx"),
                    models.Index(fields=["status", "-started_at"], name="scheduler_ta_status_6aa9ca_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="schedulertaskhealth",
            constraint=models.UniqueConstraint(fields=("task_name", "instance_id"), name="scheduler_task_health_unique_task_instance"),
        ),
    ]

