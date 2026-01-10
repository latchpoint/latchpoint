from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.models import Rule
from alarm.rules.action_schemas import get_action_schemas
from alarm.serializers import RuleSerializer, RuleUpsertSerializer
from alarm.use_cases import rules as rules_uc
from config.view_utils import ObjectPermissionMixin


class RulesView(APIView):
    def get(self, request):
        """List rules, optionally filtering by kind/enabled."""
        queryset = rules_uc.list_rules(
            kind=request.query_params.get("kind"),
            enabled=request.query_params.get("enabled"),
        )
        return Response(RuleSerializer(queryset, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        """Create a rule from the provided definition."""
        serializer = RuleUpsertSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        rule = serializer.save(created_by=request.user)
        return Response(RuleSerializer(rule).data, status=status.HTTP_201_CREATED)


class RuleDetailView(ObjectPermissionMixin, APIView):
    def get(self, request, rule_id: int):
        """Return a single rule (including referenced entities)."""
        rule = self.get_object_or_404(
            request,
            queryset=Rule.objects.all().prefetch_related("entity_refs__entity"),
            pk=rule_id,
        )
        return Response(RuleSerializer(rule).data, status=status.HTTP_200_OK)

    def patch(self, request, rule_id: int):
        """Partially update a rule."""
        rule = self.get_object_or_404(
            request,
            queryset=Rule.objects.all().prefetch_related("entity_refs__entity"),
            pk=rule_id,
        )
        serializer = RuleUpsertSerializer(rule, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        rule = serializer.save()
        return Response(RuleSerializer(rule).data, status=status.HTTP_200_OK)

    def delete(self, request, rule_id: int):
        """Delete a rule."""
        rule = self.get_object_or_404(
            request,
            queryset=Rule.objects.all().prefetch_related("entity_refs__entity"),
            pk=rule_id,
        )
        rule.delete()
        # Ensure dispatcher sees the updated dependency index immediately (ADR 0057).
        try:
            from alarm.dispatcher import invalidate_entity_rule_cache

            invalidate_entity_rule_cache()
        except Exception:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class RuleRunView(APIView):
    def post(self, request):
        """Run all enabled rules immediately."""
        result = rules_uc.run_rules(actor_user=request.user)
        return Response(result.as_dict(), status=status.HTTP_200_OK)


class RuleSimulateView(APIView):
    def post(self, request):
        """Simulate rules with an injected entity-state map (no side effects)."""
        input_data = rules_uc.parse_simulate_input(request.data)
        result = rules_uc.simulate_rules(input_data=input_data)
        return Response(result, status=status.HTTP_200_OK)


class SupportedActionsView(APIView):
    """
    GET /api/rules/supported-actions/

    Returns the list of supported action types for the rules engine THEN clause.
    Non-admin users only see non-admin actions.
    Admin users see all actions including ha_call_service and zwavejs_set_value.
    """

    def get(self, request):
        """Return rule action schemas, filtering out admin-only actions for non-admin users."""
        user = request.user
        is_admin = getattr(user, "is_staff", False)

        schemas = get_action_schemas()
        actions = []

        for action_type, schema in schemas.items():
            action_info = {
                "type": action_type,
                "admin_only": schema.get("admin_only", False),
                "schema": {k: v for k, v in schema.items() if k != "admin_only"},
            }

            # Only include admin-only actions for admin users
            if schema.get("admin_only") and not is_admin:
                continue

            actions.append(action_info)

        return Response({
            "schema_version": 1,
            "actions": actions,
        }, status=status.HTTP_200_OK)
