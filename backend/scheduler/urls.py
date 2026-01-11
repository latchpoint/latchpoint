from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("status/", views.SchedulerStatusView.as_view(), name="scheduler-status"),
    path(
        "tasks/<str:task_name>/runs/",
        views.SchedulerTaskRunsView.as_view(),
        name="scheduler-task-runs",
    ),
]

