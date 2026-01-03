# ADR 0037: Notifications Django App Architecture

## Status
**Superseded by ADR 0044**

## Context

ADR 0035 established that notification providers should be configured in-app rather than through Home Assistant. ADR 0036 detailed the Pushbullet implementation. Before implementing, we need to decide on the Django app structure.

### Current State
- Notifications currently flow through `ha_call_service` action in `alarm/rules/`
- Home Assistant integration lives in `integrations_home_assistant/`
- No dedicated notification infrastructure exists

### Questions to Answer
1. Should notifications be a separate Django app or part of `alarm/`?
2. How should Home Assistant notifications integrate with the new system?
3. What's the relationship between `notifications/` and existing integrations?

## Decision

### 1. Create Separate `notifications/` Django App

Notifications will be a standalone Django app, following the project's existing pattern of separating integrations.

```
backend/
├── alarm/                        # Core alarm logic, rules engine
├── integrations_home_assistant/  # HA connection, entity sync, services
├── integrations_zigbee2mqtt/     # Z2M connection, device sync
└── notifications/                # NEW: All notification providers
```

### 2. Home Assistant as a Notification Handler

The `home_assistant` notification handler will be a **thin wrapper** around the existing HA gateway. This provides:
- Unified UX (all providers in one place)
- Single "Send Notification" action type
- No duplication of HA connection logic

```
notifications/handlers/home_assistant.py
         │
         │ imports
         ▼
integrations_home_assistant/api.py
         │
         │ calls
         ▼
    Home Assistant API
```

### 3. Clear Separation of Concerns

| App | Responsibility |
|-----|----------------|
| `alarm/` | Rules engine, action execution, alarm state |
| `integrations_home_assistant/` | HA connection, entity sync, generic service calls |
| `notifications/` | Notification providers, dispatcher, all handlers |

---

## App Structure

```
backend/notifications/
├── __init__.py
├── apps.py
├── models.py                 # NotificationProvider model
├── serializers.py            # DRF serializers
├── views.py                  # API views (CRUD, test, provider-specific)
├── urls.py                   # URL routing
├── admin.py                  # Django admin
├── dispatcher.py             # Routes notifications to handlers
├── encryption.py             # Config field encryption utilities
├── handlers/
│   ├── __init__.py           # Handler registry
│   ├── base.py               # Protocol/ABC definition
│   ├── pushbullet.py
│   ├── discord.py
│   ├── telegram.py
│   ├── pushover.py
│   ├── ntfy.py
│   ├── email_smtp.py
│   ├── twilio_sms.py
│   ├── twilio_call.py
│   ├── slack.py
│   ├── webhook.py
│   └── home_assistant.py     # Wraps HA gateway
├── migrations/
│   └── 0001_initial.py
└── tests/
    ├── __init__.py
    ├── test_models.py
    ├── test_dispatcher.py
    ├── test_views.py
    └── handlers/
        ├── test_pushbullet.py
        ├── test_discord.py
        └── ...
```

---

## Models

### NotificationProvider

```python
# notifications/models.py

import uuid
from django.db import models
from alarm.models import AlarmProfile

class NotificationProvider(models.Model):
    """A configured notification provider instance."""

    class ProviderType(models.TextChoices):
        PUSHBULLET = 'pushbullet', 'Pushbullet'
        DISCORD = 'discord', 'Discord'
        TELEGRAM = 'telegram', 'Telegram'
        PUSHOVER = 'pushover', 'Pushover'
        NTFY = 'ntfy', 'Ntfy'
        EMAIL = 'email', 'Email (SMTP)'
        TWILIO_SMS = 'twilio_sms', 'Twilio SMS'
        TWILIO_CALL = 'twilio_call', 'Twilio Voice Call'
        SLACK = 'slack', 'Slack'
        WEBHOOK = 'webhook', 'Webhook'
        HOME_ASSISTANT = 'home_assistant', 'Home Assistant'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        AlarmProfile,
        on_delete=models.CASCADE,
        related_name='notification_providers'
    )
    name = models.CharField(max_length=100, help_text="Display name")
    provider_type = models.CharField(max_length=50, choices=ProviderType.choices)
    config = models.JSONField(default=dict, help_text="Provider configuration (encrypted fields)")
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['profile', 'name']
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"
```

