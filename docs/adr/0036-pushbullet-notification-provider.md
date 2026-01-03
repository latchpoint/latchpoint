# ADR 0036: Pushbullet Notification Provider Implementation

## Status
**Superseded by ADR 0044**

## Context
ADR 0035 established the architecture for in-app notification provider configuration. This ADR details the specific implementation for Pushbullet as a notification provider.

Pushbullet is a popular notification service that:
- Supports push notifications to mobile devices (iOS, Android) and desktop browsers
- Offers a simple REST API with access token authentication
- Provides free tier with basic features, premium tier with more capacity
- Supports rich notifications with links, images, and files

## Decision

Implement Pushbullet as a first-class notification provider with full UI configuration and direct API integration.

---

## Pushbullet API Overview

### Authentication
All API requests use an Access Token passed as:
- HTTP Basic Auth: `Authorization: Basic base64(access_token:)`
- Or header: `Access-Token: <access_token>`

### Base URL
```
https://api.pushbullet.com/v2
```

### Rate Limits
- Free: 500 pushes/month
- Pro: Unlimited pushes
- API rate limit: ~1 request/second (soft limit)

---

## Provider Configuration Schema

### Database Fields

```python
# NotificationProvider.config JSON structure for pushbullet type
{
    "access_token": "o.xxxxxxxxxxxxxxxxxxxxxxxxx",  # Required, encrypted
    "default_device_iden": "ujpah72o0",              # Optional: specific device
    "default_channel_tag": "my-channel",             # Optional: channel tag
    "default_email": "user@example.com"              # Optional: email target
}
```

### UI Configuration Form

```
┌─────────────────────────────────────────────────────────────┐
│  Add Pushbullet Provider                                [×] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Display Name *                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ My Pushbullet                                        │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Access Token *                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ ••••••••••••••••••••••••••                           │   │
│  └─────────────────────────────────────────────────────┘   │
│  ℹ️ Get from: pushbullet.com → Settings → Access Tokens    │
│                                                             │
│  ─────────────── Default Target (Optional) ───────────────  │
│                                                             │
│  Target Type                                                │
│  ○ All devices (default)                                    │
│  ○ Specific device                                          │
│  ○ Email address                                            │
│  ○ Channel                                                  │
│                                                             │
│  [Device/Email/Channel field shown based on selection]      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ [Fetch Devices]  Lists available devices             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│                              [Cancel]  [Test]  [Save]       │
└─────────────────────────────────────────────────────────────┘
```

### Configuration Form Fields

| Field | Type | Required | Validation | Description |
|-------|------|----------|------------|-------------|
| `name` | text | Yes | 1-100 chars | Display name in UI |
| `access_token` | password | Yes | Starts with `o.` | Pushbullet access token |
| `target_type` | radio | No | enum | `all`, `device`, `email`, `channel` |
| `default_device_iden` | select | If device | Valid device ID | Device identifier |
| `default_email` | email | If email | Valid email | Target email address |
| `default_channel_tag` | text | If channel | Non-empty | Channel tag |

---

## Per-Notification Options (Rule Builder)

When creating a "Send Notification" action with a Pushbullet provider, these options are available:

### Basic Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | textarea | Yes | Notification body (supports newlines) |
| `title` | text | No | Notification title (defaults to "Alarm Notification") |

### Advanced Fields (collapsible)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | text | No | URL to open when notification is clicked |
| `target_override` | select | No | Override default target for this notification |
| `image_url` | text | No | URL of image to include (creates file push) |

### UI in Rule Builder

