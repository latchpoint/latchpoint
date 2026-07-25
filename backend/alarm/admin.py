from django.contrib import admin
from django.db import transaction

from . import models
from .signals import settings_profile_changed


def _notify_settings_profile_changed(profile_id: int, reason: str) -> None:
    """Fire ``settings_profile_changed`` on commit, matching what the settings views do.

    Admin writes bypass the views and use cases that normally send this signal, so
    without it the process-local settings snapshots — ``alarm.system_status`` and the
    Zigbee2MQTT / Frigate ingest caches added by ADR-0103 — keep serving stale values
    until the process restarts. Editing the ``frigate`` or ``zigbee2mqtt`` entry here
    changes ingest behavior, so a silent cache is a real footgun.
    """
    transaction.on_commit(lambda: settings_profile_changed.send(sender=None, profile_id=profile_id, reason=reason))


@admin.register(models.AlarmSettingsProfile)
class AlarmSettingsProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        _notify_settings_profile_changed(obj.pk, "activated" if obj.is_active else "updated")


@admin.register(models.AlarmSettingsEntry)
class AlarmSettingsEntryAdmin(admin.ModelAdmin):
    list_display = ("profile", "key", "value_type", "updated_at")
    list_filter = ("value_type",)
    search_fields = ("key", "profile__name")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        _notify_settings_profile_changed(obj.profile_id, "updated")

    def delete_model(self, request, obj):
        # Read profile_id before the delete clears it; removing an entry reverts that
        # setting to its registry default, which the caches must observe too.
        profile_id = obj.profile_id
        super().delete_model(request, obj)
        _notify_settings_profile_changed(profile_id, "updated")

    def delete_queryset(self, request, queryset):
        profile_ids = sorted(set(queryset.values_list("profile_id", flat=True)))
        super().delete_queryset(request, queryset)
        for profile_id in profile_ids:
            _notify_settings_profile_changed(profile_id, "updated")


@admin.register(models.AlarmSystem)
class AlarmSystemAdmin(admin.ModelAdmin):
    list_display = ("name", "timezone", "created_at", "updated_at")


@admin.register(models.AlarmStateSnapshot)
class AlarmStateSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "current_state",
        "previous_state",
        "target_armed_state",
        "entered_at",
        "exit_at",
    )
    list_filter = ("current_state",)


@admin.register(models.AlarmEvent)
class AlarmEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "state_from", "state_to", "timestamp")
    list_filter = ("event_type", "state_to")


@admin.register(models.Sensor)
class SensorAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "is_entry_point")
    list_filter = ("is_active", "is_entry_point")


@admin.register(models.SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "value_type", "modified_by", "updated_at")
    list_filter = ("value_type",)
    search_fields = ("key", "name")
