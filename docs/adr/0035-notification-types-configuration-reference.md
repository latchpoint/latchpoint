# ADR 0035: Notification Providers with In-App Configuration

## Status
**Superseded by ADR 0044**

## Context
ADR 0034 established notifications via Home Assistant's `ha_call_service` action, requiring users to configure notification integrations in Home Assistant's `configuration.yaml`. This approach has limitations:

1. **Poor UX**: Users must edit YAML files and restart Home Assistant
2. **Split configuration**: Notification settings live outside the alarm system
3. **Limited visibility**: No way to see or manage credentials in our UI
4. **HA dependency**: Notifications fail if Home Assistant is unreachable

This ADR proposes that **all notification providers are configured directly in the alarm system UI**, with the backend sending notifications directly to each service.

## Decision

### New Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Alarm System                                 │
│  ┌──────────────────┐    ┌────────────────────────────────────┐ │
│  │  Settings UI     │───▶│  Notification Providers (encrypted)│ │
│  │  - Add provider  │    │  - Discord: {webhook_url}          │ │
│  │  - Test provider │    │  - Telegram: {bot_token, chat_id}  │ │
│  │  - Edit/Delete   │    │  - Email: {smtp_host, user, pass}  │ │
│  └──────────────────┘    └────────────────────────────────────┘ │
│                                       │                          │
│  ┌──────────────────┐                 ▼                          │
│  │  Rule Builder    │    ┌────────────────────────────────────┐ │
│  │  THEN:           │───▶│  Notification Dispatcher           │ │
│  │  - Send to Discord    │  - Sends directly to service APIs  │ │
│  │  - Send to Telegram   │  - No Home Assistant dependency    │ │
│  └──────────────────┘    └────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              ┌──────────┐   ┌──────────┐   ┌──────────┐
              │ Discord  │   │ Telegram │   │  Twilio  │
              │   API    │   │   API    │   │   API    │
              └──────────┘   └──────────┘   └──────────┘
```

### New Action Type

Replace `ha_call_service` with a dedicated `send_notification` action:

```json
{
  "type": "send_notification",
  "provider_id": "uuid-of-configured-provider",
  "message": "Alarm triggered!",
  "title": "Security Alert",
  "data": { ...provider-specific options... }
}
```

### New Settings Tab

Add **Settings > Notification Providers** with:
- List of configured providers with status indicators
- Add/Edit/Delete provider forms
- "Test" button to send test notification
- Credentials stored encrypted (like HA connection settings, ADR 0017)

---

## Notification Provider Specifications

### 1. Discord

**Provider Type**: `discord`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name (e.g., "Security Alerts Channel") |
| `webhook_url` | text | Yes | Discord webhook URL |

**How to get webhook URL**:
1. Right-click channel → Edit Channel → Integrations → Webhooks
2. Create webhook, copy URL

**Per-notification options** (in rule builder):
| Field | Type | Description |
|-------|------|-------------|
| `message` | text | Message content (required) |
| `title` | text | Embed title |
| `color` | color | Embed sidebar color |
| `image_url` | text | Image to embed |

**Backend API**: POST to webhook URL with JSON payload

---

### 2. Telegram

**Provider Type**: `telegram`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name |
| `bot_token` | password | Yes | Bot token from @BotFather |
| `chat_id` | text | Yes | Chat/Group/Channel ID |

**How to get credentials**:
1. Message @BotFather, create bot, copy token
2. Add bot to group/channel
3. Get chat ID via `https://api.telegram.org/bot<TOKEN>/getUpdates`

**Per-notification options**:
| Field | Type | Description |
|-------|------|-------------|
| `message` | text | Message text (required) |
| `parse_mode` | select | `html`, `markdown`, or `plain` |
| `disable_notification` | checkbox | Send silently |
| `photo_url` | text | Image URL to attach |

**Backend API**: Telegram Bot API (`sendMessage`, `sendPhoto`)

---

### 3. Pushover

**Provider Type**: `pushover`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name |
| `api_token` | password | Yes | Application API token |
| `user_key` | password | Yes | User/Group key |

**How to get credentials**:
1. Create account at pushover.net
2. Create application, copy API token
3. Copy user key from dashboard

**Per-notification options**:
| Field | Type | Description |
|-------|------|-------------|
| `message` | text | Notification body (required) |
| `title` | text | Notification title |
| `priority` | select | -2 (silent) to 2 (emergency) |
| `sound` | select | Alert sound name |
| `url` | text | Supplementary URL |

**Backend API**: `https://api.pushover.net/1/messages.json`

---

### 4. Pushbullet

