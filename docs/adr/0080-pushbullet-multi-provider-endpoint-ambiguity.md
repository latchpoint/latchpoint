# ADR 0080: Pushbullet Multi-Provider Endpoint Ambiguity

## Status
**Proposed**

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

## Investigation Needed

1. **Usage audit**: How are these endpoints called from the frontend? Does `PushbulletNotificationOptions.tsx` already have access to a `provider_id` it could pass?
2. **URL design**: Should the provider ID be a URL path param (`/api/notifications/providers/{id}/pushbullet/devices/`) or a query param (`?provider_id=123`)? Path param is more RESTful but requires URL restructuring.
3. **Backwards compatibility**: Is this a breaking change for any external consumers, or is the API internal-only?
4. **Other providers**: Do any other notification handlers have similar test/validate endpoints that would need the same fix?

## Proposed Direction

Accept a `provider_id` query parameter on both endpoints. Validate that the provider belongs to the active profile and is of type `pushbullet`. Fall back to `.first()` if no ID is provided for backwards compatibility during transition.
