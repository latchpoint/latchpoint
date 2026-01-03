from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone as django_timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    display_name = models.CharField(max_length=150, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    locale = models.CharField(max_length=32, default="en")
    access_expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    password_updated_at = models.DateTimeField(default=django_timezone.now)
    last_login = models.DateTimeField(null=True, blank=True, db_column="last_login_at")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["email"]
        verbose_name = "user"
        verbose_name_plural = "users"
        indexes = [
            models.Index(fields=["last_login"]),
            models.Index(fields=["is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(failed_login_attempts__gte=0),
                name="users_failed_login_attempts_gte_0",
            ),
            models.UniqueConstraint(
                Lower("email"),
                name="users_email_ci_unique",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a human-friendly identifier for logs/admin lists."""
        return self.email

    @property
    def full_name(self) -> str:
        """Return a best-effort full name based on first/last name."""
        return f"{self.first_name} {self.last_name}".strip()

    def save(self, *args, **kwargs):
        """Normalize email casing/format before saving."""
        if self.email:
            self.email = self.__class__.objects.normalize_email(self.email)
        super().save(*args, **kwargs)


class Role(models.Model):
    id = models.SmallAutoField(primary_key=True)
    slug = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return the role slug for logs/admin lists."""
        return self.slug


class UserRoleAssignment(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="role_assignments"
    )
    role = models.ForeignKey(
        Role, on_delete=models.PROTECT, related_name="user_assignments"
    )
    assigned_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="granted_role_assignments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role"], name="user_role_assignments_unique_user_role"
            ),
        ]
        indexes = [models.Index(fields=["role"])]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.user_id}:{self.role_id}"


class UserCode(models.Model):
    class CodeType(models.TextChoices):
        PERMANENT = "permanent", "Permanent"
        TEMPORARY = "temporary", "Temporary"
        ONE_TIME = "one_time", "One-time"
        SERVICE = "service", "Service"

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="codes")
    code_hash = models.TextField()
    label = models.CharField(max_length=150, blank=True)
    code_type = models.CharField(max_length=16, choices=CodeType.choices)
    pin_length = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(4), MaxValueValidator(8)]
    )
    is_active = models.BooleanField(default=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    uses_count = models.PositiveIntegerField(default=0)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    days_of_week = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(127)]
    )
    window_start = models.TimeField(null=True, blank=True)
    window_end = models.TimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_entry_point = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(
                fields=["user"],
                condition=Q(is_active=True),
                name="user_codes_active_user_idx",
            ),
            models.Index(
                fields=["end_at"],
                condition=Q(end_at__isnull=False),
                name="user_codes_end_at_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(pin_length__gte=4) & Q(pin_length__lte=8),
                name="user_codes_pin_length_between_4_8",
            ),
            models.CheckConstraint(
                condition=Q(days_of_week__isnull=True)
                | (Q(days_of_week__gte=0) & Q(days_of_week__lte=127)),
                name="user_codes_days_of_week_between_0_127",
            ),
            models.CheckConstraint(
                condition=Q(uses_count__gte=0),
                name="user_codes_uses_count_gte_0",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.user_id}:{self.label or self.id}"


class UserCodeAllowedState(models.Model):
    class AlarmState(models.TextChoices):
        DISARMED = "disarmed", "Disarmed"
        ARMED_HOME = "armed_home", "Armed home"
        ARMED_AWAY = "armed_away", "Armed away"
        ARMED_NIGHT = "armed_night", "Armed night"
        ARMED_VACATION = "armed_vacation", "Armed vacation"
        ARMED_CUSTOM_BYPASS = "armed_custom_bypass", "Armed custom bypass"
        PENDING = "pending", "Pending"
        TRIGGERED = "triggered", "Triggered"

    id = models.BigAutoField(primary_key=True)
    code = models.ForeignKey(
        UserCode, on_delete=models.CASCADE, related_name="allowed_states"
    )
    state = models.CharField(max_length=32, choices=AlarmState.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["code", "state"], name="user_code_allowed_states_unique_code_state"
            ),
        ]
        indexes = [models.Index(fields=["state"])]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.code_id}:{self.state}"


class UserTOTPDevice(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="totp_devices")
    label = models.CharField(max_length=150, blank=True)
    secret_encrypted = models.BinaryField()
    is_active = models.BooleanField(default=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["user", "is_active"])]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.user_id}:{self.label or self.id}"