**Provider Type**: `pushbullet`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name |
| `api_key` | password | Yes | Access token |
| `device_iden` | text | No | Specific device (optional) |

**How to get credentials**:
1. Go to pushbullet.com → Settings → Access Tokens
2. Create token, copy value

**Per-notification options**:
| Field | Type | Description |
|-------|------|-------------|
| `message` | text | Notification body (required) |
| `title` | text | Notification title |
| `url` | text | Link to open on click |

**Backend API**: `https://api.pushbullet.com/v2/pushes`

---

### 5. Ntfy

**Provider Type**: `ntfy`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name |
| `server_url` | text | Yes | Server URL (default: `https://ntfy.sh`) |
| `topic` | text | Yes | Topic name |
| `username` | text | No | Auth username (if protected) |
| `password` | password | No | Auth password |

**Per-notification options**:
| Field | Type | Description |
|-------|------|-------------|
| `message` | text | Notification body (required) |
| `title` | text | Notification title |
| `priority` | select | 1-5 (5 is urgent) |
| `tags` | text | Comma-separated emoji tags |
| `click_url` | text | URL to open on click |

**Backend API**: POST to `{server_url}/{topic}`

---

### 6. Email (SMTP)

**Provider Type**: `email`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name |
| `smtp_host` | text | Yes | SMTP server hostname |
| `smtp_port` | number | Yes | Port (587 for TLS, 465 for SSL) |
| `username` | text | Yes | SMTP username |
| `password` | password | Yes | SMTP password |
| `from_email` | email | Yes | Sender email address |
| `from_name` | text | No | Sender display name |
| `default_recipient` | email | Yes | Default recipient |
| `use_tls` | checkbox | Yes | Use STARTTLS |
| `use_ssl` | checkbox | Yes | Use SSL/TLS |

**Common SMTP Settings**:
| Provider | Host | Port | Notes |
|----------|------|------|-------|
| Gmail | smtp.gmail.com | 587 | Requires App Password |
| Outlook | smtp.office365.com | 587 | TLS |
| SendGrid | smtp.sendgrid.net | 587 | API key as password |
| Mailgun | smtp.mailgun.org | 587 | TLS |

**Per-notification options**:
| Field | Type | Description |
|-------|------|-------------|
| `message` | textarea | Email body (required) |
| `subject` | text | Email subject |
| `recipient` | email | Override default recipient |
| `html` | checkbox | Send as HTML |

**Backend**: Python `smtplib` or Django email backend

---

### 7. Twilio SMS

**Provider Type**: `twilio_sms`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name |
| `account_sid` | text | Yes | Twilio Account SID |
| `auth_token` | password | Yes | Twilio Auth Token |
| `from_number` | text | Yes | Twilio phone number (E.164) |
| `default_to_number` | text | Yes | Default recipient number |

**How to get credentials**:
1. Sign up at twilio.com
2. Copy Account SID and Auth Token from console
3. Buy or use trial phone number

**Per-notification options**:
| Field | Type | Description |
|-------|------|-------------|
| `message` | text | SMS body (required, 160 chars) |
| `to_number` | text | Override recipient |
| `media_url` | text | MMS image URL |

**Backend API**: Twilio REST API

---

### 8. Twilio Voice Call

**Provider Type**: `twilio_call`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name |
| `account_sid` | text | Yes | Twilio Account SID |
| `auth_token` | password | Yes | Twilio Auth Token |
| `from_number` | text | Yes | Twilio phone number |
| `default_to_number` | text | Yes | Default recipient number |

**Per-notification options**:
| Field | Type | Description |
|-------|------|-------------|
| `message` | text | Text-to-speech message (required) |
| `to_number` | text | Override recipient |
| `voice` | select | TTS voice (alice, man, woman) |
| `loop` | number | Times to repeat message |

**Backend API**: Twilio REST API with TwiML

---

### 9. Slack

**Provider Type**: `slack`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name |
| `webhook_url` | text | Yes | Slack incoming webhook URL |

**How to get webhook URL**:
1. Go to api.slack.com → Your Apps → Create App
2. Add "Incoming Webhooks" feature
3. Activate and copy webhook URL

**Per-notification options**:
| Field | Type | Description |
|-------|------|-------------|
| `message` | text | Message text (required) |
| `username` | text | Override bot username |
| `icon_emoji` | text | Override bot emoji |
| `channel` | text | Override channel |

**Backend API**: POST to webhook URL

---

### 10. Webhook (Generic)

