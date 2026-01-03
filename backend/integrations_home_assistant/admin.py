from django.contrib import admin

from integrations_home_assistant import models


class HasErrorFilter(admin.SimpleListFilter):
    title = "Has error"
    parameter_name = "has_error"

    def lookups(self, request, model_admin):
        """Provide filter options for rows with/without errors."""
        return [
            ("yes", "Yes"),
            ("no", "No"),
        ]

    def queryset(self, request, queryset):
        """Filter rows by whether an error timestamp exists."""
        value = self.value()
        if value == "yes":
            return queryset.filter(last_error_at__isnull=False)
        if value == "no":
            return queryset.filter(last_error_at__isnull=True)
        return queryset


@admin.register(models.HomeAssistantMqttAlarmEntityStatus)
class HomeAssistantMqttAlarmEntityStatusAdmin(admin.ModelAdmin):
    ordering = ("-updated_at",)
    list_select_related = ("profile",)
    list_display = (
        "profile",
        "last_discovery_publish_at",
        "last_state_publish_at",
        "last_availability_publish_at",
        "last_error_at",
        "updated_at",
    )
    list_filter = (HasErrorFilter,)
    search_fields = ("profile__name",)
