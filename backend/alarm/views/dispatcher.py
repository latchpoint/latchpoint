"""Dispatcher API views for ADR 0057."""

from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.models import RuleRuntimeState


class DispatcherStatusView(APIView):
    """GET /api/alarm/dispatcher/status - Return dispatcher health metrics."""

    def get(self, request):
        """Return dispatcher status and statistics."""
        from alarm.dispatcher import get_dispatcher_status

        return Response(get_dispatcher_status(), status=status.HTTP_200_OK)


class SuspendedRulesView(APIView):
    """GET /api/alarm/dispatcher/suspended-rules - List error-suspended rules."""

    def get(self, request):
        """Return list of rules currently suspended due to errors."""
        suspended = RuleRuntimeState.objects.filter(
            error_suspended=True
        ).select_related("rule")

        data = []
        for runtime in suspended:
            data.append({
                "rule_id": runtime.rule_id,
                "rule_name": runtime.rule.name if runtime.rule else None,
                "node_id": runtime.node_id,
                "consecutive_failures": runtime.consecutive_failures,
                "last_failure_at": runtime.last_failure_at.isoformat() if runtime.last_failure_at else None,
                "last_error": runtime.last_error,
                "next_allowed_at": runtime.next_allowed_at.isoformat() if runtime.next_allowed_at else None,
            })

        return Response(data, status=status.HTTP_200_OK)

    def delete(self, request):
        """Clear suspension for all rules or a specific rule."""
        rule_id = request.query_params.get("rule_id")

        from alarm.dispatcher.failure_handler import clear_suspension

        if rule_id:
            try:
                runtime = RuleRuntimeState.objects.get(
                    rule_id=int(rule_id),
                    error_suspended=True,
                )
                clear_suspension(runtime=runtime)
                return Response({"cleared": 1}, status=status.HTTP_200_OK)
            except (ValueError, RuleRuntimeState.DoesNotExist):
                return Response(
                    {"error": "Rule not found or not suspended"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # Clear all suspended rules
        suspended = RuleRuntimeState.objects.filter(error_suspended=True)
        count = suspended.count()
        for runtime in suspended:
            clear_suspension(runtime=runtime)

        return Response({"cleared": count}, status=status.HTTP_200_OK)


class DispatcherConfigView(APIView):
    """GET/PATCH /api/alarm/dispatcher/config - View or update dispatcher config."""

    def get(self, request):
        """Return current dispatcher configuration."""
        from alarm.dispatcher.config import get_dispatcher_config

        config = get_dispatcher_config()
        return Response({
            "enabled": True,  # Always enabled (ADR 0057)
            "debounce_ms": config.debounce_ms,
            "batch_size_limit": config.batch_size_limit,
            "rate_limit_per_sec": config.rate_limit_per_sec,
            "rate_limit_burst": config.rate_limit_burst,
            "worker_concurrency": config.worker_concurrency,
            "queue_max_depth": config.queue_max_depth,
        }, status=status.HTTP_200_OK)