**Provider Type**: `webhook`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name |
| `url` | text | Yes | Webhook endpoint URL |
| `method` | select | Yes | HTTP method (POST, PUT) |
| `content_type` | select | Yes | `application/json` or `application/x-www-form-urlencoded` |
| `headers` | key-value | No | Custom headers |
| `auth_type` | select | No | none, basic, bearer |
| `auth_value` | password | No | Auth credentials |

**Per-notification options**:
| Field | Type | Description |
|-------|------|-------------|
| `message` | text | Message (required) |
| `title` | text | Title |
| `custom_data` | json | Additional JSON data to merge |

**Backend**: Configurable HTTP request

---

### 11. Home Assistant (Optional)

**Provider Type**: `home_assistant`

**UI Configuration Form**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | text | Yes | Display name |
| `service` | text | Yes | HA notify service (e.g., `notify.mobile_app_phone`) |

**Description**: Uses existing HA connection to call notify services. Keeps backward compatibility with ADR 0034.

**Per-notification options**:
| Field | Type | Description |
|-------|------|-------------|
| `message` | text | Message (required) |
| `title` | text | Title |
| `data` | json | Service-specific data |

---

## Data Models

### NotificationProvider Model

```python
class NotificationProvider(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    profile = models.ForeignKey(AlarmProfile, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    provider_type = models.CharField(max_length=50, choices=PROVIDER_TYPES)
    config = models.JSONField()  # Encrypted credentials
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['profile', 'name']
```

### Provider Types Enum

```python
PROVIDER_TYPES = [
    ('discord', 'Discord'),
    ('telegram', 'Telegram'),
    ('pushover', 'Pushover'),
    ('pushbullet', 'Pushbullet'),
    ('ntfy', 'Ntfy'),
    ('email', 'Email (SMTP)'),
    ('twilio_sms', 'Twilio SMS'),
    ('twilio_call', 'Twilio Voice Call'),
    ('slack', 'Slack'),
    ('webhook', 'Webhook'),
    ('home_assistant', 'Home Assistant'),
]
```

### Action Schema

```python
# In action_schemas.py
SEND_NOTIFICATION_SCHEMA = {
    "type": "send_notification",
    "provider_id": "uuid",        # Required: references NotificationProvider
    "message": "string",          # Required
    "title": "string",            # Optional
    "data": {}                    # Optional: provider-specific options
}
```

---

## UI Components

### Settings > Notification Providers

```
┌─────────────────────────────────────────────────────────────┐
│  Notification Providers                          [+ Add]    │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Discord - Security Alerts          ✓ Enabled        │   │
│  │ Type: Discord Webhook                    [Test] [⋮] │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Telegram - Family Group            ✓ Enabled        │   │
│  │ Type: Telegram Bot                       [Test] [⋮] │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Emergency SMS                      ✓ Enabled        │   │
│  │ Type: Twilio SMS                         [Test] [⋮] │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Add Provider Dialog

```
┌─────────────────────────────────────────────────────────────┐
│  Add Notification Provider                              [×] │
├─────────────────────────────────────────────────────────────┤
│  Provider Type                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ [Discord ▼]                                          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Display Name *                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Security Alerts                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Webhook URL *                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ https://discord.com/api/webhooks/...                 │   │
│  └─────────────────────────────────────────────────────┘   │
│  ℹ️ Right-click channel → Edit → Integrations → Webhooks   │
│                                                             │
│                              [Cancel]  [Test]  [Save]       │
└─────────────────────────────────────────────────────────────┘
```

### Rule Builder - Send Notification Action

```
┌─────────────────────────────────────────────────────────────┐
│  THEN                                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Action: [Send Notification ▼]                        │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Provider: [Discord - Security Alerts ▼]              │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Message: Alarm triggered at {{ timestamp }}          │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Title: Security Alert                                │   │
│  └─────────────────────────────────────────────────────┘   │
│  [+ Advanced Options]                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Backend Services

### Notification Dispatcher

```python
# backend/alarm/notifications/dispatcher.py

class NotificationDispatcher:
    """Sends notifications to configured providers."""

    def send(self, provider: NotificationProvider, message: str,
             title: str = None, data: dict = None) -> NotificationResult:
        handler = self._get_handler(provider.provider_type)
        return handler.send(provider.config, message, title, data)

    def _get_handler(self, provider_type: str) -> NotificationHandler:
        handlers = {
            'discord': DiscordHandler(),
            'telegram': TelegramHandler(),
            'pushover': PushoverHandler(),
            'pushbullet': PushbulletHandler(),
            'ntfy': NtfyHandler(),
            'email': EmailHandler(),
            'twilio_sms': TwilioSMSHandler(),
            'twilio_call': TwilioCallHandler(),
            'slack': SlackHandler(),
            'webhook': WebhookHandler(),
            'home_assistant': HomeAssistantHandler(),
        }
        return handlers[provider_type]
```

