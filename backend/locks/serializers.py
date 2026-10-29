from __future__ import annotations

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
        """Return sorted lock entity ids, requiring `lock_assignments` to be prefetched."""
        prefetched = getattr(obj, "_prefetched_objects_cache", {}) or {}
        if "lock_assignments" not in prefetched:
            raise RuntimeError("DoorCode.lock_assignments must be prefetched for serialization.")
        return sorted({assignment.lock_entity_id for assignment in obj.lock_assignments.all()})

    def get_lock_slot_assignments(self, obj: DoorCode) -> list[dict]:
        """Return per-lock slot programming state for the UI push-status badge (ADR 0092).

        ``pending_removal`` is set for a lock the code is being dropped from whose
        slot clear hasn't worked yet. Its assignment stays until it does (issue
        #139), and only listing it again in ``lock_entity_ids`` on an update keeps
        it on the code (issue #151).
        """
        prefetched = getattr(obj, "_prefetched_objects_cache", {}) or {}
        if "lock_assignments" not in prefetched:
            raise RuntimeError("DoorCode.lock_assignments must be prefetched for serialization.")
        removing = {f.lock_entity_id for f in self._clear_failures(obj) if f.removing}
        return [
            {
                "lock_entity_id": assignment.lock_entity_id,
                "slot_index": assignment.slot_index,
                "pending_removal": assignment.lock_entity_id in removing,
            }
            for assignment in obj.lock_assignments.all()
        ]

    def get_pending_slot_clears(self, obj: DoorCode) -> list[dict]:
        """Slot clears still outstanding, as ``{lock_entity_id, slot_index, removing}`` (issue #151). No PINs."""
        from locks.use_cases.lock_push import pending_slot_clears

        return pending_slot_clears(door_code=obj, failures=self._clear_failures(obj))

    def get_validity(self, obj: DoorCode) -> str:
        """``scheduled``, ``valid``, ``expired`` or ``exhausted``, from the code's dates and uses (issue #145)."""
        return validity(obj, now=_validation_now(self))

    def _clear_failures(self, obj: DoorCode) -> list:
        """``unresolved_clear_failures`` for ``obj``, loaded once per code for both fields above."""
        from locks.use_cases.lock_push import unresolved_clear_failures

        cache = self.__dict__.setdefault("_clear_failures_cache", {})
        if obj.pk not in cache:
            cache[obj.pk] = unresolved_clear_failures(door_code=obj)
        return cache[obj.pk]


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
        }
    )

    def validate(self, attrs):
        """Validate updates, including time-range edits for eligible code types only."""
        attrs = super().validate(attrs)
        instance: DoorCode | None = getattr(self, "instance", None)
        if instance is None:
            return attrs

        if instance.source == DoorCode.Source.SYNCED:
            disallowed = self._SYNCED_READONLY_FIELDS & attrs.keys()
            if disallowed:
                raise serializers.ValidationError(
                    {field: "This field cannot be modified on synced codes." for field in sorted(disallowed)}
                )

        # An expired code stays off until it's turned on with a later end_at, and
        # moving end_at later on its own doesn't turn it back on (issue #145).
        # Only a new end_at has to be in the future: the edit form sends both
        # dates when either changes, so an expired code's unchanged one comes back.
        now = _validation_now(self)
        if "end_at" in attrs and attrs["end_at"] != instance.end_at and ended_by(attrs["end_at"], now=now):
            raise serializers.ValidationError({"end_at": _END_AT_IN_PAST})
        if attrs.get("is_active") is True and ended_by(attrs.get("end_at", instance.end_at), now=now):
            raise serializers.ValidationError({"is_active": _ACTIVE_WHEN_EXPIRED})

        updates_time_range = any(
            key in attrs for key in ["start_at", "end_at", "days_of_week", "window_start", "window_end"]
        )
        if not updates_time_range:
            return attrs

        if instance.code_type not in (DoorCode.CodeType.TEMPORARY, DoorCode.CodeType.ONE_TIME):
            raise serializers.ValidationError(
                {"code_type": "Only temporary or one-time codes can set an active time range."}
            )

        start_at = attrs.get("start_at", instance.start_at)
        end_at = attrs.get("end_at", instance.end_at)
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
