from __future__ import annotations

from django.db import transaction

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.gateways.zwavejs import default_zwavejs_gateway
from alarm.state_machine.settings import get_setting_json
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from config.domain_exceptions import ValidationError
from integrations_zwavejs.config import normalize_zwavejs_connection, prepare_runtime_zwavejs_connection
from locks.permissions import IsAdminRole
from locks.serializers import DismissedAssignmentSerializer, LockConfigSyncRequestSerializer
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_config_sync as lock_config_sync_uc

zwavejs_gateway = default_zwavejs_gateway


def _apply_zwavejs_settings() -> float:
    """Apply stored Z-Wave JS connection settings to the gateway; return connect timeout seconds."""
    profile = ensure_active_settings_profile()
    settings_obj = normalize_zwavejs_connection(get_setting_json(profile, "zwavejs_connection") or {})
    if not settings_obj.get("enabled"):
        raise ValidationError("Z-Wave JS is disabled.")
    if not settings_obj.get("ws_url"):
        raise ValidationError("Z-Wave JS ws_url is required.")

    zwavejs_gateway.apply_settings(settings_obj=prepare_runtime_zwavejs_connection(settings_obj))
    return float(settings_obj.get("connect_timeout_seconds") or 5)


class LockConfigSyncView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, lock_entity_id: str):
        """Sync user codes + supported schedules from a Z-Wave lock into DoorCodes (admin-only, requires re-auth)."""
        serializer = LockConfigSyncRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        dry_run = str(request.query_params.get("dry_run", "")).lower() in ("true", "1")

        door_codes_uc.assert_admin_reauth(user=request.user, reauth_password=payload.get("reauth_password"))
        target_user = door_codes_uc.resolve_create_target_user(
            actor_user=request.user,
            requested_user_id=str(payload["user_id"]),
        )

        timeout_seconds = _apply_zwavejs_settings()
        zwavejs_gateway.ensure_connected(timeout_seconds=timeout_seconds)

        if dry_run:
            # Execute the sync inside a savepoint that is always rolled back,
            # so we get a full preview without persisting any changes.
            with transaction.atomic():
                result = lock_config_sync_uc.sync_lock_config(
                    lock_entity_id=lock_entity_id,
                    target_user=target_user,
                    actor_user=request.user,
                    zwavejs=zwavejs_gateway,
                    dry_run=True,
                )
                # Force rollback of this savepoint.
                transaction.set_rollback(True)
            data = result.as_dict()
            data["dry_run"] = True
            return Response(data, status=status.HTTP_200_OK)

        result = lock_config_sync_uc.sync_lock_config(
            lock_entity_id=lock_entity_id,
            target_user=target_user,
            actor_user=request.user,
            zwavejs=zwavejs_gateway,
        )

        return Response(result.as_dict(), status=status.HTTP_200_OK)


class DismissedAssignmentsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request, lock_entity_id: str):
        """List sync-dismissed assignments for a lock."""
        assignments = door_codes_uc.list_dismissed_assignments(lock_entity_id=lock_entity_id)
        return Response(DismissedAssignmentSerializer(assignments, many=True).data, status=status.HTTP_200_OK)


class UndismissAssignmentView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, assignment_id: int):
        """Clear sync_dismissed on an assignment, re-enabling sync for that slot."""
        reauth_password = request.data.get("reauth_password")
        door_codes_uc.assert_admin_reauth(user=request.user, reauth_password=reauth_password)
        assignment = door_codes_uc.undismiss_assignment(assignment_id=assignment_id)
        return Response(DismissedAssignmentSerializer(assignment).data, status=status.HTTP_200_OK)
