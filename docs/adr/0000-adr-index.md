# ADR 0000: ADR Index

This document tracks all Architecture Decision Records (ADRs) and their implementation status.

## Status Legend

| Status | Description |
|--------|-------------|
| **Implemented** | Decision has been fully implemented |
| **Partially Implemented** | Core functionality implemented, some features pending |
| **Proposed** | Decision documented but not yet implemented |
| **Superseded** | Replaced by a newer ADR |

---

## ADR Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-core-models-state-machine.md) | Core Models and State Machine (MVP) | **Implemented** |
| [0002](0002-code-auth-and-rate-limiting.md) | Code Auth and Rate Limiting (MVP) | **Implemented** |
| [0003](0003-separate-entity-import-from-alarm-configuration.md) | Separate Entity Import from Alarm Configuration | **Implemented** |
| [0004](0004-rules-engine-entity-registry-remove-zones.md) | Rules Engine + Entity Registry; Remove Zones | **Implemented** |
| [0005](0005-thin-views-and-use-cases.md) | Thin Views and Use-Case Layer | **Implemented** |
| [0006](0006-rules-engine-internal-modules.md) | Rules Engine Internal Decomposition (SOLID) | **Implemented** |
| [0007](0007-home-assistant-gateway-and-allowlist.md) | Home Assistant Gateway Abstraction | **Implemented** |
| [0008](0008-alarm-state-machine-decomposition.md) | Alarm State Machine Decomposition + Services Facade | **Implemented** |
| [0009](0009-rules-engine-repository-boundary.md) | Rules Engine Repository Boundary (DIP) | **Implemented** |
| [0010](0010-disable-home-assistant-during-tests.md) | Disable Home Assistant During Tests by Default | **Implemented** |
| [0011](0011-session-cookie-auth.md) | Session Cookie Authentication for SPA | **Implemented** |
| [0012](0012-zwave-js-gateway-and-connection-manager.md) | Z-Wave JS Gateway + Connection Manager | **Implemented** |
| [0013](0013-mqtt-transport-and-integrations.md) | MQTT Transport Separate From HA/Zigbee2MQTT | Superseded by 0014 |
| [0014](0014-alarm-core-and-integrations-decomposition.md) | Alarm Core + Integrations Decomposition | **Implemented** |
| [0015](0015-integration-signals-contract.md) | Integration Signals Contract | **Implemented** |
| [0016](0016-settings-routed-tabs-per-tab-save.md) | Settings UI as Routed Tabs with Per-Tab Save | **Implemented** |
| [0017](0017-home-assistant-connection-settings-in-profile.md) | Home Assistant Connection Settings in Profile (Encrypted) | **Implemented** |
| [0018](0018-zigbee2mqtt-integration.md) | Zigbee2MQTT Integration (Device Sync + Event Ingest) | **Implemented** |
| [0019](0019-frigate-verification-and-person-thresholds.md) | Frigate MQTT Person Events as Rules Conditions | **Implemented** |
| [0020](0020-ring-keypad-v2-volume-control.md) | Ring Keypad v2 Volume Control | **Implemented** |
| [0021](0021-rules-engine-then-actions.md) | Rules Engine "THEN" Actions | **Implemented** |
| [0022](0022-sqlite-fallback-when-database-url-unset.md) | SQLite Fallback When DATABASE_URL Is Unset | **Implemented** |
| [0023](0023-event-cleanup-background-task.md) | Event Cleanup Background Task | **Implemented** |
| [0024](0024-in-process-task-scheduler.md) | In-Process Task Scheduler with Watchdog | **Implemented** |
| [0025](0025-standardized-api-response-format.md) | Standardized API Response Format | **Implemented** |
| [0026](0026-rule-action-log-cleanup-task.md) | Rule Action Log Cleanup Task | **Implemented** |
| [0027](0027-entity-state-sync-task.md) | Entity State Sync Task | **Implemented** |
| [0028](0028-integration-health-check-task.md) | Integration Health Check Task | Superseded by 0042 |
| [0029](0029-session-cleanup-task.md) | Session Cleanup Task | **Implemented** |
| [0030](0030-system-status-monitoring.md) | System Status Monitoring Architecture | Superseded by 0042 |
| [0031](0031-unified-docker-service.md) | Unified Docker Service for Frontend and Backend | **Implemented** |
| [0032](0032-frigate-event-json-viewer-and-cleanup.md) | Frigate Event JSON Viewer and Detection Cleanup Task | **Implemented** |
| [0033](0033-react-query-builder-for-rules-ui.md) | React Query Builder for Rules UI | **Implemented** |
| [0034](0034-notifications-as-rule-actions.md) | Home Assistant Notifications as Rule Actions | **Superseded** |
| [0035](0035-notification-types-configuration-reference.md) | Notification Providers with In-App Configuration | **Superseded** |
| [0036](0036-pushbullet-notification-provider.md) | Pushbullet Notification Provider Implementation | **Superseded** |
| [0037](0037-notifications-django-app-architecture.md) | Notifications Django App Architecture | **Superseded** |
| [0038](0038-centralized-encryption-logic.md) | Centralized Encryption Logic | **Implemented** |
| [0039](0039-unified-error-handling.md) | Unified Error Handling | **Implemented** |
| [0040](0040-zigbee2mqtt-hardening-and-control-semantics.md) | Zigbee2MQTT Hardening (Validation, Ingest, Control) | Superseded by 0049 |
| [0041](0041-django-6.1-upgrade-plan.md) | Django 6.x Upgrade Plan | **Implemented** |
| [0042](0042-integration-status-monitoring.md) | Integration Status Monitoring | **Implemented** |
| [0043](0043-notification-delivery-outbox-and-retries.md) | Notification Delivery Outbox + Retries | **Implemented** |
| [0044](0044-notifications-architecture-consolidation.md) | Notifications Architecture (Consolidated) | **Implemented** |
| [0045](0045-slack-notification-provider.md) | Slack Notification Provider | **Implemented** |
| [0046](0046-home-assistant-websocket-state-subscription.md) | Home Assistant WebSocket State Subscription | **Superseded** |
| [0047](0047-legacy-code-deprecation-and-removal.md) | Legacy Code Deprecation and Removal | **Implemented** |
| [0048](0048-zigbee2mqtt-mappings-user-friendly-editor.md) | User-Friendly Zigbee2MQTT Mappings Editor | Superseded by 0049 |
| [0049](0049-zigbee2mqtt-entity-first-rules-driven-automation.md) | Zigbee2MQTT Entity-First, Rules-Driven Automation | **Implemented** |
| [0050](0050-paginate-frigate-recent-detections-ui.md) | Paginate Recent Frigate Detections UI (Page Size 5) | **Implemented** |
| [0051](0051-standardize-integration-settings-ui-cards.md) | Standardize Integration Settings UI Cards | **Implemented** |
| [0052](0052-responsive-integration-overview-cards.md) | Responsive Integration Overview Cards | **Implemented** |
| [0053](0053-application-color-scheme.md) | Application Color Scheme | **Implemented** |
| [0054](0054-frontend-testing.md) | Frontend Testing Strategy | **Implemented** |
| [0055](0055-github-actions-ci-and-ghcr-image.md) | GitHub Actions CI + GHCR Image Publishing | **Implemented** |
| [0056](0056-door-codes-ui-simplification.md) | Door Codes UI Simplification | **Implemented** |
| [0057](0057-integration-entity-updates-trigger-rules.md) | Integration Entity Updates Trigger Rules (Efficiently) | **Implemented** |
| [0058](0058-home-assistant-realtime-entity-updates-via-websocket.md) | Home Assistant Realtime Entity Updates via WebSocket (Dispatcher-Based) | **Implemented** |
| [0059](0059-rule-triggering-accuracy-and-realtime-semantics.md) | Rule Triggering Accuracy and Realtime Semantics | **Implemented** |
| [0060](0060-evaluate-django-cron-library.md) | Evaluate django-cron Library vs Custom Scheduler | Superseded |
| [0061](0061-optimize-dispatcher-entity-state-snapshot-for-rule-evaluation.md) | Optimize Dispatcher Entity-State Snapshot for Faster Rule Evaluation | **Implemented** |
| [0062](0062-scheduler-resilience-improvements.md) | Scheduler Resilience Improvements | **Implemented** |
| [0063](0063-scheduler-status-ui-and-health-monitoring.md) | Scheduler Status UI and Health Monitoring | **Implemented** |
| [0064](0064-integration-gated-scheduler-tasks.md) | Integration-Gated Scheduler Tasks | **Implemented** |
| [0065](0065-rule-builder-when-time-ranges.md) | Rule Builder WHEN Time Ranges | **Implemented** |
| [0066](0066-retention-cleanup-notifications-and-door-code-events.md) | Retention Cleanup Tasks for Notifications and Door Code Events | **Implemented** |
| [0067](0067-backend-endpoint-test-coverage-gaps.md) | Backend Endpoint Test Coverage Gaps | **Proposed** |
| [0068](0068-zwavejs-lock-config-sync.md) | Z-Wave JS Lock Config Sync (Codes & Schedules) | **Implemented** |
| [0069](0069-lock-config-sync-operational-concerns.md) | Lock Config Sync — Operational, Security & UX Concerns | **Implemented** |
| [0070](0070-entity-state-debug-page.md) | Entity State Debug Page | **Implemented** |

---

## Summary

| Status | Count |
|--------|-------|
| **Implemented** | 57 |
| **Partially Implemented** | 1 |
| **Proposed** | 1 |
| **Superseded** | 11 |
| **Total** | 70 |

Note: **Superseded** includes entries marked as "Superseded by …" in the table above.

---

*Last updated: 2026-02-08* (Marked ADR 0047 as Implemented — all legacy removal targets completed)
