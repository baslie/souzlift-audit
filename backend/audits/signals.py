"""Signal handlers for audit notifications."""
from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from .emails import notify_audit_reviewed, notify_audit_submitted
from .models import Audit


@receiver(post_save, sender=Audit)
def trigger_audit_status_notifications(
    sender: type[Audit], instance: Audit, created: bool, **_: Any
) -> None:
    """Send email notifications when audit status changes."""

    previous_status = getattr(instance, "_previous_status", None)
    status_changed = getattr(instance, "_status_changed", created)

    actor = getattr(instance, "_log_actor", None)

    if created:
        if instance.status == Audit.Status.SUBMITTED:
            notify_audit_submitted(instance)
        return

    if not status_changed:
        return

    if instance.status == Audit.Status.SUBMITTED and previous_status != Audit.Status.SUBMITTED:
        notify_audit_submitted(instance)
    elif instance.status == Audit.Status.REVIEWED and previous_status != Audit.Status.REVIEWED:
        notify_audit_reviewed(instance, actor=actor)
