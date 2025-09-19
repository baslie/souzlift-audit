from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ReviewStatus(models.TextChoices):
    """Common moderation statuses for catalog records."""

    PENDING = "pending", _("Ожидает проверки")
    APPROVED = "approved", _("Подтверждён")
    REJECTED = "rejected", _("Отклонён")


class ModeratedQuerySet(models.QuerySet):
    """QuerySet helpers for models moderated by administrators."""

    def approved(self) -> "ModeratedQuerySet":
        return self.filter(review_status=ReviewStatus.APPROVED)

    def pending(self) -> "ModeratedQuerySet":
        return self.filter(review_status=ReviewStatus.PENDING)

    def rejected(self) -> "ModeratedQuerySet":
        return self.filter(review_status=ReviewStatus.REJECTED)

    def visible_for_user(self, user: object) -> "ModeratedQuerySet":
        """Restrict queryset according to moderation rules."""

        if not getattr(user, "is_authenticated", False):
            return self.approved()

        profile = getattr(user, "profile", None)
        if profile is not None and getattr(profile, "is_admin", False):
            return self

        visibility_filter = models.Q(review_status=ReviewStatus.APPROVED)
        if profile is not None and getattr(profile, "is_auditor", False):
            visibility_filter |= models.Q(created_by=profile.user)
        elif getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            visibility_filter |= models.Q(created_by=user)

        return self.filter(visibility_filter)

    def for_moderation(self) -> "ModeratedQuerySet":
        """Return a queue ordered by creation time for administrator review."""

        return self.pending().order_by("created_at")


class ModeratedManager(models.Manager.from_queryset(ModeratedQuerySet)):
    """Default manager exposing moderation helpers."""

    pass


class ModerationMixin:
    """Behavior shared by moderated catalog models."""

    def _set_review_status(
        self,
        status: str,
        *,
        reviewer: object | None = None,
        commit: bool = True,
    ) -> None:
        """Internal helper that updates moderation state and metadata."""

        update_fields: set[str] = {"review_status"}
        self.review_status = status

        if status == ReviewStatus.PENDING:
            if self.verified_by_id is not None:  # type: ignore[attr-defined]
                self.verified_by = None  # type: ignore[assignment]
                update_fields.add("verified_by")
            if self.verified_at is not None:
                self.verified_at = None
                update_fields.add("verified_at")
        else:
            if reviewer is None:
                raise ValueError("Reviewer must be provided when approving or rejecting a record.")
            self.verified_by = reviewer  # type: ignore[assignment]
            self.verified_at = timezone.now()
            update_fields.update({"verified_by", "verified_at"})

        if commit:
            self.save(update_fields=sorted(update_fields))

    def approve(self, reviewer: object, *, commit: bool = True) -> None:
        """Mark the record as approved by administrator."""

        self._set_review_status(ReviewStatus.APPROVED, reviewer=reviewer, commit=commit)

    def reject(self, reviewer: object, *, commit: bool = True) -> None:
        """Mark the record as rejected by administrator."""

        self._set_review_status(ReviewStatus.REJECTED, reviewer=reviewer, commit=commit)

    def send_to_review(self, *, commit: bool = True) -> None:
        """Return the record to moderation queue (pending status)."""

        self._set_review_status(ReviewStatus.PENDING, reviewer=None, commit=commit)


class Building(ModerationMixin, models.Model):
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

    objects = ModeratedManager()

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


class Elevator(ModerationMixin, models.Model):
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

    objects = ModeratedManager()

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
