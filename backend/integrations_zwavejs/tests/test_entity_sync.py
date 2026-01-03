from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from alarm.models import Entity
from integrations_zwavejs.entity_sync import sync_entities_from_zwavejs


class _FakeZwavejs:
    def __init__(self, *, home_id: int | None = 123, nodes: list[dict] | None = None):
        self._home_id = home_id
        self._nodes = nodes or [{"id": 2, "name": "Front Door"}]

    def controller_get_state(self, *, timeout_seconds: float = 5.0) -> dict:
        return {"state": {"nodes": self._nodes}}

    def get_home_id(self) -> int | None:
        return self._home_id

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0) -> list[dict]:
        raise NotImplementedError

    def node_get_value_metadata(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0) -> dict:
        raise NotImplementedError

    def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0) -> object:
        raise NotImplementedError


class ZwavejsEntitySyncTests(TestCase):
    def test_sync_supports_dict_shaped_nodes(self):
        class _OkDictNodes(_FakeZwavejs):
            def __init__(self):
                super().__init__(nodes={"2": {"name": "Front Door"}})

            def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0) -> list[dict]:
                return [{"commandClass": 113, "endpoint": 0, "property": "Home Security", "propertyKey": 0}]

            def node_get_value_metadata(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0) -> dict:
                return {"label": "Contact"}

            def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0) -> object:
                return True

        now = timezone.now()
        result = sync_entities_from_zwavejs(zwavejs=_OkDictNodes(), now=now)

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["candidate_node_count"], 1)

    def test_sync_returns_warning_when_value_ids_fetch_fails(self):
        class _FailsValueIds(_FakeZwavejs):
            def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0) -> list[dict]:
                raise RuntimeError("unknown command")

        now = timezone.now()
        result = sync_entities_from_zwavejs(zwavejs=_FailsValueIds(), now=now)

        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["candidate_node_count"], 1)
        self.assertEqual(result["nodes_value_ids_failed"], 1)
        self.assertTrue(result["warnings"])

    def test_sync_imports_entities_from_value_ids(self):
        class _Ok(_FakeZwavejs):
            def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0) -> list[dict]:
                return [{"commandClass": 113, "endpoint": 0, "property": "Home Security", "propertyKey": 0}]

            def node_get_value_metadata(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0) -> dict:
                return {"label": "Contact"}

            def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0) -> object:
                return True

        now = timezone.now()
        result = sync_entities_from_zwavejs(zwavejs=_Ok(), now=now)

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["warnings"], [])
        self.assertTrue(Entity.objects.filter(source="zwavejs").exists())
