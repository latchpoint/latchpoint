# ADR-0041: Django 6.x Upgrade Plan

## Status
**COMPLETED** - 2025-12-29

## Context
The project was upgraded from Django 5.x to Django 6.0.

### Environment After Upgrade
- **Django version**: 6.0
- **Python version**: 3.12
- **Database**: PostgreSQL (via psycopg2-binary)
- **Key dependencies**: Django REST Framework 3.16.1, Channels 4.3.2, Daphne 4.2.1

---

## Upgrade Path

The upgrade must go through **Django 6.0 first**, then to 6.1. This is because Django 6.0 removes deprecated features from Django 5.x that must be addressed.

### Phase 1: Pre-Upgrade Preparation ✅ COMPLETED

#### 1.1 Run Deprecation Warnings
```bash
docker compose exec web sh -c "cd backend && python -Wd manage.py check"
docker compose exec web sh -c "cd backend && python -Wd manage.py test"
```

**Results (2025-12-29):**
```
RemovedInDjango60Warning: CheckConstraint.check is deprecated in favor of `.condition`.
  - accounts/models.py:48
  - accounts/models.py:162
  - accounts/models.py:166
  - accounts/models.py:171
  - alarm/models.py:181
  - locks/models.py:57
  - locks/models.py:61
  - locks/models.py:66
  - accounts/migrations/0001_initial.py:230, 257, 264, 272
```

**Additional warnings found:**
- `paho-mqtt`: `DeprecationWarning: Callback API version 1 is deprecated` (in `transports_mqtt/manager.py:285`)

#### 1.2 Verify Third-Party Package Compatibility

| Package | Current | Django 6.0 Support | Status |
|---------|---------|-------------------|--------|
| djangorestframework | >=3.15 | 3.17 (unreleased, merged Dec 5) | ⚠️ Wait for 3.17 release |
| channels | >=4.0 | 4.3.2 confirms Django 6.0 | ✅ Update to `>=4.3.2` |
| daphne | >=4.1 | Compatible | ✅ No change needed |
| django-environ | >=0.11 | Check required | ⚠️ Test compatibility |
| django-cors-headers | >=4.3 | Check required | ⚠️ Test compatibility |
| paho-mqtt | >=1.6 | Update callback API | ⚠️ Update to v2 API |

**Key Finding:** Django REST Framework 3.17 with Django 6.0 support has been merged but not yet released (as of Dec 29, 2025). Current PyPI version is 3.16.1.

**Recommendation:** Wait for DRF 3.17 release before upgrading to Django 6.0, OR test with DRF from git main branch.

---

### Phase 2: Code Changes Required (Critical) ✅ COMPLETED

#### 2.1 CheckConstraint `check` → `condition` Parameter (BREAKING)

**Issue**: The `check` keyword argument was deprecated in Django 5.0 and **removed in Django 6.0**.

**Files affected**:
- `backend/accounts/models.py` (4 occurrences)
- `backend/alarm/models.py` (1 occurrence)
- `backend/locks/models.py` (3 occurrences)
- Several migration files

**Current code**:
```python
models.CheckConstraint(
    check=Q(failed_login_attempts__gte=0),
    name="users_failed_login_attempts_gte_0",
)
```

**Required change**:
```python
models.CheckConstraint(
    condition=Q(failed_login_attempts__gte=0),
    name="users_failed_login_attempts_gte_0",
)
```

**Complete list of changes**:

| File | Line | Constraint Name |
|------|------|-----------------|
| `accounts/models.py` | 48 | `users_failed_login_attempts_gte_0` |
| `accounts/models.py` | 162 | `user_codes_pin_length_between_4_8` |
| `accounts/models.py` | 166 | `user_codes_days_of_week_between_0_127` |
| `accounts/models.py` | 171 | `user_codes_uses_count_gte_0` |
| `alarm/models.py` | 181 | `alarm_events_timestamp_not_null` |
| `locks/models.py` | 57 | `door_codes_pin_length_between_4_8` |
| `locks/models.py` | 61 | `door_codes_days_of_week_between_0_127` |
| `locks/models.py` | 66 | `door_codes_uses_count_gte_0` |

#### 2.2 Migration Files with `check=`

Some existing migration files also use `check=`. These need to be updated or squashed:

- `backend/accounts/migrations/0001_initial.py` (lines 230, 257, 264, 272)

**Options**:
1. **Squash migrations** - Create new squashed migration with correct syntax
2. **Edit migration files** - Change `check=` to `condition=` in place (safe for same behavior)

**Recommended**: Edit migration files directly since `check` and `condition` are functionally identical.

---

### Phase 3: Django 6.0 Breaking Changes to Review

#### 3.1 DEFAULT_AUTO_FIELD (Already Configured)
Your project already sets `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"` in settings.py. No action needed.

#### 3.2 Database Backend Changes
- MariaDB 10.5 dropped (you use PostgreSQL - OK)
- `as_sql()` methods must return params as tuple not list (only affects custom lookups)

#### 3.3 Python Version
Django 6.0+ requires Python 3.12+. Your Dockerfile already uses `python:3.12-slim`. OK.

