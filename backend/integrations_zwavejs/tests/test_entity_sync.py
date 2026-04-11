from __future__ import annotations

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from alarm.models import Entity
from integrations_zwavejs.entity_sync import sync_entities_from_zwavejs
from integrations_zwavejs.manager import infer_entity_domain


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

    def test_sync_creates_single_lock_entity_per_node(self):
        """A lock node with CC 98 + multiple CC 99 values should produce exactly one domain='lock' entity."""

        class _LockNode(_FakeZwavejs):
            def node_get_defined_value_ids(self, *, node_id, timeout_seconds=5.0):
                return [
                    {"commandClass": 98, "endpoint": 0, "property": "currentMode", "propertyKey": "-"},
                    {"commandClass": 99, "endpoint": 0, "property": "userIdStatus", "propertyKey": 1},
                    {"commandClass": 99, "endpoint": 0, "property": "userCode", "propertyKey": 1},
                    {"commandClass": 99, "endpoint": 0, "property": "usersNumber", "propertyKey": "-"},
                ]

            def node_get_value_metadata(self, *, node_id, value_id, timeout_seconds=5.0):
                return {"label": str(value_id.get("property", ""))}

            def node_get_value(self, *, node_id, value_id, timeout_seconds=5.0):
                return 0

        result = sync_entities_from_zwavejs(zwavejs=_LockNode(), now=timezone.now())
        self.assertEqual(result["imported"], 4)

        lock_entities = Entity.objects.filter(source="zwavejs", domain="lock")
        self.assertEqual(lock_entities.count(), 1)

        lock_entity = lock_entities.first()
        self.assertIn("98", lock_entity.entity_id)
        self.assertIn("currentMode", lock_entity.entity_id)

        sensor_entities = Entity.objects.filter(source="zwavejs", domain="sensor")
        self.assertEqual(sensor_entities.count(), 3)

    def test_lock_entity_has_zwavejs_node_id(self):
        """The representative lock entity must carry zwavejs.node_id for lock config sync resolution."""

        class _LockNode(_FakeZwavejs):
            def node_get_defined_value_ids(self, *, node_id, timeout_seconds=5.0):
                return [{"commandClass": 98, "endpoint": 0, "property": "currentMode", "propertyKey": "-"}]

            def node_get_value_metadata(self, *, node_id, value_id, timeout_seconds=5.0):
                return {"label": "Current Mode"}

            def node_get_value(self, *, node_id, value_id, timeout_seconds=5.0):
                return 0

        sync_entities_from_zwavejs(zwavejs=_LockNode(), now=timezone.now())
        entity = Entity.objects.get(source="zwavejs", domain="lock")
        self.assertEqual(entity.attributes["zwavejs"]["node_id"], 2)

    def test_lock_entity_uses_node_name(self):
        """The representative lock entity should use just the node name, not 'node_name - label'."""

        class _LockNode(_FakeZwavejs):
            def node_get_defined_value_ids(self, *, node_id, timeout_seconds=5.0):
                return [{"commandClass": 98, "endpoint": 0, "property": "currentMode", "propertyKey": "-"}]

            def node_get_value_metadata(self, *, node_id, value_id, timeout_seconds=5.0):
                return {"label": "Current Mode"}

            def node_get_value(self, *, node_id, value_id, timeout_seconds=5.0):
                return 0

        sync_entities_from_zwavejs(zwavejs=_LockNode(), now=timezone.now())
        entity = Entity.objects.get(source="zwavejs", domain="lock")
        self.assertEqual(entity.name, "Front Door")

    def test_non_lock_node_unaffected(self):
        """CC 113 (Notification) entities should still get binary_sensor/sensor domains."""

        class _SensorNode(_FakeZwavejs):
            def node_get_defined_value_ids(self, *, node_id, timeout_seconds=5.0):
                return [{"commandClass": 113, "endpoint": 0, "property": "Home Security", "propertyKey": 0}]

            def node_get_value_metadata(self, *, node_id, value_id, timeout_seconds=5.0):
                return {"label": "Contact"}

            def node_get_value(self, *, node_id, value_id, timeout_seconds=5.0):
                return True

        sync_entities_from_zwavejs(zwavejs=_SensorNode(), now=timezone.now())
        self.assertEqual(Entity.objects.filter(source="zwavejs", domain="lock").count(), 0)
        self.assertTrue(Entity.objects.filter(source="zwavejs", domain="binary_sensor").exists())

    def test_lock_fallback_to_cc99_when_no_cc98(self):
        """When a lock node exposes only CC 99 (no CC 98), the representative should be CC 99."""

        class _Cc99Only(_FakeZwavejs):
            def node_get_defined_value_ids(self, *, node_id, timeout_seconds=5.0):
                return [
                    {"commandClass": 99, "endpoint": 0, "property": "userIdStatus", "propertyKey": 1},
                    {"commandClass": 99, "endpoint": 0, "property": "userCode", "propertyKey": 1},
                ]

            def node_get_value_metadata(self, *, node_id, value_id, timeout_seconds=5.0):
                return {"label": str(value_id.get("property", ""))}

            def node_get_value(self, *, node_id, value_id, timeout_seconds=5.0):
                return 0

        sync_entities_from_zwavejs(zwavejs=_Cc99Only(), now=timezone.now())
        lock_entities = Entity.objects.filter(source="zwavejs", domain="lock")
        self.assertEqual(lock_entities.count(), 1)
        sensor_entities = Entity.objects.filter(source="zwavejs", domain="sensor")
        self.assertEqual(sensor_entities.count(), 1)


class InferEntityDomainTests(SimpleTestCase):
    def test_returns_lock_for_cc_98(self):
        self.assertEqual(infer_entity_domain(value=1, command_class=98), "lock")

    def test_returns_lock_for_cc_99(self):
        self.assertEqual(infer_entity_domain(value="1234", command_class=99), "lock")

    def test_returns_lock_for_cc_76(self):
        self.assertEqual(infer_entity_domain(value={}, command_class=76), "lock")

    def test_returns_sensor_for_non_lock_cc(self):
        self.assertEqual(infer_entity_domain(value=42, command_class=113), "sensor")

    def test_returns_binary_sensor_for_bool_without_lock_cc(self):
        self.assertEqual(infer_entity_domain(value=True, command_class=113), "binary_sensor")

    def test_returns_sensor_when_no_command_class(self):
        self.assertEqual(infer_entity_domain(value=42), "sensor")
