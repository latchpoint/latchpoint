"""
Django admin configuration for notification providers.
"""

from django.contrib import admin

from .models import NotificationDelivery, NotificationLog, NotificationProvider


@admin.register(NotificationProvider)
class NotificationProviderAdmin(admin.ModelAdmin):
    """Admin for NotificationProvider model."""

    list_display = [
        "name",
        "provider_type",
        "is_enabled",
        "profile",
        "created_at",
        "updated_at",
    ]
    list_filter = ["provider_type", "is_enabled", "profile"]
    search_fields = ["name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["name"]

    fieldsets = [
        (None, {"fields": ["id", "name", "provider_type", "is_enabled"]}),
        ("Configuration", {"fields": ["config"], "classes": ["collapse"]}),
        ("Metadata", {"fields": ["profile", "created_at", "updated_at"]}),
    ]


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    """Admin for NotificationLog model."""

    list_display = [
        "created_at",
        "provider_name",
        "provider_type",
        "status",
        "message_preview",
        "rule_name",
    ]
    list_filter = ["status", "provider_type", "created_at"]
    search_fields = ["provider_name", "message_preview", "rule_name"]
    readonly_fields = [
        "id",
        "provider",
        "provider_name",
        "provider_type",
        "status",
        "message_preview",
        "error_message",
        "error_code",
        "rule_name",
        "created_at",
    ]
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        """Logs are created automatically, not manually."""
        return False

    def has_change_permission(self, request, obj=None):
        """Logs are immutable."""
        return False


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    """Admin for NotificationDelivery outbox."""

    list_display = [
        "created_at",
        "profile",
        "provider_key",
        "status",
        "attempt_count",
        "max_attempts",
        "next_attempt_at",
        "sent_at",
        "rule_name",
    ]
    list_filter = ["status", "created_at", "sent_at", "profile"]
    search_fields = ["provider_key", "rule_name", "message", "idempotency_key"]
    readonly_fields = [
        "id",
        "profile",
        "provider",
        "provider_key",
        "message",
        "title",
        "data",
        "rule_name",
        "status",
        "attempt_count",
        "max_attempts",
        "next_attempt_at",
        "locked_at",
        "last_attempt_at",
        "sent_at",
        "last_error_code",
        "last_error_message",
        "idempotency_key",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False