#### 3.4 Email Changes (Not Applicable)
No `send_mail()` or email functions found in codebase.

#### 3.5 Model.save() Positional Arguments (OK)
All `.save()` calls in the codebase use keyword arguments. No changes needed.

---

### Phase 4: Django 6.1 Specific Changes

#### 4.1 Features Removed in 6.1 (from 5.2 deprecations)

| Deprecated Feature | Status in Codebase |
|-------------------|-------------------|
| `staticfiles.finders.find(all=)` | Not used |
| `auth.login()` fallback to `request.user` | Not used |
| PostgreSQL `ArrayAgg/JSONBAgg/StringAgg(ordering=)` | Not used |
| `RemoteUserMiddleware.process_request()` override | Not used |

**Result**: No additional changes required for 6.1-specific removals.

#### 4.2 New Features in 6.1 (Optional)
- **Field fetch modes** - New `FETCH_PEERS` mode for batch field fetching
- **JSONNull expression** - Explicit JSON null representation
- **DecimalField** - `max_digits`/`decimal_places` now optional on PostgreSQL

---

### Phase 5: Upgrade Execution Steps ✅ COMPLETED

**Executed 2025-12-29:**
- Django 6.0 installed successfully
- DRF 3.16.1 works with Django 6.0 (official 3.17 support not yet released)
- All 325 tests ran: **323 passed, 2 failed** (pre-existing test issues, not Django-related)

**Installed versions:**
```
Django==6.0
djangorestframework==3.16.1
channels==4.3.2
daphne==4.2.1
django-environ==0.12.0
django-cors-headers==4.9.0
paho-mqtt==2.1.0
```

**Test fixes applied:**
- `test_status_endpoint_warms_cache_from_active_profile` - Added `@override_settings(ALLOW_HOME_ASSISTANT_IN_TESTS=True)` and profile cleanup
- `test_websocket_receives_alarm_state_updates` - Drain both initial WS messages (`alarm_state` + `system_status`)

**Final test results: 325 tests passed ✅**

---

### Phase 5 (Original Plan): Upgrade Execution Steps

#### Step 1: Create upgrade branch
```bash
git checkout -b feature/django-6.1-upgrade
```

#### Step 2: Update CheckConstraint syntax in models
Change `check=` to `condition=` in all 8 locations listed above.

#### Step 3: Update migration files
Change `check=` to `condition=` in `accounts/migrations/0001_initial.py`.

#### Step 4: Update requirements.txt
```diff
- Django>=5.0,<6.0
+ Django>=6.1,<7.0
- djangorestframework>=3.15
+ djangorestframework>=3.16
- channels>=4.0
+ channels>=4.2
- django-environ>=0.11
+ django-environ>=0.12
- django-cors-headers>=4.3
+ django-cors-headers>=4.6
```

#### Step 5: Run checks
```bash
pip install -r requirements.txt
python manage.py check
python manage.py makemigrations --check --dry-run
```

#### Step 6: Run full test suite
```bash
python manage.py test
```

#### Step 7: Test manually
- Test all alarm state transitions
- Test user authentication flows
- Test WebSocket connections (Channels)
- Test admin interface

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Third-party package incompatibility | Medium | High | Pin exact versions, test thoroughly |
| Migration conflicts | Low | Medium | Run `makemigrations --check` before deploy |
| Channels/ASGI issues | Low | High | Test WebSocket functionality extensively |
| Subtle ORM behavior changes | Low | Medium | Full test suite coverage |

---

## Rollback Plan

1. Keep Django 5.x branch available
2. Database migrations are backwards-compatible (constraint rename is cosmetic)
3. Pin requirements.txt to exact working versions after upgrade

---

## Checklist

- [x] Update CheckConstraint syntax in `accounts/models.py`
- [x] Update CheckConstraint syntax in `alarm/models.py`
- [x] Update CheckConstraint syntax in `locks/models.py`
- [x] Update `accounts/migrations/0001_initial.py`
- [x] Update `requirements.txt` with new versions
- [x] Run `python manage.py check`
- [x] Run `python manage.py makemigrations --check`
- [x] Run full test suite (325 tests passing)
- [x] Test WebSocket functionality (via test suite)
- [x] Test authentication flows (via test suite)
- [x] Test alarm state machine (via test suite)
- [x] Update Dockerfile if needed (Python 3.12 already in use)
- [ ] Deploy to staging environment
- [ ] Production deployment

## Future Upgrades

- **DRF 3.17**: Update `requirements.txt` when released on PyPI (Django 6.0 support merged but not released)
- **Django 6.1**: Upgrade when released (no additional code changes expected)

---

## References

- [Django 6.0 Release Notes](https://docs.djangoproject.com/en/6.0/releases/6.0/)
- [Django 6.1 Release Notes](https://docs.djangoproject.com/en/dev/releases/6.1/)
- [Django Deprecation Timeline](https://docs.djangoproject.com/en/dev/internals/deprecation/)
- [Django REST Framework Changelog](https://www.django-rest-framework.org/community/release-notes/)
- [Channels Release Notes](https://channels.readthedocs.io/en/latest/releases/)
