from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ReviewStatus(models.TextChoices):
    """Common moderation statuses for catalog records."""

    PENDING = "pending", _("Ожидает проверки")
    APPROVED = "approved", _("Подтверждён")
    REJECTED = "rejected", _("Отклонён")


class Building(models.Model):
    """Справочник зданий, доступных аудиторам."""

    address = models.CharField(
        _("Адрес"),
        max_length=255,
        help_text=_("Улица и номер дома."),
    )
    entrance = models.CharField(
        _("Подъезд"),
        max_length=50,
        blank=True,
        help_text=_("Дополнительные указания: номер подъезда, корпус и т.п."),
    )
    notes = models.TextField(
        _("Примечания"),
        blank=True,
        help_text=_("Особенности объекта или дополнительные комментарии."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="buildings_created",
        verbose_name=_("Автор"),
        help_text=_("Пользователь, добавивший запись."),
    )
    created_at = models.DateTimeField(
        _("Дата создания"),
        auto_now_add=True,
        help_text=_("Когда запись была создана."),
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="buildings_verified",
        verbose_name=_("Подтвердил"),
        help_text=_("Администратор, утвердивший запись."),
    )
    verified_at = models.DateTimeField(
        _("Дата подтверждения"),
        null=True,
        blank=True,
        help_text=_("Когда администратор проверил запись."),
    )
    review_status = models.CharField(
        _("Статус модерации"),
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        help_text=_("Определяет доступность записи для других пользователей."),
    )

    class Meta:
        verbose_name = _("Здание")
        verbose_name_plural = _("Здания")
        ordering = ["address", "entrance"]
        constraints = [
            models.UniqueConstraint(
                fields=["address", "entrance"],
                condition=models.Q(review_status=ReviewStatus.APPROVED),
                name="unique_approved_building_address",
            )
        ]

    def __str__(self) -> str:
        if self.entrance:
            return f"{self.address}, подъезд {self.entrance}"
        return self.address


class Elevator(models.Model):
    """Справочник лифтов, привязанных к зданиям."""

    class Status(models.TextChoices):
        IN_SERVICE = "in_service", _("В эксплуатации")
        OUT_OF_SERVICE = "out_of_service", _("Не работает")
        UNDER_MAINTENANCE = "under_maintenance", _("На обслуживании")
        DECOMMISSIONED = "decommissioned", _("Списан")

    building = models.ForeignKey(
        Building,
        on_delete=models.PROTECT,
        related_name="elevators",
        verbose_name=_("Здание"),
        help_text=_("Объект, в котором расположен лифт."),
    )
    identifier = models.CharField(
        _("Идентификатор"),
        max_length=64,
        help_text=_("Заводской номер или внутренний идентификатор."),
    )
    description = models.TextField(
        _("Описание"),
        blank=True,
        help_text=_("Дополнительная информация о лифте."),
    )
    status = models.CharField(
        _("Статус"),
        max_length=32,
        choices=Status.choices,
        default=Status.IN_SERVICE,
        help_text=_("Текущее состояние лифта."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="elevators_created",
        verbose_name=_("Автор"),
        help_text=_("Пользователь, добавивший запись."),
    )
    created_at = models.DateTimeField(
        _("Дата создания"),
        auto_now_add=True,
        help_text=_("Когда запись была создана."),
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="elevators_verified",
        verbose_name=_("Подтвердил"),
        help_text=_("Администратор, утвердивший запись."),
    )
    verified_at = models.DateTimeField(
        _("Дата подтверждения"),
        null=True,
        blank=True,
        help_text=_("Когда администратор проверил запись."),
    )
    review_status = models.CharField(
        _("Статус модерации"),
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        help_text=_("Определяет доступность записи для других пользователей."),
    )

    class Meta:
        verbose_name = _("Лифт")
        verbose_name_plural = _("Лифты")
        ordering = ["building__address", "identifier"]
        constraints = [
            models.UniqueConstraint(
                fields=["building", "identifier"],
                condition=models.Q(review_status=ReviewStatus.APPROVED),
                name="unique_approved_elevator_identifier",
            )
        ]

    def __str__(self) -> str:
        return f"{self.identifier} ({self.building})"
