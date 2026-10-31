from __future__ import annotations

from datetime import timezone as dt_timezone

from cryptography.fernet import InvalidToken
from django.utils import timezone
from rest_framework import serializers

from alarm.crypto import SettingsEncryption

from .models import DoorCode, DoorCodeLockAssignment
from .use_cases.code_lifecycle import ended_by, validity

_END_AT_IN_PAST = "end_at must be in the future."
_ACTIVE_WHEN_EXPIRED = "This code has expired. Set a later end_at to turn it back on."
# end_at is exclusive, so a code that ends when it starts is never valid (issue #145).
_END_AT_NOT_AFTER_START = "end_at must be after start_at."
# A synced code's dates are only editable while it has an end_at, so clearing it
# would leave the code stuck the way it is (issue #189).
_SYNCED_END_AT_REQUIRED = "A synced code's end_at can be moved but not cleared."
_LOCK_CHANGES_WITH_FULL_LIST = "Send lock_entity_ids or add_lock_entity_ids/remove_lock_entity_ids, not both."
_LOCK_ADDED_AND_REMOVED = "A lock can't be added and removed in the same save."


def _same_minute(a, b) -> bool:
    """Whether two optional datetimes match to the minute. The edit form drops the seconds."""
    if a is None or b is None:
        return a is b
    return a.astimezone(dt_timezone.utc).replace(second=0, microsecond=0) == b.astimezone(dt_timezone.utc).replace(
        second=0, microsecond=0
    )


def _is_stored_date_sent_back(sent, stored) -> bool:
    """Whether a sent ``start_at`` or ``end_at`` is the stored one coming back unchanged (issue #189).

    That's the exact stored value, or the stored value cut to the minute, which
    is what the edit form sends since its input has no seconds. A value with
    seconds that isn't exactly the stored one is a real change from an API
    client, even inside the same minute.
    """
    if sent is None or stored is None:
        return sent is stored
    if sent == stored:
        return True
    return sent.second == 0 and sent.microsecond == 0 and _same_minute(sent, stored)


def _validation_now(serializer: serializers.Serializer):
    """The time the date checks compare against; tests can pin it with ``context["now"]``."""
    return serializer.context.get("now") or timezone.now()


class DoorCodeLockAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoorCodeLockAssignment
        fields = (
            "id",
            "lock_entity_id",
        )


class DoorCodeSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(read_only=True)
    user_display_name = serializers.SerializerMethodField()
    pin = serializers.SerializerMethodField()
    lock_assignments = serializers.SerializerMethodField()
    lock_entity_ids = serializers.SerializerMethodField()
    lock_slot_assignments = serializers.SerializerMethodField()
    pending_slot_clears = serializers.SerializerMethodField()
    validity = serializers.SerializerMethodField()

    class Meta:
        model = DoorCode
        fields = (
            "id",
            "user_id",
            "user_display_name",
            "source",
            "label",
            "code_type",
            "pin",
            "pin_length",
            "is_active",
            "max_uses",
            "uses_count",
            "start_at",
            "end_at",
            "days_of_week",
            "window_start",
            "window_end",
            "validity",
            "last_used_at",
            "last_used_lock",
            "lock_assignments",
            "lock_entity_ids",
            "lock_slot_assignments",
            "pending_slot_clears",
            "push_state",
            "last_push_attempt_at",
            "last_push_error",
            "created_at",
            "updated_at",
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["last_push_error"] = self._push_error_for_viewer(data.get("last_push_error"))
        return data

    def _push_error_for_viewer(self, message: str | None) -> str:
        """The push error, without the admin code hint unless the viewer is an admin (PR #198 review).

        A code's owner can view it, and the hint tells them their PIN may be the
        lock's admin code (issue #125). Without a ``request`` in the context the
        viewer is unknown, so the hint goes.
        """
        from accounts.policies import is_admin
        from locks.use_cases.lock_push import strip_admin_code_hint

        if "_viewer_is_admin" not in self.__dict__:
            request = self.context.get("request")
            self._viewer_is_admin = is_admin(getattr(request, "user", None))
        return (message or "") if self._viewer_is_admin else strip_admin_code_hint(message)

    def get_user_display_name(self, obj: DoorCode) -> str:
        """Return a display name for the code's user with fallbacks."""
        user = obj.user
        if getattr(user, "display_name", ""):
            return user.display_name
        full_name = getattr(user, "full_name", "") or ""
        if full_name.strip():
            return full_name.strip()
        return user.email

    def get_pin(self, obj: DoorCode) -> str | None:
        """Decrypt and return the PIN, or None if unavailable."""
        if not obj.encrypted_pin:
            return None
        try:
            return SettingsEncryption.get().decrypt(obj.encrypted_pin)
        except (ValueError, InvalidToken):
            return None

    def get_lock_assignments(self, obj: DoorCode) -> list[dict]:
        """Serialize lock assignments, requiring `lock_assignments` to be prefetched."""
        prefetched = getattr(obj, "_prefetched_objects_cache", {}) or {}
        if "lock_assignments" not in prefetched:
            raise RuntimeError("DoorCode.lock_assignments must be prefetched for serialization.")
        return [
            {
                "id": assignment.id,
                "lock_entity_id": assignment.lock_entity_id,
            }
            for assignment in obj.lock_assignments.all()
        ]

    def get_lock_entity_ids(self, obj: DoorCode) -> list[str]:
        """The code's locks, sorted, without the ones whose removal is still waiting on its clear (issue #171).

        Those keep their assignment until the clear works, and only listing the
        lock again on an update cancels the removal, so a client that sends this
        list back unchanged must not have them in it. They're still in
        ``lock_slot_assignments`` with ``pending_removal``, which is what the card
        and badge read. Requires ``lock_assignments`` to be prefetched.
        """
        prefetched = getattr(obj, "_prefetched_objects_cache", {}) or {}
        if "lock_assignments" not in prefetched:
            raise RuntimeError("DoorCode.lock_assignments must be prefetched for serialization.")
        removing = {f.lock_entity_id for f in self._clear_failures(obj) if f.removing}
        return sorted(
            {assignment.lock_entity_id for assignment in obj.lock_assignments.all()} - removing,
        )

    def get_lock_slot_assignments(self, obj: DoorCode) -> list[dict]:
        """Return per-lock slot programming state for the UI push-status badge (ADR 0092).

        ``pending_removal`` is set for a lock the code is being dropped from whose
        slot clear hasn't worked yet. Its assignment stays until it does (issue
        #139), and only listing it again in ``lock_entity_ids`` (or
        ``add_lock_entity_ids``) on an update keeps it on the code (issue #151).
        It's left out of ``lock_entity_ids`` (issue #171), so this is the list of
        every lock the code is on, being removed or not.

        Each lock also has its own ``push_state``, ``last_push_error``,
        ``last_push_attempt_at``, ``push_attempt_count`` and
        ``schedule_pending`` (the PIN is on the lock but its schedule isn't)
        (issues #126, #123). The code-level fields stay the rollup of these.
        ``push_requested_at`` is when a save or Retry queued a push of the lock
        (issue #124). ``push_queued`` says whether the queued push task would
        still push the lock now (``lock_push.push_queued``, issue #205), which the
        frontend can't work out on its own: it needs the TTL, the cap and the
        microseconds the JSON timestamps can lose in the browser. Never a PIN.
        """
        prefetched = getattr(obj, "_prefetched_objects_cache", {}) or {}
        if "lock_assignments" not in prefetched:
            raise RuntimeError("DoorCode.lock_assignments must be prefetched for serialization.")
        from locks.use_cases.lock_push import push_queued

        failures = self._clear_failures(obj)
        removing = {f.lock_entity_id for f in failures if f.removing}
        now = _validation_now(self)

        def queued(assignment: DoorCodeLockAssignment) -> bool:
            # The cap is only read for a lock with a request, so a page with
            # nothing queued costs no query for it.
            return assignment.push_requested_at is not None and push_queued(
                assignment, code=obj, now=now, max_attempts=self._push_max_attempts(), failures=failures
            )

        return [
            {
                "lock_entity_id": assignment.lock_entity_id,
                "slot_index": assignment.slot_index,
                "pending_removal": assignment.lock_entity_id in removing,
                "push_state": assignment.push_state,
                "last_push_error": self._push_error_for_viewer(assignment.last_push_error),
                "last_push_attempt_at": (
                    serializers.DateTimeField().to_representation(assignment.last_push_attempt_at)
                    if assignment.last_push_attempt_at
                    else None
                ),
                "push_attempt_count": assignment.push_attempt_count,
                "schedule_pending": assignment.schedule_pending,
                "push_requested_at": (
                    serializers.DateTimeField().to_representation(assignment.push_requested_at)
                    if assignment.push_requested_at
                    else None
                ),
                "push_queued": queued(assignment),
            }
            for assignment in obj.lock_assignments.all()
        ]

    def get_pending_slot_clears(self, obj: DoorCode) -> list[dict]:
        """Slot clears still outstanding, as ``{lock_entity_id, slot_index, removing}`` (issue #151). No PINs."""
        from locks.use_cases.lock_push import pending_slot_clears

        prefetch = self._pending_clears_prefetch(obj)
        if prefetch is not None:
            return prefetch.pending_slot_clears(obj)
        return pending_slot_clears(door_code=obj, failures=self._clear_failures(obj))

    def get_validity(self, obj: DoorCode) -> str:
        """``scheduled``, ``valid``, ``expired`` or ``exhausted``, from the code's dates and uses (issue #145)."""
        return validity(obj, now=_validation_now(self))

    def _pending_clears_prefetch(self, obj: DoorCode):
        """The list view's :class:`PendingClearsPrefetch` when it covers ``obj``, else ``None`` (issue #170)."""
        prefetch = self.context.get("pending_clears_prefetch")
        return prefetch if prefetch is not None and prefetch.covers(obj) else None

    def _clear_failures(self, obj: DoorCode) -> list:
        """``unresolved_clear_failures`` for ``obj``, loaded once per code for the fields above.

        From the list view's prefetch when there is one, so a page of codes
        costs the same few queries whatever its size (issue #170).
        """
        from locks.use_cases.lock_push import unresolved_clear_failures

        prefetch = self._pending_clears_prefetch(obj)
        if prefetch is not None:
            return prefetch.clear_failures(obj)
        cache = self.__dict__.setdefault("_clear_failures_cache", {})
        if obj.pk not in cache:
            cache[obj.pk] = unresolved_clear_failures(door_code=obj)
        return cache[obj.pk]

    def _push_max_attempts(self) -> int:
        """``door_codes.push_max_attempts``, read once per serializer, so once for a whole list."""
        if "_push_max_attempts_value" not in self.__dict__:
            from locks.tasks import _get_push_max_attempts

            self._push_max_attempts_value = _get_push_max_attempts()
        return self._push_max_attempts_value


class DoorCodePushSerializer(DoorCodeSerializer):
    class Meta(DoorCodeSerializer.Meta):
        fields = tuple(f for f in DoorCodeSerializer.Meta.fields if f != "pin")

    def get_pin(self, obj: DoorCode) -> None:  # pragma: no cover - field removed via Meta.fields
        return None


class DoorCodeCreateSerializer(serializers.Serializer):
    reauth_password = serializers.CharField(write_only=True)
    code = serializers.CharField(write_only=True)
    label = serializers.CharField(max_length=150, required=False, allow_blank=True)
    user_id = serializers.UUIDField(required=False)
    code_type = serializers.ChoiceField(
        required=False,
        choices=DoorCode.CodeType.choices,
        default=DoorCode.CodeType.PERMANENT,
    )
    start_at = serializers.DateTimeField(required=False, allow_null=True)
    end_at = serializers.DateTimeField(required=False, allow_null=True)
    days_of_week = serializers.IntegerField(required=False, allow_null=True)
    window_start = serializers.TimeField(required=False, allow_null=True)
    window_end = serializers.TimeField(required=False, allow_null=True)
    max_uses = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    lock_entity_ids = serializers.ListField(
        required=False,
        child=serializers.CharField(max_length=255),
        allow_empty=True,
    )

    def validate_code(self, value: str) -> str:
        """Validate and normalize a numeric PIN-style code."""
        code = (value or "").strip()
        if not code.isdigit():
            raise serializers.ValidationError("Code must be digits only.")
        if len(code) < 4 or len(code) > 8:
            raise serializers.ValidationError("Code must be 4 to 8 digits.")
        return code

    def validate(self, attrs):
        """Validate cross-field constraints for code types and time restrictions."""
        attrs = super().validate(attrs)
        code_type = attrs.get("code_type", DoorCode.CodeType.PERMANENT)
        start_at = attrs.get("start_at")
        end_at = attrs.get("end_at")
        days_of_week = attrs.get("days_of_week")
        window_start = attrs.get("window_start")
        window_end = attrs.get("window_end")
        max_uses = attrs.get("max_uses")

        time_restrictions = (
            start_at is not None
            or end_at is not None
            or days_of_week is not None
            or window_start is not None
            or window_end is not None
        )

        if code_type not in (DoorCode.CodeType.TEMPORARY, DoorCode.CodeType.ONE_TIME) and time_restrictions:
            raise serializers.ValidationError(
                {"code_type": "Only temporary or one-time codes can set an active time range."}
            )

        if code_type == DoorCode.CodeType.ONE_TIME and max_uses is not None:
            raise serializers.ValidationError({"max_uses": "One-time codes automatically expire after one use."})

        if start_at and end_at and start_at >= end_at:
            raise serializers.ValidationError({"end_at": _END_AT_NOT_AFTER_START})

        # A new code is always active, so one that's already expired would only be
        # turned off again by the scheduler (issue #145).
        if ended_by(end_at, now=_validation_now(self)):
            raise serializers.ValidationError({"end_at": _END_AT_IN_PAST})

        if days_of_week is not None:
            if days_of_week < 0 or days_of_week > 127:
                raise serializers.ValidationError({"days_of_week": "days_of_week must be between 0 and 127."})
            if days_of_week == 0:
                raise serializers.ValidationError({"days_of_week": "Select at least one day."})

        if (window_start is None) != (window_end is None):
            raise serializers.ValidationError({"window_start": "window_start and window_end must be set together."})

        if window_start is not None and window_end is not None and window_start >= window_end:
            raise serializers.ValidationError(
                {"window_end": "window_end must be after window_start (same-day window)."}
            )

        return attrs


class DoorCodeUpdateSerializer(serializers.Serializer):
    reauth_password = serializers.CharField(write_only=True)
    code = serializers.CharField(write_only=True, required=False)
    label = serializers.CharField(max_length=150, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    start_at = serializers.DateTimeField(required=False, allow_null=True)
    end_at = serializers.DateTimeField(required=False, allow_null=True)
    days_of_week = serializers.IntegerField(required=False, allow_null=True)
    window_start = serializers.TimeField(required=False, allow_null=True)
    window_end = serializers.TimeField(required=False, allow_null=True)
    max_uses = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    lock_entity_ids = serializers.ListField(
        required=False,
        child=serializers.CharField(max_length=255),
        allow_empty=True,
    )
    # Lock changes relative to what the code has when the save runs, so a tab
    # that hasn't refetched can't put back a lock another tab removed (issue #159).
    add_lock_entity_ids = serializers.ListField(
        required=False,
        child=serializers.CharField(max_length=255),
        allow_empty=True,
    )
    remove_lock_entity_ids = serializers.ListField(
        required=False,
        child=serializers.CharField(max_length=255),
        allow_empty=True,
    )

    def validate_code(self, value: str) -> str:
        """Validate and normalize a numeric PIN-style code."""
        code = (value or "").strip()
        if not code.isdigit():
            raise serializers.ValidationError("Code must be digits only.")
        if len(code) < 4 or len(code) > 8:
            raise serializers.ValidationError("Code must be 4 to 8 digits.")
        return code

    _SYNCED_READONLY_FIELDS = frozenset(
        {
            "code",
            "is_active",
            "start_at",
            "end_at",
            "days_of_week",
            "window_start",
            "window_end",
            "max_uses",
            "lock_entity_ids",
            "add_lock_entity_ids",
            "remove_lock_entity_ids",
        }
    )
    # What a synced code with an end_at can still edit (issues #145, #189).
    _SYNCED_VALIDITY_FIELDS = frozenset({"is_active", "start_at", "end_at"})

    @staticmethod
    def synced_validity_editable(code: DoorCode) -> bool:
        """Whether ``code`` is a synced code with an ``end_at``, whose active window and Active are editable.

        The scheduler retires synced codes at ``end_at`` like manual ones, and
        with every field read-only one could never come back on (issue #145).
        Once one is back on it also has to be possible to turn it off again or
        fix its window, ie while it's only waiting on its start (issue #189), so
        this holds whether it's on or off. Those can set ``is_active``,
        ``start_at`` and ``end_at`` with the manual rules, and their ``end_at``
        can be moved but not cleared, so they never drop out of this. Turning
        one on or off goes through the normal push and clear. It's keyed on the
        row, not on the retire event, since event retention would delete that
        and leave the code stuck. Synced codes without an ``end_at`` (the
        scheduler never turns those off) keep every field but ``label``
        read-only (ADR 0082), so lock sync stays the say for them.
        """
        return code.source == DoorCode.Source.SYNCED and code.end_at is not None

    @staticmethod
    def _validate_lock_changes(attrs) -> None:
        """Lock adds and removes don't go with ``lock_entity_ids`` or name the same lock (issue #159)."""
        added = set(attrs.get("add_lock_entity_ids") or ())
        removed = set(attrs.get("remove_lock_entity_ids") or ())
        if "lock_entity_ids" in attrs and ("add_lock_entity_ids" in attrs or "remove_lock_entity_ids" in attrs):
            raise serializers.ValidationError({"lock_entity_ids": _LOCK_CHANGES_WITH_FULL_LIST})
        if added & removed:
            raise serializers.ValidationError({"add_lock_entity_ids": _LOCK_ADDED_AND_REMOVED})

    def validate(self, attrs):
        """Validate updates, including time-range edits for eligible code types only."""
        attrs = super().validate(attrs)
        instance: DoorCode | None = getattr(self, "instance", None)
        if instance is None:
            return attrs

        synced_validity = self.synced_validity_editable(instance)
        if instance.source == DoorCode.Source.SYNCED:
            readonly = self._SYNCED_READONLY_FIELDS
            if synced_validity:
                readonly = readonly - self._SYNCED_VALIDITY_FIELDS
            disallowed = readonly & attrs.keys()
            if disallowed:
                raise serializers.ValidationError(
                    {field: "This field cannot be modified on synced codes." for field in sorted(disallowed)}
                )
            if "end_at" in attrs and attrs["end_at"] is None:
                raise serializers.ValidationError({"end_at": _SYNCED_END_AT_REQUIRED})

        self._validate_lock_changes(attrs)

        # The edit form sends both dates when either changes, without the
        # seconds, so a date that's the stored one cut to the minute is the
        # unchanged one coming back. It's dropped, so the stored value keeps its
        # seconds (a start cut to the minute would push the PIN up to 59s early).
        # Any other value is a change, a same-minute one with seconds included
        # (issue #189).
        sent_start_at = attrs.get("start_at", instance.start_at)
        sent_end_at = attrs.get("end_at", instance.end_at)
        for field in ("start_at", "end_at"):
            if field in attrs and _is_stored_date_sent_back(attrs[field], getattr(instance, field)):
                attrs.pop(field)
        dates_changed = "end_at" in attrs or "start_at" in attrs

        # An expired code stays off until it's turned on with a later end_at, and
        # moving end_at later on its own doesn't turn it back on (issue #145).
        # Only a new end_at has to be in the future.
        now = _validation_now(self)
        if "end_at" in attrs and ended_by(attrs["end_at"], now=now):
            raise serializers.ValidationError({"end_at": _END_AT_IN_PAST})
        if attrs.get("is_active") is True and ended_by(attrs.get("end_at", instance.end_at), now=now):
            raise serializers.ValidationError({"is_active": _ACTIVE_WHEN_EXPIRED})

        updates_time_range = any(
            key in attrs for key in ["start_at", "end_at", "days_of_week", "window_start", "window_end"]
        )
        if not updates_time_range:
            return attrs

        # Lock sync sets a synced code's code_type from the lock's schedule but
        # keeps its dates, so one that can edit them may be permanent.
        if not synced_validity and instance.code_type not in (DoorCode.CodeType.TEMPORARY, DoorCode.CodeType.ONE_TIME):
            raise serializers.ValidationError(
                {"code_type": "Only temporary or one-time codes can set an active time range."}
            )

        # Only checked when a date changes, so editing the days or time window
        # of an existing row whose dates are equal doesn't fail on them. Both the
        # dates that were sent and the dates that get stored are checked, since
        # a date sent back unchanged keeps its stored seconds, ie a start sent
        # with seconds can land after a stored end in the same minute (issue #189).
        if dates_changed:
            stored_start_at = attrs.get("start_at", instance.start_at)
            stored_end_at = attrs.get("end_at", instance.end_at)
            for start_at, end_at in ((sent_start_at, sent_end_at), (stored_start_at, stored_end_at)):
                if start_at and end_at and start_at >= end_at:
                    raise serializers.ValidationError({"end_at": _END_AT_NOT_AFTER_START})

        days_of_week = attrs.get("days_of_week", instance.days_of_week)
        if days_of_week is not None:
            if days_of_week < 0 or days_of_week > 127:
                raise serializers.ValidationError({"days_of_week": "days_of_week must be between 0 and 127."})
            if days_of_week == 0:
                raise serializers.ValidationError({"days_of_week": "Select at least one day."})

        window_start = attrs.get("window_start", instance.window_start)
        window_end = attrs.get("window_end", instance.window_end)
        if (window_start is None) != (window_end is None):
            raise serializers.ValidationError({"window_start": "window_start and window_end must be set together."})
        if window_start is not None and window_end is not None and window_start >= window_end:
            raise serializers.ValidationError(
                {"window_end": "window_end must be after window_start (same-day window)."}
            )

        return attrs


class LockConfigSyncRequestSerializer(serializers.Serializer):
    reauth_password = serializers.CharField(write_only=True)
    user_id = serializers.UUIDField()