### NotificationLog (Optional)

```python
class NotificationLog(models.Model):
    """Audit log for sent notifications."""

    class Status(models.TextChoices):
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        PENDING = 'pending', 'Pending'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        NotificationProvider,
        on_delete=models.SET_NULL,
        null=True,
        related_name='logs'
    )
    provider_name = models.CharField(max_length=100)  # Denormalized for history
    provider_type = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=Status.choices)
    message_preview = models.CharField(max_length=200)  # Truncated message
    error_message = models.TextField(blank=True)
    rule_action_log = models.ForeignKey(
        'alarm.RuleActionLog',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
```

---

## Handler Architecture

### Base Protocol

```python
# notifications/handlers/base.py

from typing import Protocol
from dataclasses import dataclass

@dataclass
class NotificationResult:
    """Result of a notification send attempt."""
    success: bool
    message: str
    error_code: str | None = None
    provider_response: dict | None = None

    @classmethod
    def ok(cls, message: str = "Sent successfully", response: dict = None):
        return cls(success=True, message=message, provider_response=response)

    @classmethod
    def error(cls, message: str, code: str = "ERROR", response: dict = None):
        return cls(success=False, message=message, error_code=code, provider_response=response)


class NotificationHandler(Protocol):
    """Protocol for notification handlers."""

    # Provider type identifier
    provider_type: str

    # Fields that should be encrypted in config
    encrypted_fields: list[str]

    # JSON schema for config validation
    config_schema: dict

    def validate_config(self, config: dict) -> list[str]:
        """Validate provider configuration. Returns list of errors."""
        ...

    def send(
        self,
        config: dict,
        message: str,
        title: str | None = None,
        data: dict | None = None
    ) -> NotificationResult:
        """Send a notification. Returns result."""
        ...

    def test(self, config: dict) -> NotificationResult:
        """Send a test notification."""
        ...
```

### Handler Registry

```python
# notifications/handlers/__init__.py

from .pushbullet import PushbulletHandler
from .discord import DiscordHandler
from .telegram import TelegramHandler
from .pushover import PushoverHandler
from .ntfy import NtfyHandler
from .email_smtp import EmailHandler
from .twilio_sms import TwilioSMSHandler
from .twilio_call import TwilioCallHandler
from .slack import SlackHandler
from .webhook import WebhookHandler
from .home_assistant import HomeAssistantHandler

HANDLERS = {
    'pushbullet': PushbulletHandler,
    'discord': DiscordHandler,
    'telegram': TelegramHandler,
    'pushover': PushoverHandler,
    'ntfy': NtfyHandler,
    'email': EmailHandler,
    'twilio_sms': TwilioSMSHandler,
    'twilio_call': TwilioCallHandler,
    'slack': SlackHandler,
    'webhook': WebhookHandler,
    'home_assistant': HomeAssistantHandler,
}

def get_handler(provider_type: str) -> NotificationHandler:
    """Get handler instance for provider type."""
    handler_class = HANDLERS.get(provider_type)
    if not handler_class:
        raise ValueError(f"Unknown provider type: {provider_type}")
    return handler_class()
```

### Home Assistant Handler

