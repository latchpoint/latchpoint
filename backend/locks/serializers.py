from __future__ import annotations

from rest_framework import serializers

from .models import DoorCode, DoorCodeLockAssignment


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
    lock_assignments = serializers.SerializerMethodField()
    lock_entity_ids = serializers.SerializerMethodField()

    class Meta:
        model = DoorCode
        fields = (
            "id",
            "user_id",
            "user_display_name",
            "label",
            "code_type",
            "pin_length",
            "is_active",
            "max_uses",
            "uses_count",
            "start_at",
            "end_at",
            "days_of_week",
            "window_start",
            "window_end",
            "last_used_at",
            "last_used_lock",
            "lock_assignments",
            "lock_entity_ids",
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
            raise serializers.ValidationError(
                {"max_uses": "One-time codes automatically expire after one use."}
            )

        if start_at and end_at and start_at > end_at:
            raise serializers.ValidationError(
                {"end_at": "end_at must be after or equal to start_at."}
            )

        if days_of_week is not None:
            if days_of_week < 0 or days_of_week > 127:
                raise serializers.ValidationError(
                    {"days_of_week": "days_of_week must be between 0 and 127."}
                )
            if days_of_week == 0:
                raise serializers.ValidationError(
                    {"days_of_week": "Select at least one day."}
                )

        if (window_start is None) != (window_end is None):
            raise serializers.ValidationError(
                {"window_start": "window_start and window_end must be set together."}
            )

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

    def validate(self, attrs):
        """Validate updates, including time-range edits for eligible code types only."""
        attrs = super().validate(attrs)
        instance: DoorCode | None = getattr(self, "instance", None)
        if instance is None:
            return attrs

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
        if start_at and end_at and start_at > end_at:
            raise serializers.ValidationError(
                {"end_at": "end_at must be after or equal to start_at."}
            )

        days_of_week = attrs.get("days_of_week", instance.days_of_week)
        if days_of_week is not None:
            if days_of_week < 0 or days_of_week > 127:
                raise serializers.ValidationError(
                    {"days_of_week": "days_of_week must be between 0 and 127."}
                )
            if days_of_week == 0:
                raise serializers.ValidationError(
                    {"days_of_week": "Select at least one day."}
                )

        window_start = attrs.get("window_start", instance.window_start)
        window_end = attrs.get("window_end", instance.window_end)
        if (window_start is None) != (window_end is None):
            raise serializers.ValidationError(
                {"window_start": "window_start and window_end must be set together."}
            )
        if window_start is not None and window_end is not None and window_start >= window_end:
            raise serializers.ValidationError(
                {"window_end": "window_end must be after window_start (same-day window)."}
            )

        return attrs
