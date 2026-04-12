from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class AuditLog(TimeStampedModel):
    class ActorType(models.TextChoices):
        USER = "user", "User"
        SYSTEM = "system", "System"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        CRITICAL = "critical", "Critical"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    actor_type = models.CharField(
        max_length=20,
        choices=ActorType.choices,
        default=ActorType.USER,
    )
    action = models.CharField(max_length=100)
    target_app_label = models.CharField(max_length=50, blank=True)
    target_model = models.CharField(max_length=50, blank=True)
    target_object_id = models.CharField(max_length=64, blank=True)
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        default=Severity.INFO,
    )
    message = models.TextField(blank=True)
    remote_addr = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action"]),
            models.Index(fields=["severity"]),
            models.Index(fields=["target_app_label", "target_model"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} ({self.severity})"

    @classmethod
    def record(
        cls,
        *,
        action: str,
        actor=None,
        actor_type: str = ActorType.USER,
        severity: str = Severity.INFO,
        target_app_label: str = "",
        target_model: str = "",
        target_object_id: str = "",
        message: str = "",
        remote_addr: str | None = None,
        request_id: str = "",
        metadata: dict | None = None,
    ):
        return cls.objects.create(
            actor=actor,
            actor_type=actor_type,
            action=action,
            severity=severity,
            target_app_label=target_app_label,
            target_model=target_model,
            target_object_id=target_object_id,
            message=message,
            remote_addr=remote_addr,
            request_id=request_id,
            metadata=metadata or {},
        )

