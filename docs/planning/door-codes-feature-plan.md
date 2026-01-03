# Door Codes Feature - Implementation Plan

## Overview
Add door lock code management similar to the existing alarm codes feature: admins can create/manage PIN codes and choose which Home Assistant lock entities each code applies to. Codes are enforced by this app (not pushed down into lock hardware).

## Current State Analysis

### Existing Alarm Codes Implementation
The system has a robust alarm code implementation that can serve as a template:

**Location**: `backend/accounts/`
- **Models**: `UserCode` model with support for:
  - Multiple code types (PERMANENT, TEMPORARY, ONE_TIME, SERVICE)
  - Time-based restrictions (date ranges, days of week, time windows)
  - Usage tracking and limits
  - State-based access control (`UserCodeAllowedState`)
  - Bcrypt password hashing for security

- **Validation**: `backend/accounts/use_cases/code_validation.py`
  - Comprehensive time constraint checks
  - Timezone-aware validation
  - Audit logging (uses count, last used timestamp)

- **API**: `backend/accounts/views/codes.py`
  - RESTful endpoints for CRUD operations
  - Requires admin role + reauth for sensitive operations
  - PIN validation (4-8 digits)

### Door Lock Integration Status
- Door lock entities can be discovered from Home Assistant (`domain == "lock"`).
- This feature does **not** attempt to manage lock hardware “usercode slots” via HA service calls.

---

## Feature Requirements

### Core Functionality
1. **Code Management**
   - Create/update/delete door codes with 4-8 digit PINs
   - Label codes for easy identification
   - Toggle codes active/inactive
   - Track usage statistics

2. **Lock Assignment**
   - Select one or more door locks per code
   - Lock selection is based on Home Assistant lock entities (e.g. `lock.front_door`)
   - UI should display lock names from Home Assistant discovery

3. **Code Types**
   - **Permanent**: No expiration, always active
   - **Temporary**: Time-bound with optional:
     - Start/end dates
     - Days of week restrictions
     - Time window restrictions (e.g., 9 AM - 5 PM)
     - Maximum usage limits

4. **Security**
   - Bcrypt hashing for PIN storage
   - Admin role required for code management
   - Reauthentication for code creation
   - Audit trail of all code usage

5. **Integration**
   - Discover locks from Home Assistant for selection
   - Persist code ↔ lock-entity assignments in the DB
   - Validate a code optionally scoped to a lock entity (`lock_entity_id`)

---

## Data Model Design

### New Models

#### DoorCode
Primary model for storing door lock codes (similar to UserCode).

```python
# backend/locks/models.py

class DoorCode(models.Model):
    """Door lock access code"""

    CODE_TYPE_PERMANENT = 'permanent'
    CODE_TYPE_TEMPORARY = 'temporary'
    CODE_TYPE_ONE_TIME = 'one_time'
    CODE_TYPE_SERVICE = 'service'

    CODE_TYPE_CHOICES = [
        (CODE_TYPE_PERMANENT, 'Permanent'),
        (CODE_TYPE_TEMPORARY, 'Temporary'),
        (CODE_TYPE_ONE_TIME, 'One Time'),
        (CODE_TYPE_SERVICE, 'Service'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='door_codes')
    code_hash = models.CharField(max_length=255)  # bcrypt hash
    pin_length = models.IntegerField()
    label = models.CharField(max_length=100)
    code_type = models.CharField(max_length=20, choices=CODE_TYPE_CHOICES)
    is_active = models.BooleanField(default=True)

    # Time restrictions (optional)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    days_of_week = models.IntegerField(default=127)  # Bitmask: 0-127 (0=Mon, 6=Sun)
    window_start = models.TimeField(null=True, blank=True)  # e.g., 09:00:00
    window_end = models.TimeField(null=True, blank=True)    # e.g., 17:00:00

    # Usage tracking
    max_uses = models.IntegerField(null=True, blank=True)
    uses_count = models.IntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_lock = models.CharField(max_length=255, null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'door_codes'
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['code_type']),
        ]
```

#### DoorCodeLockAssignment
Junction table for many-to-many relationship between codes and locks.

```python
class DoorCodeLockAssignment(models.Model):
    """Assignment of door codes to specific locks"""

    door_code = models.ForeignKey(DoorCode, on_delete=models.CASCADE, related_name='lock_assignments')
    lock_entity_id = models.CharField(max_length=255)  # HA entity ID (e.g., "lock.front_door")

    class Meta:
        db_table = 'door_code_lock_assignments'
        unique_together = [['door_code', 'lock_entity_id']]
        indexes = [
            models.Index(fields=['lock_entity_id']),
        ]
```

#### DoorCodeEvent
Audit trail for door code usage.