```
┌─────────────────────────────────────────────────────────────┐
│  THEN: Send Notification                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Provider: [Pushbullet - My Phone ▼]                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Message *                                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Alarm triggered!                                     │   │
│  │ Check cameras immediately.                           │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Title                                                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Security Alert                                       │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ▶ Advanced Options                                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ URL (opens on click)                                 │   │
│  │ ┌─────────────────────────────────────────────────┐ │   │
│  │ │ https://my-alarm.local/cameras                   │ │   │
│  │ └─────────────────────────────────────────────────┘ │   │
│  │                                                       │   │
│  │ Target Override                                       │   │
│  │ ┌─────────────────────────────────────────────────┐ │   │
│  │ │ [Use provider default ▼]                         │ │   │
│  │ └─────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Action Schema

```python
# Rule action for Pushbullet notification
{
    "type": "send_notification",
    "provider_id": "uuid-of-pushbullet-provider",
    "message": "Alarm triggered!\nCheck cameras immediately.",
    "title": "Security Alert",
    "data": {
        "url": "https://my-alarm.local/cameras",
        "target_override": {
            "type": "device",
            "device_iden": "ujpah72o0sjAoRtnM0jc"
        }
    }
}
```

---

## Backend Implementation

### Handler Class

```python
# backend/alarm/notifications/handlers/pushbullet.py

import httpx
from typing import Protocol
from dataclasses import dataclass

@dataclass
class NotificationResult:
    success: bool
    message: str
    provider_response: dict | None = None
    error_code: str | None = None

