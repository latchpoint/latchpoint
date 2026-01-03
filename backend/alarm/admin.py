from django.contrib import admin

from . import models


@admin.register(models.AlarmSettingsProfile)
class AlarmSettingsProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(models.AlarmSettingsEntry)
class AlarmSettingsEntryAdmin(admin.ModelAdmin):
    list_display = ("profile", "key", "value_type", "updated_at")
    list_filter = ("value_type",)
    search_fields = ("key", "profile__name")


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