```python
class DoorCodeEvent(models.Model):
    """Audit log for door code operations"""

    EVENT_CODE_USED = 'code_used'
    EVENT_CODE_FAILED = 'code_failed'
    EVENT_CODE_SYNCED = 'code_synced'
    EVENT_CODE_REMOVED = 'code_removed'

    EVENT_TYPE_CHOICES = [
        (EVENT_CODE_USED, 'Code Used'),
        (EVENT_CODE_FAILED, 'Code Failed'),
        (EVENT_CODE_SYNCED, 'Code Synced'),
        (EVENT_CODE_REMOVED, 'Code Removed'),
    ]

    door_code = models.ForeignKey(DoorCode, on_delete=models.CASCADE, related_name='events')
    lock_entity_id = models.CharField(max_length=255, null=True, blank=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    metadata = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'door_code_events'
        indexes = [
            models.Index(fields=['door_code', 'timestamp']),
            models.Index(fields=['event_type', 'timestamp']),
        ]
```

---

## API Design

### Endpoints

#### Lock Discovery
```
GET /api/locks/available/
Response: List of available door locks from Home Assistant
[
  {
    "entity_id": "lock.front_door",
    "name": "Front Door",
    "manufacturer": "Schlage",
    "model": "BE469"
  }
]
```

#### Door Code Management
```
GET /api/door-codes/
Response: List of user's door codes

POST /api/door-codes/
Request:
{
  "label": "Cleaning Service",
  "code": "1234",  // 4-8 digits (write-only)
  "code_type": "temporary",
  "lock_entity_ids": ["lock.front_door", "lock.back_door"],
  "start_at": "2025-01-01T00:00:00Z",
  "end_at": "2025-12-31T23:59:59Z",
  "days_of_week": 62,  // Mon-Fri (bits 0-4)
  "window_start": "09:00:00",
  "window_end": "17:00:00",
  "max_uses": 100
}
Response: Created door code (without code field)

GET /api/door-codes/{id}/
Response: Door code details

PATCH /api/door-codes/{id}/
Request: Partial update (same fields as POST)
Response: Updated door code

DELETE /api/door-codes/{id}/
Response: 204 No Content
```

---

## Implementation Phases

### Phase 1: Core Backend (Week 1)
**Goal**: Door code CRUD + lock assignment

- [x] Create `backend/locks/` Django app
- [x] Define models: `DoorCode`, `DoorCodeLockAssignment`, `DoorCodeEvent`
- [x] Create database migrations
- [x] Implement use cases (create/update/delete/list/validate/record usage)
- [x] Add serializers with validation
- [x] Create API views and URL routing
- [x] Add permissions (admin role + reauth for writes)
- [x] Write unit tests for API + validation

**Files to Create:**
- `backend/locks/__init__.py`
- `backend/locks/models.py`
- `backend/locks/migrations/0001_initial.py`
- `backend/locks/use_cases/door_codes.py`
- `backend/locks/use_cases/code_validation.py`
- `backend/locks/serializers.py`
- `backend/locks/views/door_codes.py`
- `backend/locks/urls.py`
- `backend/locks/permissions.py`
- `backend/locks/tests/test_door_codes.py`

**Dependencies:**
- Reuse `backend/accounts/use_cases/code_validation.py` patterns
- Follow same security patterns as alarm codes

---

### Phase 2: Lock Discovery (Week 2)
**Goal**: Discover HA locks for selection (no hardware code sync)

- [x] Implement lock entity discovery:
  - `GET /api/locks/available/` queries Home Assistant for `domain == "lock"`

---

### Phase 3: Frontend UI (Week 3)
**Goal**: User interface for managing door codes (React)

- [ ] Create door codes management page
  - List view with filters (active, expired, by lock)
  - Create/edit form with lock selection
  - Code type selector (permanent vs temporary)
  - Time restriction UI (date pickers, day selector, time range)
  - Lock assignment multi-select
- [ ] Add lock status indicators
  - Show sync status per lock
  - Display available code slots
  - Lock online/offline status
- [ ] Usage statistics dashboard
  - Recent code usage events
  - Usage count charts
  - Failed attempts log
- [ ] Validation feedback
  - Real-time PIN validation
  - Time window conflicts
  - Code slot availability warnings

**Files to Create (expected shape):**
- `frontend/src/views/DoorCodes.tsx`
- `frontend/src/components/DoorCodeForm.tsx`
- `frontend/src/components/DoorCodeList.tsx`
- `frontend/src/components/LockSelector.tsx`

**UI Components Needed:**
- Code list table with actions
- Modal for create/edit
- Time range picker
- Day of week selector (checkboxes)
- Lock multi-select dropdown
- Sync status badges
- Usage statistics cards

---

### Phase 4: Advanced Features (Week 4)
**Goal**: Polish and advanced capabilities

- [ ] One-time codes
  - Auto-expire after single use
  - Immediate notification on use
- [ ] Service codes
  - Special category for contractors/maintenance
  - Extended audit logging
- [ ] Notifications
  - Code used notification (push/email)
  - Code expiring soon alerts
  - Sync failure alerts
- [ ] Code sharing
  - Generate shareable links (temporary)
  - QR codes for easy sharing
  - Guest code templates
- [ ] Bulk operations
  - Import codes from CSV
  - Bulk enable/disable
  - Code rotation (regenerate all codes)
- [ ] Lock automations
  - Auto-unlock on alarm disarm
  - Auto-lock on alarm arm
  - Integration with alarm rules engine