class PushbulletHandler:
    """Handles sending notifications via Pushbullet API."""

    BASE_URL = "https://api.pushbullet.com/v2"
    TIMEOUT = 10.0  # seconds

    def validate_config(self, config: dict) -> list[str]:
        """Validate provider configuration."""
        errors = []

        if not config.get("access_token"):
            errors.append("Access token is required")
        elif not config["access_token"].startswith("o."):
            errors.append("Access token should start with 'o.'")

        target_type = config.get("target_type", "all")
        if target_type == "device" and not config.get("default_device_iden"):
            errors.append("Device identifier is required when target type is 'device'")
        if target_type == "email" and not config.get("default_email"):
            errors.append("Email address is required when target type is 'email'")
        if target_type == "channel" and not config.get("default_channel_tag"):
            errors.append("Channel tag is required when target type is 'channel'")

        return errors

    def send(
        self,
        config: dict,
        message: str,
        title: str | None = None,
        data: dict | None = None
    ) -> NotificationResult:
        """Send a push notification via Pushbullet."""
        data = data or {}

        # Build push payload
        payload = self._build_payload(config, message, title, data)

        try:
            response = httpx.post(
                f"{self.BASE_URL}/pushes",
                json=payload,
                headers=self._get_headers(config["access_token"]),
                timeout=self.TIMEOUT
            )

            if response.status_code == 200:
                return NotificationResult(
                    success=True,
                    message="Notification sent successfully",
                    provider_response=response.json()
                )
            elif response.status_code == 401:
                return NotificationResult(
                    success=False,
                    message="Invalid access token",
                    error_code="AUTH_FAILED"
                )
            elif response.status_code == 403:
                return NotificationResult(
                    success=False,
                    message="Access token lacks required permissions",
                    error_code="FORBIDDEN"
                )
            elif response.status_code == 429:
                return NotificationResult(
                    success=False,
                    message="Rate limit exceeded. Try again later.",
                    error_code="RATE_LIMITED"
                )
            else:
                error_data = response.json() if response.content else {}
                return NotificationResult(
                    success=False,
                    message=f"Pushbullet API error: {error_data.get('error', {}).get('message', 'Unknown error')}",
                    error_code="API_ERROR",
                    provider_response=error_data
                )

        except httpx.TimeoutException:
            return NotificationResult(
                success=False,
                message="Request to Pushbullet timed out",
                error_code="TIMEOUT"
            )
        except httpx.RequestError as e:
            return NotificationResult(
                success=False,
                message=f"Network error: {str(e)}",
                error_code="NETWORK_ERROR"
            )

    def test(self, config: dict) -> NotificationResult:
        """Send a test notification."""
        return self.send(
            config,
            message="This is a test notification from your alarm system.",
            title="Test Notification"
        )

    def list_devices(self, access_token: str) -> list[dict]:
        """Fetch list of devices for the account."""
        try:
            response = httpx.get(
                f"{self.BASE_URL}/devices",
                headers=self._get_headers(access_token),
                timeout=self.TIMEOUT
            )
            if response.status_code == 200:
                data = response.json()
                # Filter to active devices only
                return [
                    {
                        "iden": d["iden"],
                        "nickname": d.get("nickname", "Unknown Device"),
                        "model": d.get("model"),
                        "type": d.get("type"),
                        "pushable": d.get("pushable", False)
                    }
                    for d in data.get("devices", [])
                    if d.get("active", True) and d.get("pushable", False)
                ]
            return []
        except Exception:
            return []

    def get_user_info(self, access_token: str) -> dict | None:
        """Fetch user info to validate token."""
        try:
            response = httpx.get(
                f"{self.BASE_URL}/users/me",
                headers=self._get_headers(access_token),
                timeout=self.TIMEOUT
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None

    def _get_headers(self, access_token: str) -> dict:
        """Build request headers."""
        return {
            "Access-Token": access_token,
            "Content-Type": "application/json"
        }

    def _build_payload(
        self,
        config: dict,
        message: str,
        title: str | None,
        data: dict
    ) -> dict:
        """Build the push payload."""
        # Determine push type
        if data.get("image_url"):
            payload = {
                "type": "file",
                "file_url": data["image_url"],
                "file_type": "image/jpeg",
                "body": message
            }
            if title:
                payload["file_name"] = title
        elif data.get("url"):
            payload = {
                "type": "link",
                "title": title or "Alarm Notification",
                "body": message,
                "url": data["url"]
            }
        else:
            payload = {
                "type": "note",
                "title": title or "Alarm Notification",
                "body": message
            }

        # Add target
        target = self._resolve_target(config, data)
        payload.update(target)

        return payload

    def _resolve_target(self, config: dict, data: dict) -> dict:
        """Resolve the notification target."""
        # Check for override in notification data
        if override := data.get("target_override"):
            return self._target_to_payload(override)

        # Use default from config
        target_type = config.get("target_type", "all")

        if target_type == "device":
            return {"device_iden": config["default_device_iden"]}
        elif target_type == "email":
            return {"email": config["default_email"]}
        elif target_type == "channel":
            return {"channel_tag": config["default_channel_tag"]}
        else:
            # "all" - no target specified, pushes to all devices
            return {}

    def _target_to_payload(self, target: dict) -> dict:
        """Convert target override to API payload."""
        target_type = target.get("type", "all")

        if target_type == "device":
            return {"device_iden": target["device_iden"]}
        elif target_type == "email":
            return {"email": target["email"]}
        elif target_type == "channel":
            return {"channel_tag": target["channel_tag"]}
        return {}
```

### Config Encryption

Sensitive fields in config are encrypted using the same approach as Home Assistant credentials (ADR 0017):

```python
# Fields to encrypt for pushbullet provider
PUSHBULLET_ENCRYPTED_FIELDS = ["access_token"]
```

---

## API Endpoints

### Provider-Specific Endpoints

```python
# GET /api/notification-providers/pushbullet/devices/
# Fetches available devices for a Pushbullet account
# Query params: access_token (or use saved provider's token)

@api_view(['GET'])
def list_pushbullet_devices(request):
    """List Pushbullet devices for device picker."""
    access_token = request.query_params.get('access_token')

    # Or get from existing provider
    provider_id = request.query_params.get('provider_id')
    if provider_id:
        provider = NotificationProvider.objects.get(id=provider_id)
        access_token = decrypt_field(provider.config['access_token'])

    if not access_token:
        return Response({'error': 'Access token required'}, status=400)

    handler = PushbulletHandler()
    devices = handler.list_devices(access_token)

    return Response({'devices': devices})


# POST /api/notification-providers/pushbullet/validate-token/
# Validates an access token before saving

@api_view(['POST'])
def validate_pushbullet_token(request):
    """Validate a Pushbullet access token."""
    access_token = request.data.get('access_token')

    if not access_token:
        return Response({'valid': False, 'error': 'Access token required'})

    handler = PushbulletHandler()
    user_info = handler.get_user_info(access_token)

    if user_info:
        return Response({
            'valid': True,
            'user': {
                'name': user_info.get('name'),
                'email': user_info.get('email'),
                'max_upload_size': user_info.get('max_upload_size')
            }
        })
    else:
        return Response({
            'valid': False,
            'error': 'Invalid access token'
        })
```

---

## Frontend Components

### Provider Form Component

```typescript
// frontend/src/features/notifications/components/PushbulletProviderForm.tsx

interface PushbulletConfig {
  access_token: string
  target_type: 'all' | 'device' | 'email' | 'channel'
  default_device_iden?: string
  default_email?: string
  default_channel_tag?: string
}

interface PushbulletDevice {
  iden: string
  nickname: string
  model?: string
  type?: string
}

export function PushbulletProviderForm({
  config,
  onChange,
  onValidate
}: ProviderFormProps<PushbulletConfig>) {
  const [devices, setDevices] = useState<PushbulletDevice[]>([])
  const [isLoadingDevices, setIsLoadingDevices] = useState(false)
  const [tokenValid, setTokenValid] = useState<boolean | null>(null)

  const fetchDevices = async () => {
    if (!config.access_token) return
    setIsLoadingDevices(true)
    try {
      const response = await api.get('/notification-providers/pushbullet/devices/', {
        params: { access_token: config.access_token }
      })
      setDevices(response.data.devices)
    } finally {
      setIsLoadingDevices(false)
    }
  }

  const validateToken = async () => {
    const response = await api.post('/notification-providers/pushbullet/validate-token/', {
      access_token: config.access_token
    })
    setTokenValid(response.data.valid)
    onValidate?.(response.data.valid)
  }

  return (
    <Stack spacing={2}>
      <TextField
        label="Access Token"
        type="password"
        value={config.access_token}
        onChange={(e) => onChange({ ...config, access_token: e.target.value })}
        required
        helperText="Get from pushbullet.com → Settings → Access Tokens"
        InputProps={{
          endAdornment: tokenValid !== null && (
            tokenValid ? <CheckIcon color="success" /> : <ErrorIcon color="error" />
          )
        }}
        onBlur={validateToken}
      />

      <FormControl>
        <FormLabel>Default Target</FormLabel>
        <RadioGroup
          value={config.target_type || 'all'}
          onChange={(e) => onChange({ ...config, target_type: e.target.value as any })}
        >
          <FormControlLabel value="all" control={<Radio />} label="All devices" />
          <FormControlLabel value="device" control={<Radio />} label="Specific device" />
          <FormControlLabel value="email" control={<Radio />} label="Email address" />
          <FormControlLabel value="channel" control={<Radio />} label="Channel" />
        </RadioGroup>
      </FormControl>

      {config.target_type === 'device' && (
        <>
          <Button
            variant="outlined"
            onClick={fetchDevices}
            disabled={!config.access_token || isLoadingDevices}
            startIcon={isLoadingDevices ? <CircularProgress size={16} /> : <RefreshIcon />}
          >
            Fetch Devices
          </Button>
          <Select
            value={config.default_device_iden || ''}
            onChange={(e) => onChange({ ...config, default_device_iden: e.target.value })}
            displayEmpty
          >
            <MenuItem value="">Select a device...</MenuItem>
            {devices.map((device) => (
              <MenuItem key={device.iden} value={device.iden}>
                {device.nickname} {device.model && `(${device.model})`}
              </MenuItem>
            ))}
          </Select>
        </>
      )}

      {config.target_type === 'email' && (
        <TextField
          label="Email Address"
          type="email"
          value={config.default_email || ''}
          onChange={(e) => onChange({ ...config, default_email: e.target.value })}
          required
        />
      )}

      {config.target_type === 'channel' && (
        <TextField
          label="Channel Tag"
          value={config.default_channel_tag || ''}
          onChange={(e) => onChange({ ...config, default_channel_tag: e.target.value })}
          required
          helperText="The channel's tag (not display name)"
        />
      )}
    </Stack>
  )
}
```

### Notification Options Component

```typescript
// frontend/src/features/notifications/components/PushbulletNotificationOptions.tsx

interface PushbulletNotificationData {
  url?: string
  target_override?: {
    type: 'all' | 'device' | 'email' | 'channel'
    device_iden?: string
    email?: string
    channel_tag?: string
  }
  image_url?: string
}

export function PushbulletNotificationOptions({
  data,
  onChange,
  providerId
}: NotificationOptionsProps<PushbulletNotificationData>) {
  const [showAdvanced, setShowAdvanced] = useState(false)

  return (
    <>
      <Accordion expanded={showAdvanced} onChange={() => setShowAdvanced(!showAdvanced)}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>Advanced Options</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            <TextField
              label="URL (opens on click)"
              value={data.url || ''}
              onChange={(e) => onChange({ ...data, url: e.target.value })}
              placeholder="https://..."
            />

            <TextField
              label="Image URL"
              value={data.image_url || ''}
              onChange={(e) => onChange({ ...data, image_url: e.target.value })}
              placeholder="https://..."
              helperText="Attach an image to the notification"
            />

            <FormControl>
              <FormLabel>Target Override</FormLabel>
              <Select
                value={data.target_override?.type || 'default'}
                onChange={(e) => {
                  if (e.target.value === 'default') {
                    onChange({ ...data, target_override: undefined })
                  } else {
                    onChange({
                      ...data,
                      target_override: { type: e.target.value as any }
                    })
                  }
                }}
              >
                <MenuItem value="default">Use provider default</MenuItem>
                <MenuItem value="all">All devices</MenuItem>
                <MenuItem value="device">Specific device</MenuItem>
                <MenuItem value="email">Email address</MenuItem>
              </Select>
            </FormControl>

            {data.target_override?.type === 'device' && (
              <PushbulletDevicePicker
                providerId={providerId}
                value={data.target_override.device_iden}
                onChange={(iden) => onChange({
                  ...data,
                  target_override: { ...data.target_override!, device_iden: iden }
                })}
              />
            )}

            {data.target_override?.type === 'email' && (
              <TextField
                label="Email Address"
                type="email"
                value={data.target_override.email || ''}
                onChange={(e) => onChange({
                  ...data,
                  target_override: { ...data.target_override!, email: e.target.value }
                })}
              />
            )}
          </Stack>
        </AccordionDetails>
      </Accordion>
    </>
  )
}
```

---

## Push Types Reference

Pushbullet supports several push types. We implement the most useful ones:

### Note Push (Default)
Simple text notification.
```json
{
  "type": "note",
  "title": "Title",
  "body": "Message body"
}
```

### Link Push
Notification with clickable URL.
```json
{
  "type": "link",
  "title": "Title",
  "body": "Message body",
  "url": "https://example.com"
}
```

### File Push
Notification with attached image.
```json
{
  "type": "file",
  "file_url": "https://example.com/image.jpg",
  "file_type": "image/jpeg",
  "body": "Caption"
}
```

---

## Error Handling

### Error Codes

| HTTP Status | Error Code | User Message | Action |
|-------------|------------|--------------|--------|
| 401 | `AUTH_FAILED` | Invalid access token | Re-enter token |
| 403 | `FORBIDDEN` | Access denied | Check permissions |
| 429 | `RATE_LIMITED` | Rate limit exceeded | Wait and retry |
| 5xx | `SERVER_ERROR` | Pushbullet service unavailable | Retry later |
| Timeout | `TIMEOUT` | Request timed out | Retry |
| Network | `NETWORK_ERROR` | Network error | Check connectivity |

### Retry Logic

```python
# In action executor
MAX_RETRIES = 2
RETRY_DELAY = 1.0  # seconds

async def execute_with_retry(handler, config, message, title, data):
    for attempt in range(MAX_RETRIES + 1):
        result = handler.send(config, message, title, data)

        if result.success:
            return result

        # Don't retry auth failures
        if result.error_code in ('AUTH_FAILED', 'FORBIDDEN'):
            return result

        # Retry on transient errors
        if result.error_code in ('TIMEOUT', 'NETWORK_ERROR', 'SERVER_ERROR'):
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                continue

        return result

    return result
```

---

## Testing

### Unit Tests

```python
# backend/alarm/notifications/tests/test_pushbullet_handler.py

class TestPushbulletHandler:

    def test_validate_config_valid(self):
        handler = PushbulletHandler()
        config = {"access_token": "o.valid_token"}
        errors = handler.validate_config(config)
        assert errors == []

    def test_validate_config_missing_token(self):
        handler = PushbulletHandler()
        config = {}
        errors = handler.validate_config(config)
        assert "Access token is required" in errors

    def test_validate_config_invalid_token_format(self):
        handler = PushbulletHandler()
        config = {"access_token": "invalid_token"}
        errors = handler.validate_config(config)
        assert "Access token should start with 'o.'" in errors

    def test_validate_config_device_target_missing_iden(self):
        handler = PushbulletHandler()
        config = {
            "access_token": "o.valid",
            "target_type": "device"
        }
        errors = handler.validate_config(config)
        assert "Device identifier is required" in errors

    @responses.activate
    def test_send_success(self):
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"iden": "push123", "active": True},
            status=200
        )

        handler = PushbulletHandler()
        result = handler.send(
            config={"access_token": "o.test"},
            message="Test message",
            title="Test"
        )

        assert result.success is True
        assert "push123" in str(result.provider_response)

    @responses.activate
    def test_send_auth_failure(self):
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"error": {"message": "Invalid access token"}},
            status=401
        )

        handler = PushbulletHandler()
        result = handler.send(
            config={"access_token": "o.invalid"},
            message="Test"
        )

        assert result.success is False
        assert result.error_code == "AUTH_FAILED"

    @responses.activate
    def test_send_with_url(self):
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"iden": "push123"},
            status=200
        )

        handler = PushbulletHandler()
        result = handler.send(
            config={"access_token": "o.test"},
            message="Check this out",
            title="Link",
            data={"url": "https://example.com"}
        )

        assert result.success is True
        # Verify payload was link type
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["type"] == "link"
        assert request_body["url"] == "https://example.com"

    @responses.activate
    def test_send_to_specific_device(self):
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"iden": "push123"},
            status=200
        )

        handler = PushbulletHandler()
        result = handler.send(
            config={
                "access_token": "o.test",
                "target_type": "device",
                "default_device_iden": "device123"
            },
            message="Test"
        )

        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["device_iden"] == "device123"
