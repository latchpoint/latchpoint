from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.fields import CIEmailField
from django.contrib.postgres.operations import CreateExtension
from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def seed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.bulk_create(
        [
            Role(slug="admin", name="Admin", description="Full administrative access"),
            Role(slug="resident", name="Resident", description="Resident access"),
            Role(slug="guest", name="Guest", description="Guest access"),
            Role(slug="service", name="Service", description="Service access"),
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        CreateExtension("citext"),
        migrations.CreateModel(
            name="Role",
            fields=[
                ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                ("slug", models.CharField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
            ],
            options={
                "ordering": ["slug"],
            },
        ),
        migrations.CreateModel(
            name="User",
            fields=[
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, db_column="last_login_at", null=True)),
                ("is_superuser", models.BooleanField(default=False)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", CIEmailField(unique=True)),
                ("first_name", models.CharField(blank=True, max_length=150)),
                ("last_name", models.CharField(blank=True, max_length=150)),
                ("display_name", models.CharField(blank=True, max_length=150)),
                ("timezone", models.CharField(default="UTC", max_length=64)),
                ("locale", models.CharField(default="en", max_length=32)),
                ("access_expires_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("is_staff", models.BooleanField(default=False)),
                ("onboarding_completed_at", models.DateTimeField(blank=True, null=True)),
                ("failed_login_attempts", models.PositiveIntegerField(default=0)),
                ("locked_until", models.DateTimeField(blank=True, null=True)),
                ("password_updated_at", models.DateTimeField(default=timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "groups",
                    models.ManyToManyField(
                        blank=True,
                        related_name="user_set",
                        related_query_name="user",
                        to="auth.group",
                    ),
                ),
                (
                    "user_permissions",
                    models.ManyToManyField(
                        blank=True,
                        related_name="user_set",
                        related_query_name="user",
                        to="auth.permission",
                    ),
                ),
            ],
            options={
                "ordering": ["email"],
                "verbose_name": "user",
                "verbose_name_plural": "users",
            },
        ),
        migrations.CreateModel(
            name="UserCode",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("code_hash", models.TextField()),
                ("label", models.CharField(blank=True, max_length=150)),
                (
                    "code_type",
                    models.CharField(
                        choices=[
                            ("permanent", "Permanent"),
                            ("temporary", "Temporary"),
                            ("one_time", "One-time"),
                            ("service", "Service"),
                        ],
                        max_length=16,
                    ),
                ),
                ("pin_length", models.PositiveSmallIntegerField()),
                ("is_active", models.BooleanField(default=True)),
                ("max_uses", models.PositiveIntegerField(blank=True, null=True)),
                ("uses_count", models.PositiveIntegerField(default=0)),
                ("start_at", models.DateTimeField(blank=True, null=True)),
                ("end_at", models.DateTimeField(blank=True, null=True)),
                ("days_of_week", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("window_start", models.TimeField(blank=True, null=True)),
                ("window_end", models.TimeField(blank=True, null=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("last_entry_point", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="codes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="UserTOTPDevice",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("label", models.CharField(blank=True, max_length=150)),
                ("secret_encrypted", models.BinaryField()),
                ("is_active", models.BooleanField(default=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="totp_devices",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="UserRoleAssignment",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "assigned_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="granted_role_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "role",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name="user_assignments",
                        to="accounts.role",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="role_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="UserCodeAllowedState",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("disarmed", "Disarmed"),
                            ("armed_home", "Armed home"),
                            ("armed_away", "Armed away"),
                            ("armed_night", "Armed night"),
                            ("armed_vacation", "Armed vacation"),
                            ("armed_custom_bypass", "Armed custom bypass"),
                            ("pending", "Pending"),
                            ("triggered", "Triggered"),
                        ],
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "code",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="allowed_states",
                        to="accounts.usercode",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="user",
            index=models.Index(fields=["last_login"], name="accounts_us_last_lo_3b1484_idx"),
        ),
        migrations.AddIndex(
            model_name="user",
            index=models.Index(fields=["is_active"], name="accounts_us_is_act_4ef7b3_idx"),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=Q(("failed_login_attempts__gte", 0)),
                name="users_failed_login_attempts_gte_0",
            ),
        ),
        migrations.AddIndex(
            model_name="usercode",
            index=models.Index(fields=["user"], name="accounts_us_user_i_11b38c_idx"),
        ),
        migrations.AddIndex(
            model_name="usercode",
            index=models.Index(
                condition=Q(("is_active", True)),
                fields=["user"],
                name="user_codes_active_user_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="usercode",
            index=models.Index(
                condition=Q(("end_at__isnull", False)),
                fields=["end_at"],
                name="user_codes_end_at_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="usercode",
            constraint=models.CheckConstraint(
                condition=Q(("pin_length__gte", 4), ("pin_length__lte", 8)),
                name="user_codes_pin_length_between_4_8",
            ),
        ),
        migrations.AddConstraint(
            model_name="usercode",
            constraint=models.CheckConstraint(
                condition=Q(("days_of_week__isnull", True))
                | (Q(("days_of_week__gte", 0)) & Q(("days_of_week__lte", 127))),
                name="user_codes_days_of_week_between_0_127",
            ),
        ),
        migrations.AddConstraint(
            model_name="usercode",
            constraint=models.CheckConstraint(
                condition=Q(("uses_count__gte", 0)),
                name="user_codes_uses_count_gte_0",
            ),
        ),
        migrations.AddIndex(
            model_name="userroleassignment",
            index=models.Index(fields=["role"], name="accounts_us_role_i_39c574_idx"),
        ),
        migrations.AddConstraint(
            model_name="userroleassignment",
            constraint=models.UniqueConstraint(
                fields=("user", "role"), name="user_role_assignments_unique_user_role"
            ),
        ),
        migrations.AddIndex(
            model_name="usercodeallowedstate",
            index=models.Index(fields=["state"], name="accounts_us_state__fc4a74_idx"),
        ),
        migrations.AddConstraint(
            model_name="usercodeallowedstate",
            constraint=models.UniqueConstraint(
                fields=("code", "state"),
                name="user_code_allowed_states_unique_code_state",
            ),
        ),
        migrations.AddIndex(
            model_name="usertotpdevice",
            index=models.Index(fields=["user", "is_active"], name="accounts_us_user_i_27c326_idx"),
        ),
        migrations.RunPython(code=seed_roles, reverse_code=migrations.RunPython.noop),
    ]
