# ADR-0032: Frigate Event JSON Viewer and Detection Cleanup Task

## Status
**Implemented**

## Context

The `FrigateDetection` model already stores the full raw Frigate event payload in a `raw` JSONField. However:

1. **No way to view full event data**: The current `/api/frigate/detections/` endpoint only returns summarized fields (`event_id`, `camera`, `zones`, `confidence_pct`, `observed_at`). Users cannot inspect the complete Frigate event payload for debugging or analysis.

2. **Unreliable retention enforcement**: The current `retention_seconds` setting (default: 3600 = 1 hour) controls how long detections are kept, but pruning only happens opportunistically during message ingestion. If no events arrive, old records never get cleaned up.

Users need:
- Ability to click on a detection event and see the full JSON payload (pretty-printed)
- Scheduled cleanup task to reliably enforce the existing `retention_seconds` setting

## Decision

### 1. Add Detection Detail Endpoint

Create a new API endpoint to retrieve the full event JSON:

**Endpoint**: `GET /api/frigate/detections/{id}/`

**Response**:
```json
{
  "id": 123,
  "event_id": "1704067200.123456-abc123",
  "provider": "frigate",
  "label": "person",
  "camera": "backyard",
  "zones": ["yard", "driveway"],
  "confidence_pct": 92.5,
  "observed_at": "2024-01-01T12:00:00Z",
  "source_topic": "frigate/events",
  "created_at": "2024-01-01T12:00:00Z",
  "updated_at": "2024-01-01T12:00:05Z",
  "raw": {
    "type": "update",
    "before": { ... },
    "after": {
      "id": "1704067200.123456-abc123",
      "camera": "backyard",
      "label": "person",
      "top_score": 0.925,
      "entered_zones": ["yard", "driveway"],
      "start_time": 1704067200.0,
      "end_time": 1704067205.0,
      "thumbnail": "...",
      "has_clip": true,
      "has_snapshot": true,
      ...
    }
  }
}
```

**Authorization**: Admin role required (consistent with list endpoint)

### 2. Update List Endpoint to Include ID

Modify `GET /api/frigate/detections/` to include the database `id` field so the frontend can link to the detail view:

```json
{
  "detections": [
    {
      "id": 123,
      "event_id": "1704067200.123456-abc123",
      "camera": "backyard",
      "zones": ["yard"],
      "confidence_pct": 92.5,
      "observed_at": "2024-01-01T12:00:00Z"
    }
  ]
}
```

### 3. Add Frigate Detection Cleanup Task

Leverage the existing in-process task scheduler (ADR-0024) to add a scheduled cleanup task:

**Configuration**: Uses existing `frigate.retention_seconds` setting (default: 3600 = 1 hour)

**Task Schedule**: Hourly (runs every hour to enforce retention)

**Implementation**:

```python
# backend/integrations_frigate/tasks.py
def cleanup_old_frigate_detections() -> int:
    """Delete FrigateDetection records older than the configured retention period."""
    settings = get_settings()
    cutoff = timezone.now() - timedelta(seconds=settings.retention_seconds)
    deleted_count, _ = FrigateDetection.objects.filter(observed_at__lt=cutoff).delete()
    logger.info("Frigate detection cleanup: deleted %d records older than %d seconds", deleted_count, settings.retention_seconds)
    return deleted_count
```

### 4. Frontend Changes

#### Detection List View
- Add clickable rows/links to each detection
- Link format: `/settings/frigate/detections/{id}`

#### Detection Detail View
New component to display:
- Summary header (camera, confidence, timestamp)
- Pretty-printed JSON viewer with syntax highlighting
- Copy-to-clipboard button for raw JSON

## Implementation

### Backend Files

| File | Changes |
|------|---------|
| `backend/integrations_frigate/views.py` | Add `FrigateDetectionDetailView` |
| `backend/integrations_frigate/serializers.py` | Add `FrigateDetectionDetailSerializer` |
| `backend/integrations_frigate/tasks.py` | New file: cleanup task function |
| `backend/integrations_frigate/urls.py` | Add detail endpoint route |
| `backend/alarm/scheduler.py` | Register Frigate cleanup task (hourly) |
| `backend/integrations_frigate/tests/test_frigate_api.py` | Test detail endpoint |
| `backend/integrations_frigate/tests/test_cleanup.py` | New: Test cleanup task |

### Frontend Files

| File | Changes |
|------|---------|
| `frontend/src/features/frigateSettings/api/frigateApi.ts` | Add `getDetectionDetail` API |
| `frontend/src/features/frigateSettings/components/DetectionDetailView.tsx` | New: JSON viewer component |
| `frontend/src/features/frigateSettings/components/DetectionsTable.tsx` | Add clickable rows with ID links |
| `frontend/src/pages/settings/SettingsFrigateTab.tsx` | Add route for detail view |

### API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/frigate/detections/` | List recent detections (updated: includes `id`) |
| GET | `/api/frigate/detections/{id}/` | Get full detection with raw JSON |

## Alternatives Considered

### Store raw JSON separately (e.g., file storage)
- **Pros**: Keeps database lean
- **Cons**: Adds complexity, requires file cleanup, harder to query
- **Verdict**: Database storage is fine for configurable retention periods

### Add separate retention setting for historical viewing
- **Pros**: Could keep short rules lookback + longer history
- **Cons**: Two settings is confusing; existing `retention_seconds` already serves both purposes
- **Verdict**: Keep single setting for simplicity

### WebSocket for real-time event viewing
- **Pros**: Live updates
- **Cons**: Overkill for occasional debugging; adds complexity
- **Verdict**: REST endpoint sufficient; can add WebSocket later if needed

## Consequences

### Positive
- Users can inspect full Frigate event payloads for debugging
- Pretty-printed JSON improves readability
- Scheduled cleanup ensures bounded table growth (no longer dependent on event arrival)
- Uses existing `retention_seconds` setting - no new configuration needed

### Negative
- Additional database queries for detail view (minor)

## Migration Notes

- No database migration needed (fields already exist)
- No settings changes needed - uses existing `retention_seconds`
- Behavior change: cleanup now runs on schedule instead of only during event ingestion

## Testing Checklist

- [x] Detail endpoint returns full `raw` JSON
- [x] Detail endpoint requires admin role
- [x] List endpoint includes `id` field
- [x] Cleanup task deletes records older than `retention_seconds`
- [x] Cleanup task runs hourly
- [x] Frontend displays pretty-printed JSON
- [x] Copy-to-clipboard works