```python
# notifications/handlers/home_assistant.py

from integrations_home_assistant.api import get_home_assistant_gateway
from .base import NotificationHandler, NotificationResult

class HomeAssistantHandler:
    """
    Notification handler that wraps Home Assistant notify services.

    This handler delegates to the existing HA gateway, providing a unified
    interface while reusing HA connection infrastructure.
    """

    provider_type = 'home_assistant'
    encrypted_fields = []  # HA credentials managed by integrations_home_assistant

    config_schema = {
        "type": "object",
        "required": ["service"],
        "properties": {
            "service": {
                "type": "string",
                "pattern": r"^notify\..+$",
                "description": "HA notify service (e.g., notify.mobile_app_iphone)"
            }
        }
    }

    def validate_config(self, config: dict) -> list[str]:
        errors = []
        service = config.get("service", "")

        if not service:
            errors.append("Service is required")
        elif not service.startswith("notify."):
            errors.append("Service must start with 'notify.'")

        return errors

    def send(
        self,
        config: dict,
        message: str,
        title: str | None = None,
        data: dict | None = None
    ) -> NotificationResult:
        """Send notification via Home Assistant notify service."""
        try:
            gateway = get_home_assistant_gateway()
            if not gateway:
                return NotificationResult.error(
                    "Home Assistant not connected",
                    code="HA_NOT_CONNECTED"
                )

            service = config["service"]
            service_data = {"message": message}

            if title:
                service_data["title"] = title
            if data:
                service_data["data"] = data

            # Call HA service (notify.xxx -> domain=notify, service=xxx)
            result = gateway.call_service(service, service_data=service_data)

            if result.get("success", True):  # HA returns empty on success
                return NotificationResult.ok(
                    f"Sent via {service}",
                    response=result
                )
            else:
                return NotificationResult.error(
                    result.get("error", "Unknown error"),
                    code="HA_SERVICE_ERROR"
                )

        except Exception as e:
            return NotificationResult.error(str(e), code="HA_ERROR")

    def test(self, config: dict) -> NotificationResult:
        """Send test notification."""
        return self.send(
            config,
            message="Test notification from alarm system",
            title="Test"
        )

    @staticmethod
    def list_available_services() -> list[dict]:
        """List available notify services from Home Assistant."""
        try:
            gateway = get_home_assistant_gateway()
            if not gateway:
                return []
            return gateway.list_notify_services()
        except Exception:
            return []
```

---

## Dispatcher

```python
# notifications/dispatcher.py

from .models import NotificationProvider
from .handlers import get_handler
from .handlers.base import NotificationResult
from .encryption import decrypt_config

class NotificationDispatcher:
    """
    Central dispatcher for sending notifications.

    Resolves provider by ID, decrypts config, and routes to appropriate handler.
    """

    def send(
        self,
        provider_id: str,
        message: str,
        title: str | None = None,
        data: dict | None = None
    ) -> NotificationResult:
        """Send notification to a configured provider."""
        try:
            provider = NotificationProvider.objects.get(id=provider_id)
        except NotificationProvider.DoesNotExist:
            return NotificationResult.error(
                f"Provider not found: {provider_id}",
                code="PROVIDER_NOT_FOUND"
            )

        if not provider.is_enabled:
            return NotificationResult.error(
                f"Provider is disabled: {provider.name}",
                code="PROVIDER_DISABLED"
            )

        handler = get_handler(provider.provider_type)
        config = decrypt_config(provider.config, handler.encrypted_fields)

        return handler.send(config, message, title, data)

    def send_to_provider(
        self,
        provider: NotificationProvider,
        message: str,
        title: str | None = None,
        data: dict | None = None
    ) -> NotificationResult:
        """Send notification using provider instance."""
        handler = get_handler(provider.provider_type)
        config = decrypt_config(provider.config, handler.encrypted_fields)
        return handler.send(config, message, title, data)

    def test_provider(self, provider: NotificationProvider) -> NotificationResult:
        """Send test notification to provider."""
        handler = get_handler(provider.provider_type)
        config = decrypt_config(provider.config, handler.encrypted_fields)
        return handler.test(config)
```

---

## Integration with Rules Engine

### New Action Type

```python
# alarm/rules/action_schemas.py

ACTION_TYPES = {
    "alarm_trigger",
    "alarm_disarm",
    "alarm_arm",
    "ha_call_service",      # Keep for backward compat
    "zwavejs_set_value",
    "send_notification",    # NEW
}

SEND_NOTIFICATION_SCHEMA = {
    "type": "object",
    "required": ["type", "provider_id", "message"],
    "properties": {
        "type": {"const": "send_notification"},
        "provider_id": {"type": "string", "format": "uuid"},
        "message": {"type": "string", "minLength": 1},
        "title": {"type": "string"},
        "data": {"type": "object"}
    }
}
```

