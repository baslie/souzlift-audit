"""Utility helpers for sending account-related email notifications."""
from __future__ import annotations

from typing import Iterable, Sequence

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.urls import reverse

from .models import UserProfile


def _normalize_recipients(recipients: Iterable[str]) -> list[str]:
    """Return a cleaned list of email addresses."""

    normalized: list[str] = []
    for address in recipients:
        if not address:
            continue
        candidate = str(address).strip()
        if candidate:
            normalized.append(candidate)
    return normalized


def send_plain_email(subject: str, message: str, recipients: Sequence[str]) -> int:
    """Send a plain-text email if recipients are provided."""

    if not getattr(settings, "EMAIL_NOTIFICATIONS_ENABLED", False):
        return 0
    normalized = _normalize_recipients(recipients)
    if not normalized:
        return 0
    return send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, normalized)


def get_active_admin_emails() -> list[str]:
    """Return emails of active administrators."""

    UserModel = get_user_model()
    queryset = (
        UserModel._default_manager.filter(
            is_active=True,
            profile__role=UserProfile.Roles.ADMIN,
        )
        .exclude(email__isnull=True)
        .exclude(email__exact="")
        .values_list("email", flat=True)
        .distinct()
    )
    return [str(address) for address in queryset]


def send_user_created_email(user: object, *, temporary_password: str | None = None) -> None:
    """Notify a user about the newly created account."""

    email = getattr(user, "email", "") or ""
    if not email.strip():
        return

    username = getattr(user, "get_username", None)
    if callable(username):
        username_value = username()
    else:
        username_value = getattr(user, "username", "")

    full_name = getattr(user, "get_full_name", None)
    if callable(full_name):
        full_name_value = full_name()
    else:
        full_name_value = getattr(user, "full_name", "")

    greeting = full_name_value or username_value or "Уважаемый пользователь"

    login_path = reverse("accounts:login")

    lines = [
        f"Здравствуйте, {greeting}!",
        "",
        "Для вас создана учётная запись в системе «Союзлифт Аудит».",
        f"Имя пользователя: {username_value}",
        f"Страница входа: {login_path}",
    ]

    if temporary_password:
        lines.append(f"Временный пароль: {temporary_password}")

    lines.append(
        "Если вы не получали пароль, обратитесь к администратору для его выдачи или смены."
    )

    message = "\n".join(lines)
    subject = "Создана учётная запись в Союзлифт Аудит"
    send_plain_email(subject, message, [email])


__all__ = [
    "get_active_admin_emails",
    "send_plain_email",
    "send_user_created_email",
]
