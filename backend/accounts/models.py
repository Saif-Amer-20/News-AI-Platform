from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class UserProfile(TimeStampedModel):
    class DefaultRole(models.TextChoices):
        ANALYST = "analyst", "Analyst"
        MANAGER = "manager", "Manager"
        OPS_OPERATOR = "ops_operator", "Operations Operator"
        PLATFORM_ADMIN = "platform_admin", "Platform Admin"

    class ClearanceLevel(models.TextChoices):
        INTERNAL = "internal", "Internal"
        RESTRICTED = "restricted", "Restricted"
        CONFIDENTIAL = "confidential", "Confidential"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    organization = models.CharField(max_length=150, blank=True)
    team_name = models.CharField(max_length=120, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    default_role = models.CharField(
        max_length=32,
        choices=DefaultRole.choices,
        default=DefaultRole.ANALYST,
    )
    clearance_level = models.CharField(
        max_length=32,
        choices=ClearanceLevel.choices,
        default=ClearanceLevel.INTERNAL,
    )
    is_on_call = models.BooleanField(default=False)
    preferences = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
        permissions = [
            ("manage_rbac", "Can manage platform RBAC bootstrap and role bindings"),
        ]

    def __str__(self) -> str:
        return f"Profile for {self.user.get_username()}"