### Action Executor

```python
# alarm/rules/action_executor.py

from notifications.dispatcher import NotificationDispatcher

class ActionExecutor:
    def __init__(self):
        self.notification_dispatcher = NotificationDispatcher()

    def execute(self, action: dict, context: dict) -> ActionResult:
        action_type = action["type"]

        if action_type == "send_notification":
            return self._execute_send_notification(action, context)
        # ... other action types

    def _execute_send_notification(self, action: dict, context: dict) -> ActionResult:
        result = self.notification_dispatcher.send(
            provider_id=action["provider_id"],
            message=action["message"],
            title=action.get("title"),
            data=action.get("data")
        )

        return ActionResult(
            success=result.success,
            message=result.message,
            details={"provider_response": result.provider_response}
        )
```

---

## API Endpoints

```python
# notifications/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # Provider CRUD
    path('providers/', views.ProviderListCreateView.as_view()),
    path('providers/<uuid:pk>/', views.ProviderDetailView.as_view()),
    path('providers/<uuid:pk>/test/', views.TestProviderView.as_view()),

    # Provider types metadata
    path('provider-types/', views.ProviderTypesView.as_view()),

    # Provider-specific endpoints
    path('providers/pushbullet/devices/', views.PushbulletDevicesView.as_view()),
    path('providers/pushbullet/validate-token/', views.PushbulletValidateTokenView.as_view()),
    path('providers/home-assistant/services/', views.HomeAssistantServicesView.as_view()),

    # Logs (optional)
    path('logs/', views.NotificationLogListView.as_view()),
]

# Main urls.py
urlpatterns = [
    ...
    path('api/notifications/', include('notifications.urls')),
]
```

---

## Configuration Encryption

```python
# notifications/encryption.py

from cryptography.fernet import Fernet
from django.conf import settings

def get_fernet() -> Fernet:
    """Get Fernet instance using Django secret key."""
    # Same approach as integrations_home_assistant
    key = settings.ENCRYPTION_KEY  # Or derive from SECRET_KEY
    return Fernet(key)

def encrypt_config(config: dict, encrypted_fields: list[str]) -> dict:
    """Encrypt sensitive fields in config."""
    fernet = get_fernet()
    result = config.copy()

    for field in encrypted_fields:
        if field in result and result[field]:
            value = result[field]
            if isinstance(value, str):
                result[field] = fernet.encrypt(value.encode()).decode()

    return result

def decrypt_config(config: dict, encrypted_fields: list[str]) -> dict:
    """Decrypt sensitive fields in config."""
    fernet = get_fernet()
    result = config.copy()

    for field in encrypted_fields:
        if field in result and result[field]:
            value = result[field]
            if isinstance(value, str):
                try:
                    result[field] = fernet.decrypt(value.encode()).decode()
                except Exception:
                    pass  # Field may not be encrypted (e.g., during creation)

    return result
```

---

## Frontend Integration

### API Hooks

```typescript
// frontend/src/features/notifications/api.ts

export const notificationKeys = {
  providers: ['notification-providers'] as const,
  provider: (id: string) => ['notification-providers', id] as const,
  providerTypes: ['notification-provider-types'] as const,
}

export function useNotificationProviders() {
  return useQuery({
    queryKey: notificationKeys.providers,
    queryFn: () => api.get('/notifications/providers/').then(r => r.data)
  })
}

export function useCreateProvider() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: CreateProviderData) =>
      api.post('/notifications/providers/', data),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: notificationKeys.providers })
  })
}

export function useTestProvider() {
  return useMutation({
    mutationFn: (providerId: string) =>
      api.post(`/notifications/providers/${providerId}/test/`)
  })
}
```

### Rule Builder Integration

