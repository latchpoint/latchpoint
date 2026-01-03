# Integrations Split (Completed)

This work is complete. The canonical decisions and current architecture are documented in:

- `docs/adr/0014-alarm-core-and-integrations-decomposition.md`
- `docs/adr/0015-integration-signals-contract.md`

Resulting Django apps:

- `backend/alarm` (core domain + API + websocket)
- `backend/transports_mqtt` (MQTT transport)
- `backend/integrations_home_assistant` (Home Assistant integration + HA-over-MQTT alarm entity)
- `backend/integrations_zwavejs` (Z-Wave JS integration)

