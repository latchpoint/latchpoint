from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.domain_exceptions import ServiceUnavailableError
from alarm.gateways.home_assistant import (
    HomeAssistantGateway,
    default_home_assistant_gateway,
)
from alarm.models import Entity
from alarm.serializers import EntitySerializer
from alarm.use_cases.entity_sync import sync_entities_from_home_assistant

ha_gateway: HomeAssistantGateway = default_home_assistant_gateway
logger = logging.getLogger(__name__)


class EntitiesView(APIView):
    def get(self, request):
        """List entities from the local entity registry."""
        queryset = Entity.objects.all().order_by("entity_id")
        return Response(EntitySerializer(queryset, many=True).data, status=status.HTTP_200_OK)


class EntitySyncView(APIView):
    def post(self, request):
        """Sync entities from Home Assistant into the local entity registry."""
        ha_gateway.ensure_available()
        try:
            items = ha_gateway.list_entities()
        except Exception as exc:
            logger.exception("Failed to fetch Home Assistant entities for sync")
            raise ServiceUnavailableError("Failed to fetch Home Assistant entities.") from exc
        result = sync_entities_from_home_assistant(items=items)
        return Response(result, status=status.HTTP_200_OK)