### Provider Handler Protocol

```python
class NotificationHandler(Protocol):
    def send(self, config: dict, message: str,
             title: str = None, data: dict = None) -> NotificationResult:
        ...

    def validate_config(self, config: dict) -> list[str]:
        """Return list of validation errors, empty if valid."""
        ...

    def test(self, config: dict) -> NotificationResult:
        """Send test notification."""
        ...
```

---

## API Endpoints

```
# Notification Providers CRUD
GET    /api/notification-providers/           # List all providers
POST   /api/notification-providers/           # Create provider
GET    /api/notification-providers/{id}/      # Get provider
PUT    /api/notification-providers/{id}/      # Update provider
DELETE /api/notification-providers/{id}/      # Delete provider
POST   /api/notification-providers/{id}/test/ # Send test notification

# Provider metadata
GET    /api/notification-providers/types/     # List available provider types with schemas
```

---

## Configuration Summary

| Provider | Required Fields | Optional Fields | Cost |
|----------|----------------|-----------------|------|
| **Discord** | webhook_url | - | Free |
| **Telegram** | bot_token, chat_id | - | Free |
| **Pushover** | api_token, user_key | - | $5 one-time |
| **Pushbullet** | api_key | device_iden | Freemium |
| **Ntfy** | server_url, topic | username, password | Free |
| **Email** | smtp_host, port, user, pass, from, to | from_name, tls/ssl | Varies |
| **Twilio SMS** | account_sid, auth_token, from, to | - | Per-message |
| **Twilio Call** | account_sid, auth_token, from, to | - | Per-minute |
| **Slack** | webhook_url | - | Free |
| **Webhook** | url, method | headers, auth | Free |
| **Home Assistant** | service | - | Free |

---

## Migration from ADR 0034

1. Keep `ha_call_service` action type working for backward compatibility
2. Add migration to convert `ha_call_service` with `notify.*` to `send_notification` with `home_assistant` provider
3. Encourage users to configure native providers for better reliability

---

## Alternatives Considered

1. **Keep HA-only approach (ADR 0034)**
   - Rejected: Poor UX, requires YAML editing, HA dependency

2. **OAuth flows for each service**
   - Rejected: Overly complex, most services use simple API keys/webhooks

3. **Third-party notification aggregator (Apprise, etc.)**
   - Considered: Could simplify backend, but adds dependency
   - May revisit if maintenance burden is high

---

## Consequences

### Positive
- All configuration in one UI - no YAML editing
- Notifications work even if Home Assistant is down
- Credentials stored encrypted alongside other settings
- Test button provides immediate feedback
- Provider-specific UI hints improve UX

### Negative
- More backend code to maintain (one handler per provider)
- Must track API changes for each provider
- Initial implementation effort is higher

### Neutral
- Shifts complexity from HA to our system
- Need to document how to get credentials for each provider

---

## Implementation Plan

1. **Backend**
   - [x] Create `NotificationProvider` model with encrypted config
   - [x] Create provider handler protocol and base class
   - [x] Implement handlers: Discord, Webhook
   - [x] Implement handlers: Pushbullet
   - [ ] Implement handlers: Telegram, Pushover, Email
   - [ ] Implement handlers: Ntfy, Slack
   - [ ] Implement handlers: Twilio SMS, Twilio Call
   - [x] Implement Home Assistant handler (backward compat)
   - [x] Create API endpoints for CRUD and test
   - [x] Add `send_notification` action type to rules engine
   - [x] Update action executor to dispatch notifications

2. **Frontend**
   - [x] Create Settings > Notification Providers tab
   - [x] Create provider list component with enable/disable
   - [x] Create add/edit provider dialog with dynamic forms
   - [x] Add test notification button with feedback
   - [x] Update ActionsEditor for `send_notification` action
   - [x] Add provider picker dropdown
   - [x] Add provider-specific option fields (Pushbullet)

3. **Migration**
   - [ ] Create migration command for existing `ha_call_service` notify rules
   - [ ] Document migration path for users

---

## References

- [ADR 0034: Notifications as Rule Actions](0034-notifications-as-rule-actions.md)
- [ADR 0017: Home Assistant Connection Settings (Encrypted)](0017-home-assistant-connection-settings-in-profile.md)
- [Discord Webhooks](https://discord.com/developers/docs/resources/webhook)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Pushover API](https://pushover.net/api)
- [Twilio API](https://www.twilio.com/docs/usage/api)
- [Ntfy Documentation](https://docs.ntfy.sh/)
