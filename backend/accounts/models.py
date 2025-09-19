from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserProfile(models.Model):
    """Дополнительные сведения о пользователе."""

    class Roles(models.TextChoices):
        AUDITOR = "AUDITOR", _("Аудитор")
        ADMIN = "ADMIN", _("Администратор")

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name=_("Пользователь"),
    )
    full_name = models.CharField(
        _("ФИО"),
        max_length=255,
        blank=True,
        help_text=_("Полное имя сотрудника."),
    )
    role = models.CharField(
        _("Роль"),
        max_length=20,
        choices=Roles.choices,
        default=Roles.AUDITOR,
        help_text=_("Определяет доступ к административным разделам."),
    )
    phone = models.CharField(
        _("Телефон"),
        max_length=32,
        blank=True,
        help_text=_("Контактный номер для связи."),
    )
    employee_id = models.CharField(
        _("Табельный номер"),
        max_length=64,
        blank=True,
        help_text=_("Внутренний идентификатор сотрудника."),
    )
    password_changed_at = models.DateTimeField(
        _("Дата смены пароля"),
        blank=True,
        null=True,
        help_text=_("Когда пользователь в последний раз менял пароль."),
    )

    class Meta:
        verbose_name = _("Профиль пользователя")
        verbose_name_plural = _("Профили пользователей")

    def __str__(self) -> str:
        if self.full_name:
            return self.full_name
        return str(self.user)

    @property
    def is_admin(self) -> bool:
        """Проверка, что профиль принадлежит администратору."""

        return self.role == self.Roles.ADMIN

    @property
    def is_auditor(self) -> bool:
        """Проверка, что профиль принадлежит аудитору."""

        return self.role == self.Roles.AUDITOR

    def mark_password_changed(self) -> None:
        """Обновить метку последней смены пароля."""

        self.password_changed_at = timezone.now()
        self.save(update_fields=["password_changed_at"])