```typescript
// frontend/src/features/rules/queryBuilder/ActionsEditor.tsx

const ACTION_TYPES = [
  { value: 'alarm_trigger', label: 'Trigger Alarm' },
  { value: 'alarm_disarm', label: 'Disarm Alarm' },
  { value: 'alarm_arm', label: 'Arm Alarm' },
  { value: 'send_notification', label: 'Send Notification' },  // NEW
  { value: 'ha_call_service', label: 'HA Call Service' },       // Keep for power users
  { value: 'zwavejs_set_value', label: 'Z-Wave Set Value' },
]

// When action type is 'send_notification', show:
// - Provider dropdown (from useNotificationProviders)
// - Message field
// - Title field
// - Provider-specific advanced options
```

---

## Migration Path

### From `ha_call_service` Notify Actions

```python
# notifications/management/commands/migrate_notify_actions.py

class Command(BaseCommand):
    help = 'Migrate ha_call_service notify actions to send_notification'

    def handle(self, *args, **options):
        for rule in Rule.objects.all():
            updated = False
            actions = rule.then_actions

            for action in actions:
                if (action.get('type') == 'ha_call_service' and
                    action.get('action', '').startswith('notify.')):

                    # Create HA provider if not exists
                    provider, _ = NotificationProvider.objects.get_or_create(
                        profile=rule.profile,
                        name=f"HA: {action['action']}",
                        defaults={
                            'provider_type': 'home_assistant',
                            'config': {'service': action['action']}
                        }
                    )

                    # Convert action
                    action['type'] = 'send_notification'
                    action['provider_id'] = str(provider.id)
                    action['message'] = action.get('data', {}).get('message', '')
                    action['title'] = action.get('data', {}).get('title')

                    # Clean up old fields
                    action.pop('action', None)
                    action.pop('data', None)

                    updated = True

            if updated:
                rule.then_actions = actions
                rule.save()
                self.stdout.write(f"Updated rule: {rule.name}")
```

---

## Alternatives Considered

### 1. Keep Notifications in `alarm/`
**Rejected**: Would bloat the core app with 10+ handler files. Violates single responsibility.

### 2. Separate App per Provider
**Rejected**: Overkill. Would create 11+ tiny apps. Hard to share common code.

### 3. Use Third-Party Library (Apprise)
**Considered**: Apprise supports 80+ services out of the box.
- **Pros**: Less code to maintain, more services
- **Cons**: Additional dependency, less control over UX, may not fit our config model
- **Decision**: Start with custom handlers, consider Apprise if maintenance becomes burdensome

### 4. Keep HA Notifications Separate
**Rejected**: Would create two notification systems. Inconsistent UX in rule builder.

---

## Consequences

### Positive
- Clean separation of concerns
- Unified notification interface for rule builder
- Scalable to many providers
- Testable in isolation
- Follows existing project patterns

### Negative
- More files/directories to maintain
- Handler per provider requires ongoing maintenance
- Must keep `ha_call_service` for backward compatibility

### Neutral
- Additional Django app to configure in `INSTALLED_APPS`
- New database migration for `NotificationProvider` model

---

## Implementation Plan

### Phase 1: Foundation
- [x] Create `notifications/` Django app skeleton
- [x] Add `NotificationProvider` model and migrations
- [x] Implement base handler protocol
- [x] Implement dispatcher
- [x] Add encryption utilities

### Phase 2: First Handlers
- [x] Implement `PushbulletHandler` (ADR 0036)
- [x] Implement `HomeAssistantHandler`
- [x] Implement `DiscordHandler`
- [x] Create API endpoints (CRUD, test)
- [x] Implement `WebhookHandler`

### Phase 3: Frontend
- [x] Create Settings > Notification Providers page
- [x] Add provider forms for each type
- [x] Update rule builder for `send_notification` action

### Phase 4: Migration
- [ ] Create migration command for existing notify rules
- [ ] Test migration with sample data
- [ ] Document upgrade path

---

## References

- [ADR 0035: Notification Providers with In-App Configuration](0035-notification-types-configuration-reference.md)
- [ADR 0036: Pushbullet Notification Provider](0036-pushbullet-notification-provider.md)
- [ADR 0017: Home Assistant Connection Settings (Encrypted)](0017-home-assistant-connection-settings-in-profile.md)
- [ADR 0021: Rules Engine THEN Actions](0021-rules-engine-then-actions.md)
