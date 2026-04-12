# ADR 0080: Pushbullet Multi-Provider Endpoint Ambiguity

## Status
**Accepted**

## Context

`PushbulletDevicesView` and `PushbulletValidateTokenView` in `backend/notifications/views.py` select the first enabled Pushbullet provider in the active profile via `.first()`:

```python
provider = NotificationProvider.objects.filter(
    profile=profile, provider_type="pushbullet", is_enabled=True
).first()
```

With ADR 0079's multi-instance provider support, a user can configure multiple Pushbullet providers (e.g. different accounts for critical vs. informational alerts). The current endpoints are ambiguous — there is no way to specify which provider to query for device listing or token validation.

### Impact

- **Device listing**: A user editing their second Pushbullet provider will see devices from the first provider's access token instead.
- **Token validation**: Validating a token always checks against the first provider, not the one being configured.
- **Scope**: Currently limited to Pushbullet; other provider types with similar "test/validate" endpoints should be audited if this pattern is adopted.

## Decision

Accept a `provider_id` query parameter on both endpoints. Validate that the provider belongs to the active profile and is of type `pushbullet`. Fall back to `.first()` if no ID is provided for backwards compatibility during transition.
