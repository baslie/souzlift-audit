"""Email notifications for audit-related events."""
from __future__ import annotations

from typing import TYPE_CHECKING

from django.urls import reverse

from accounts.emails import get_active_admin_emails, send_plain_email

if TYPE_CHECKING:  # pragma: no cover - used for type checking only
    from .models import Audit, OfflineSyncBatch


def _format_user_label(user: object | None) -> str:
    """Return a readable representation of a user for emails."""

    if user is None:
        return "неизвестный пользователь"

    full_name = getattr(user, "get_full_name", None)
    if callable(full_name):
        full_name_value = full_name()
        if full_name_value:
            return full_name_value

    username = getattr(user, "get_username", None)
    if callable(username):
        username_value = username()
        if username_value:
            return username_value

    return str(user)


def notify_audit_submitted(audit: "Audit") -> None:
    """Notify administrators that an audit was submitted by an auditor."""

    recipients = get_active_admin_emails()
    if not recipients:
        return

    subject = f"Аудит отправлен: {audit}"
    admin_url = reverse("admin:audits_audit_change", args=[audit.pk])
    author = _format_user_label(getattr(audit, "created_by", None))
    message_lines = [
        "Аудитор отправил новый аудит и ожидает проверки.",
        "",
        f"Идентификатор аудита: {audit.pk}",
        f"Объект: {audit.elevator}",
        f"Автор: {author}",
        f"Текущий статус: {audit.get_status_display()}",
        "",
        f"Открыть в админ-панели: {admin_url}",
    ]
    send_plain_email(subject, "\n".join(message_lines), recipients)


def notify_audit_reviewed(audit: "Audit") -> None:
    """Inform the auditor that their audit was reviewed by an administrator."""

    author = getattr(audit, "created_by", None)
    email = getattr(author, "email", "") or ""
    if not email.strip():
        return

    subject = f"Аудит просмотрен: {audit}"
    admin_url = reverse("admin:audits_audit_change", args=[audit.pk])
    message_lines = [
        "Ваш аудит был рассмотрен администратором.",
        "",
        f"Идентификатор аудита: {audit.pk}",
        f"Объект: {audit.elevator}",
        f"Текущий статус: {audit.get_status_display()}",
        "",
        "Вы можете открыть запись в административной панели, если у вас есть соответствующие права.",
        f"Ссылка: {admin_url}",
    ]
    send_plain_email(subject, "\n".join(message_lines), [email])


def notify_audit_changes_requested(
    audit: "Audit", message: str, *, actor: object | None = None
) -> None:
    """Inform the auditor that an administrator requested additional changes."""

    author = getattr(audit, "created_by", None)
    email = getattr(author, "email", "") or ""
    if not email.strip():
        return

    subject = f"Запрошены правки: {audit}"
    actor_label = _format_user_label(actor)
    portal_url = reverse("audits:audit-list")
    message_lines = [
        "Администратор запросил внести изменения в аудит.",
        "",
        f"Идентификатор аудита: {audit.pk}",
        f"Объект: {audit.elevator}",
        f"Администратор: {actor_label}",
        "",
        "Комментарий администратора:",
        message,
        "",
        f"Текущий статус: {audit.get_status_display()}",
        f"Список аудитов: {portal_url}",
    ]
    send_plain_email(subject, "\n".join(message_lines), [email])


def notify_offline_sync_error(batch: "OfflineSyncBatch") -> None:
    """Notify administrators about an offline synchronisation error."""

    recipients = get_active_admin_emails()
    if not recipients:
        return

    actor = _format_user_label(getattr(batch, "user", None))
    subject = f"Ошибка офлайн-синхронизации: устройство {batch.device_id}"
    message_lines = [
        "Во время офлайн-синхронизации произошла ошибка.",
        "",
        f"Пакет: {batch.pk}",
        f"Пользователь: {actor}",
        f"Устройство: {batch.device_id}",
        f"HTTP-статус: {batch.response_status}",
    ]

    details = getattr(batch, "error_details", None)
    if isinstance(details, dict) and details:
        message_lines.append("")
        message_lines.append("Сведения об ошибке:")
        for key, value in details.items():
            message_lines.append(f"- {key}: {value}")

    send_plain_email(subject, "\n".join(message_lines), recipients)


__all__ = [
    "notify_audit_changes_requested",
    "notify_audit_reviewed",
    "notify_audit_submitted",
    "notify_offline_sync_error",
]
