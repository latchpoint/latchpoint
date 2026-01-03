from __future__ import annotations

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Role,
    User,
    UserCode,
    UserCodeAllowedState,
    UserRoleAssignment,
    UserTOTPDevice,
)


class UserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Password confirmation", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email",)

    def clean_password2(self):
        """Validate password confirmation matches."""
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords do not match")
        return password2

    def save(self, commit=True):
        """Create the user, hashing the provided password."""
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm

    list_display = ("email", "display_name", "is_staff", "is_active", "last_login")
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("email", "first_name", "last_name", "display_name")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("first_name", "last_name", "display_name", "timezone", "locale")}),
        ("Access", {"fields": ("is_active", "is_staff", "is_superuser", "access_expires_at")}),
        ("Security", {"fields": ("failed_login_attempts", "locked_until", "password_updated_at")}),
        ("Important dates", {"fields": ("last_login", "onboarding_completed_at", "created_at", "updated_at")}),
        ("Permissions", {"fields": ("groups", "user_permissions")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "is_staff", "is_superuser", "is_active"),
            },
        ),
    )
    readonly_fields = ("last_login", "created_at", "updated_at", "password_updated_at")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("slug", "name")
    search_fields = ("slug", "name")


@admin.register(UserRoleAssignment)
class UserRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "assigned_by", "created_at")
    list_filter = ("role",)
    search_fields = ("user__email", "role__slug")
    autocomplete_fields = ("user", "role", "assigned_by")


@admin.register(UserCode)
class UserCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "code_type", "is_active", "uses_count", "end_at")
    list_filter = ("code_type", "is_active")
    search_fields = ("user__email", "label")
    autocomplete_fields = ("user",)
    readonly_fields = ("uses_count", "last_used_at", "created_at", "updated_at")


@admin.register(UserCodeAllowedState)
class UserCodeAllowedStateAdmin(admin.ModelAdmin):
    list_display = ("code", "state", "created_at")
    list_filter = ("state",)
    autocomplete_fields = ("code",)


@admin.register(UserTOTPDevice)
class UserTOTPDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "is_active", "confirmed_at", "last_used_at")
    list_filter = ("is_active",)
    search_fields = ("user__email", "label")
    autocomplete_fields = ("user",)