```

---

## Security Considerations

1. **Token Storage**: Access tokens are encrypted at rest using Fernet (same as HA credentials)
2. **Token Transmission**: Only transmitted over HTTPS to Pushbullet API
3. **Token Display**: Never shown in full in UI (password field, masked)
4. **Token Validation**: Validated before saving to prevent storing invalid tokens
5. **Audit Logging**: All notification sends are logged (without sensitive data)

---

## Implementation Plan

1. **Backend**
   - [x] Create `PushbulletHandler` class
   - [x] Add Pushbullet-specific API endpoints (devices, validate)
   - [x] Add unit tests with mocked responses
   - [x] Register handler in dispatcher

2. **Frontend**
   - [x] Create `PushbulletProviderForm` component
   - [x] Create `PushbulletNotificationOptions` component
   - [x] Add device picker with fetch functionality
   - [x] Add token validation feedback
   - [x] Integrate into Settings > Notification Providers page
   - [x] Integrate into ActionsEditor for send_notification action

3. **Integration**
   - [x] Add Pushbullet to provider type registry
   - [x] Test end-to-end flow
   - [x] Add to documentation

---

## References

- [Pushbullet API Documentation](https://docs.pushbullet.com/)
- [Pushbullet HTTP API](https://docs.pushbullet.com/#http)
- [ADR 0035: Notification Providers with In-App Configuration](0035-notification-types-configuration-reference.md)
- [ADR 0017: Home Assistant Connection Settings (Encrypted)](0017-home-assistant-connection-settings-in-profile.md)
