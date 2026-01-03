from __future__ import annotations

from django.urls import re_path

from .consumers import AlarmConsumer

websocket_urlpatterns = [
    re_path(r"^ws/alarm/$", AlarmConsumer.as_asgi()),
]

