"""API endpoints for the PendingAction queue (ADR-0091).

GET  /api/alarm/pending-actions/?status=scheduled  — list
POST /api/alarm/pending-actions/<id>/cancel/       — manual cancel
"""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.models import PendingAction, PendingActionStatus
from alarm.rules.pending_actions import cancel_by_id
from alarm.serializers import PendingActionSerializer
from alarm.state_machine.errors import InvalidCodeError
from alarm.use_cases.alarm_actions import CodeRequired, InvalidCode, validate_user_code
from config.domain_exceptions import NotFoundError, ValidationError

_ALLOWED_STATUS_VALUES = {s.value for s in PendingActionStatus} | {"all"}


class PendingActionsListView(APIView):
    """List queued / recently-fired / cancelled actions.

    Query params:
      - ``status`` (optional): filter by status (default: ``scheduled``).
        Pass ``all`` to include every status.
      - ``limit`` (optional, default 100, max 500): page size.
    """

    def get(self, request):
        status_filter = request.query_params.get("status", PendingActionStatus.SCHEDULED.value)
        if status_filter not in _ALLOWED_STATUS_VALUES:
            raise ValidationError(f"Invalid status filter; allowed: {sorted(_ALLOWED_STATUS_VALUES)}.")
        try:
            limit = max(1, min(int(request.query_params.get("limit", 100)), 500))
        except (TypeError, ValueError):
            limit = 100

        qs = PendingAction.objects.select_related("rule", "actor_user").order_by("-fire_at", "-id")
        if status_filter != "all":
            qs = qs.filter(status=status_filter)
        rows = list(qs[:limit])
        return Response(PendingActionSerializer(rows, many=True).data)


class PendingActionCancelView(APIView):
    """Manually cancel a queued action.

    For ``alarm_trigger`` pending actions, cancellation is functionally
    equivalent to disarming the alarm — it prevents the trigger from firing.
    To match the disarm-requires-code security gate, a valid user code is
    required in the request body when the target action is ``alarm_trigger``.
    Other action types (e.g., ``send_notification``) do not require a code.
    """

    def post(self, request, pending_action_id: int):
        try:
            pa = PendingAction.objects.select_related("rule", "actor_user").get(id=pending_action_id)
        except PendingAction.DoesNotExist as exc:
            raise NotFoundError("Pending action not found.") from exc
        if pa.status != PendingActionStatus.SCHEDULED:
            raise NotFoundError("Pending action is already in a terminal state.")

        if (pa.action_payload or {}).get("type") == "alarm_trigger":
            raw_code = request.data.get("code") if isinstance(request.data, dict) else None
            if not raw_code:
                raise CodeRequired("Code is required to cancel an alarm_trigger pending action.")
            try:
                validate_user_code(user=request.user, raw_code=raw_code)
            except InvalidCodeError as exc:
                raise InvalidCode(str(exc) or "Invalid code.") from exc

        if not cancel_by_id(pending_action_id):
            raise NotFoundError("Pending action is already in a terminal state.")
        pa.refresh_from_db()
        return Response(PendingActionSerializer(pa).data)
