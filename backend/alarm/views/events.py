from __future__ import annotations

import uuid

from django.core.paginator import Paginator
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.models import AlarmEvent, AlarmEventType
from alarm.serializers import AlarmEventSerializer


class AlarmEventsView(APIView):
    def get(self, request):
        """List alarm events with simple filtering and pagination."""
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
        ordering = request.query_params.get("ordering", "-timestamp")
        if ordering not in {"timestamp", "-timestamp"}:
            ordering = "-timestamp"

        event_type = request.query_params.get("event_type") or None
        start_date = request.query_params.get("start_date") or None
        end_date = request.query_params.get("end_date") or None
        user_id = request.query_params.get("user_id") or None
        sensor_id = request.query_params.get("sensor_id") or None
        code_id = request.query_params.get("code_id") or None

        page = max(1, page)
        page_size = min(max(1, page_size), 200)

        queryset = AlarmEvent.objects.all()

        if event_type in set(AlarmEventType.values):
            queryset = queryset.filter(event_type=event_type)

        def parse_dt(value: str) -> timezone.datetime | None:
            """Parse ISO timestamp strings into timezone-aware datetimes."""
            parsed = parse_datetime(value)
            if not parsed:
                return None
            if timezone.is_naive(parsed):
                return timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed

        if start_date:
            parsed = parse_dt(start_date)
            if parsed:
                queryset = queryset.filter(timestamp__gte=parsed)

        if end_date:
            parsed = parse_dt(end_date)
            if parsed:
                queryset = queryset.filter(timestamp__lte=parsed)

        if user_id:
            try:
                queryset = queryset.filter(user_id=uuid.UUID(user_id))
            except ValueError:
                pass

        if sensor_id:
            try:
                queryset = queryset.filter(sensor_id=int(sensor_id))
            except (TypeError, ValueError):
                pass

        if code_id:
            try:
                queryset = queryset.filter(code_id=int(code_id))
            except (TypeError, ValueError):
                pass

        queryset = queryset.order_by(ordering)
        paginator = Paginator(queryset, page_size)
        page_obj = paginator.get_page(page)

        return Response(
            {
                "data": AlarmEventSerializer(page_obj.object_list, many=True).data,
                "meta": {
                    "page": page_obj.number,
                    "page_size": page_size,
                    "total": paginator.count,
                    "total_pages": paginator.num_pages,
                    "has_next": page_obj.has_next(),
                    "has_previous": page_obj.has_previous(),
                    "timestamp": timezone.now().isoformat(),
                },
            }
        )
