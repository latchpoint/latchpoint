from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from scheduler.models import SchedulerTaskHealth, SchedulerTaskRun, SchedulerTaskRunStatus
from scheduler.telemetry import get_instance_id
from scheduler.registry import register
from scheduler.schedules import Every


class SchedulerApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        self.client = APIClient()
        self.instance_id = get_instance_id()

    def test_status_requires_admin(self):
        url = reverse("scheduler-status")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

        self.client.force_authenticate(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_status_returns_health_rows(self):
        SchedulerTaskHealth.objects.create(
            task_name="example_task",
            instance_id=self.instance_id,
            enabled=True,
            schedule_type="Every",
            schedule_payload={"seconds": 60, "jitter": 0},
            next_run_at=timezone.now() + timedelta(seconds=60),
            last_finished_at=timezone.now(),
            last_duration_seconds=0.1,
        )

        self.client.force_authenticate(self.admin)
        url = reverse("scheduler-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["instance_id"], self.instance_id)
        self.assertIsInstance(body["data"]["tasks"], list)
        task_names = [t["task_name"] for t in body["data"]["tasks"]]
        self.assertIn("example_task", task_names)

    def test_status_includes_registered_tasks_even_if_never_observed(self):
        @register(
            "never_observed_task",
            schedule=Every(seconds=60),
            enabled=True,
            description="Example task registered for API tests.",
        )
        def never_observed_task() -> None:
            return None

        self.client.force_authenticate(self.admin)
        url = reverse("scheduler-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()["data"]
        task = next((t for t in body["tasks"] if t["task_name"] == "never_observed_task"), None)
        self.assertIsNotNone(task)
        self.assertEqual(task["observed"], False)
        self.assertEqual(task["status"], "never_ran")
        self.assertIsNotNone(task["next_run_at"])
        self.assertIsNotNone(task["description"])

    def test_task_runs_are_paginated_and_admin_only(self):
        started_at = timezone.now() - timedelta(seconds=5)
        finished_at = timezone.now()
        SchedulerTaskRun.objects.create(
            task_name="example_task",
            instance_id=self.instance_id,
            started_at=started_at,
            finished_at=finished_at,
            status=SchedulerTaskRunStatus.FAILURE,
            duration_seconds=5.0,
            error_message="boom",
            consecutive_failures_at_start=2,
            thread_name="task-example",
        )

        url = reverse("scheduler-task-runs", kwargs={"task_name": "example_task"})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

        self.client.force_authenticate(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        self.client.force_authenticate(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsInstance(body["data"], list)
        self.assertEqual(body["data"][0]["task_name"], "example_task")
        self.assertIn("meta", body)