**Files to Enhance:**
- `backend/locks/use_cases/notifications.py`
- `backend/locks/use_cases/bulk_operations.py`
- `backend/alarm/rules_engine.py` (add lock actions)
- `frontend/src/components/CodeSharing.vue`

---

## Technical Considerations

### Security
- **Never store plaintext PINs**: Always use bcrypt hashing
- **Reauth required**: Force password confirmation for code creation
- **Audit everything**: Log all code operations (create, update, delete, use)
- **Rate limiting**: Prevent brute force attacks on code validation
- **Code rotation**: Encourage periodic code changes

### Performance
- **HA discovery**: Keep lock discovery read-only and fast; cache client-side if needed
- **Indexing**: Database indexes on frequently queried fields

### Reliability
- **No hardware sync**: Removes a large class of lock/vendor reliability issues

### Lock Compatibility
As long as Home Assistant exposes a `lock.*` entity, it can be selected. The app does not depend on lock/vendor code-slot support.

---

## Migration from Alarm Codes (Optional)

If users want to convert existing alarm codes to door codes:

- [ ] Create migration script: `migrate_alarm_codes_to_door_codes.py`
- [ ] Allow selecting which alarm codes to convert
- [ ] Preserve all time restrictions and metadata
- [ ] Keep both alarm and door codes (don't delete originals)

---

## Testing Strategy

### Unit Tests
- Code validation logic (time windows, days, date ranges)
- PIN hashing and comparison
- Lock assignment creation/deletion
- Serializer validation

### Integration Tests
- End-to-end API flows (create → sync → use → delete)
- HA service call mocking
- Database transactions and rollbacks
- Concurrent code usage

### Manual Testing
- Test with real Z-Wave lock
- Test with mock HA instance
- Test timezone edge cases (midnight, DST transitions)
- Test offline lock scenarios
- Test code slot exhaustion (all slots full)

---

## Documentation Needs

- [ ] User guide: Creating and managing door codes
- [ ] Admin guide: Lock setup and troubleshooting
- [ ] API documentation: OpenAPI/Swagger specs
- [ ] Developer guide: Adding support for new lock types
- [ ] Troubleshooting guide: Common sync issues

---

## Success Metrics

- Users can create door codes in < 1 minute
- Code sync to locks succeeds > 95% of time
- Code validation completes in < 100ms
- Support for top 5 lock brands (Schlage, Yale, Kwikset, August, Lockly)
- Zero plaintext PIN exposure in logs/database
- 100% audit coverage (all code operations logged)

---

## Open Questions

1. **Should door codes also grant alarm access?**
   - Option A: Separate systems (door codes ≠ alarm codes)
   - Option B: Unified codes (one code for both)
   - Recommendation: Separate initially, add linking later

2. **How to handle locks with full code slots?**
   - Auto-remove expired codes?
   - Show warning and let user choose which to remove?
   - Recommendation: Warning + manual selection

3. **Should codes be user-specific or system-wide?**
   - Current alarm codes are user-specific
   - Door codes might benefit from system-wide (shared family codes)
   - Recommendation: User-specific with sharing capability

4. **Offline lock support?**
   - Allow creating codes even if HA lock entity is currently unavailable?
   - Recommendation: Yes; lock selection is just an entity id.

5. **Code reuse across locks?**
   - Same PIN for multiple locks (simpler for users)
   - Different PINs per lock (more secure)
   - Recommendation: Same PIN can be assigned to multiple locks.

---

## Dependencies

### Python Packages
- `bcrypt` - Already used for alarm codes
- `pytz` / `zoneinfo` - Timezone handling

### Home Assistant Integrations
- Core `lock` entities exposed by Home Assistant

### Frontend
- React (current frontend)
- Date/time picker component
- Notification system

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| HA lock entity temporarily unavailable | Medium | Allow saving assignments; surface availability in lock picker UI |
| Timezone bugs in validation | Medium | Extensive testing, use well-tested libraries |
| Security: code exposure in logs | Critical | Audit all logging, never log plaintext PINs |
| User locks themselves out | High | Keep recovery/admin flow; keep good audit logging |

---

## Future Enhancements

- **Mobile app**: Manage codes from phone
- **Geofencing**: Auto-enable codes when user is near
- **NFC/Bluetooth unlock**: Alternative to PIN codes
- **Video integration**: See who used code (doorbell camera)
- **AI anomalies**: Detect unusual code usage patterns
- **Multi-home support**: Manage codes across multiple properties
- **Code templates**: Pre-configure common code types (guest, cleaner, delivery)

---

## Conclusion

This feature brings robust door code management to the alarm system by:
1. Leveraging proven patterns from existing alarm codes
2. Integrating with Home Assistant's lock ecosystem
3. Providing flexible permanent/temporary code options
4. Maintaining high security and audit standards

**Estimated Total Effort**: 4-6 weeks (1 developer)
**Complexity**: Medium-High
**Value**: High (frequently requested feature)

---

## Next Steps

1. Review and approve this plan
2. Refine open questions with stakeholders
3. Set up development environment with test locks
4. Begin Phase 1 implementation
5. Schedule weekly progress reviews
