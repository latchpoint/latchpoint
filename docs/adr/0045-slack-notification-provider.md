# ADR 0045: Slack Notification Provider

## Status
**Implemented**

## Context
The notifications system (ADR 0044) supports provider-based notifications with durable outbox delivery (ADR 0043). We currently support a generic `webhook` provider and first-class providers for Pushbullet/Discord/Home Assistant.

Slack is a common destination for operational/security alerts. While Slack Incoming Webhooks can be used via the generic `webhook` provider, a first-class Slack provider improves UX by:
- Supporting Bot Token auth (works with private channels and richer features).
- Validating credentials in-app.
- Providing an explicit “default channel” configuration.

## Decision
Implement a first-class `slack` notification provider using Slack Web API (`chat.postMessage`) with a Bot Token.

### Provider type
`provider_type = "slack"`

### Provider configuration schema
Stored in `notifications.NotificationProvider.config` (encrypted fields noted):
```json
{
  "bot_token": "xoxb-...",
  "default_channel": "C0123456789",
  "default_username": "Alarm System",
  "default_icon_emoji": ":rotating_light:"
}
```

- `bot_token` is encrypted at rest.
- `default_channel` should be stored as a channel ID (recommended).

### Rule action schema
Reuse existing `send_notification` action:
```json
{
  "type": "send_notification",
  "provider_id": "<uuid-of-slack-provider>",
  "message": "Alarm triggered!",
  "title": "Security Alert",
  "data": {
    "channel": "C0123456789",
    "blocks": [],
    "attachments": []
  }
}
```

Notes:
- `message` maps to Slack `text`.
- If `title` is present, format `text` as `*Title*\\nMessage` (or use a simple block header when `blocks` is omitted).
- `data.channel` overrides `default_channel` when provided.
- `blocks`/`attachments` are optional “advanced” payloads and passed through if provided.

### Backend handler behavior
Add `notifications.handlers.slack.SlackHandler`:
- Calls `POST https://slack.com/api/chat.postMessage`
- Headers: `Authorization: Bearer <bot_token>`
- Request JSON:
  - `channel`: from `data.channel` or `default_channel`
  - `text`: from `message` (+ optional `title`)
  - Optional: `username`, `icon_emoji`, `blocks`, `attachments`
- Validation:
  - `bot_token` required and matches `^xoxb-`
  - `default_channel` required (non-empty)
- Error mapping:
  - HTTP 429 => `RATE_LIMITED`
  - Timeout => `TIMEOUT`
  - Network error => `NETWORK_ERROR`
  - `{ "ok": false, "error": "..." }` => `API_ERROR` (surface Slack `error`)

### Optional helper endpoints
For better UX (channel pickers and token validation), optionally add:
- `GET /api/notifications/slack/channels/` (calls `conversations.list`)
- `POST /api/notifications/slack/validate-token/` (calls `auth.test`)

These endpoints are convenience-only; the primary send path remains outbox + handler.

### Frontend UX
Add Slack to Settings > Notification Providers:
- Fields: Display name, Bot token, Default channel (picker if channels endpoint exists).
In the rule builder:
- Keep generic message/title fields.
- Optional: “Channel override” and advanced JSON editor for blocks/attachments.

## Alternatives Considered
- Slack Incoming Webhooks only: already possible via generic `webhook`, but weaker UX and less flexible for private channels.
- No first-class provider: rejected due to common demand and the value of credential validation.

## Consequences
- Adds Slack as a first-class provider with encrypted credentials.
- Slack rate limits map cleanly to the existing outbox retry/backoff behavior.

## Todos
- Backend: implement `SlackHandler`, register it, and add unit tests.
- Backend (optional): add channel list + token validation endpoints.
- Frontend: add Slack provider form and align provider type lists.
