from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

MAX_ATTACHMENT_SIZE_BYTES: Final[int] = 8 * 1024 * 1024
MAX_ATTACHMENTS_PER_RESPONSE: Final[int] = 10
MAX_ATTACHMENTS_PER_AUDIT: Final[int] = 100


@dataclass(frozen=True)
class AttachmentLimits:
    """Convenience container exposing limits to templates and services."""

    max_per_response: int = MAX_ATTACHMENTS_PER_RESPONSE
    max_per_audit: int = MAX_ATTACHMENTS_PER_AUDIT
    max_size_bytes: int = MAX_ATTACHMENT_SIZE_BYTES


class Audit(models.Model):
    """Прохождение чек-листа аудитора по конкретному лифту."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Черновик")
        IN_PROGRESS = "in_progress", _("В работе")
        SUBMITTED = "submitted", _("Отправлен")
        REVIEWED = "reviewed", _("Просмотрен")

    elevator = models.ForeignKey(
        "catalog.Elevator",
        on_delete=models.PROTECT,
        related_name="audits",
        verbose_name=_("Лифт"),
        help_text=_("Объект проверки."),
    )
    object_info = models.JSONField(
        _("Информационная карта"),
        blank=True,
        default=dict,
        help_text=_("Снимок пользовательских полей объекта на момент проверки."),
    )
    planned_date = models.DateField(
        _("Плановая дата"),
        null=True,
        blank=True,
        help_text=_("Дата, на которую была запланирована проверка."),
    )
    started_at = models.DateTimeField(
        _("Начато"),
        null=True,
        blank=True,
        help_text=_("Фактическое время начала аудита."),
    )
    finished_at = models.DateTimeField(
        _("Завершено"),
        null=True,
        blank=True,
        help_text=_("Фактическое время завершения аудита."),
    )
    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        help_text=_("Жизненный цикл аудита."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audits_created",
        verbose_name=_("Автор"),
        help_text=_("Пользователь, инициировавший аудит."),
    )
    created_at = models.DateTimeField(
        _("Создан"),
        auto_now_add=True,
        help_text=_("Когда аудит был создан."),
    )
    updated_at = models.DateTimeField(
        _("Обновлён"),
        auto_now=True,
        help_text=_("Когда запись аудита последний раз изменялась."),
    )
    total_score = models.PositiveIntegerField(
        _("Суммарный балл"),
        default=0,
        help_text=_("Агрегированная сумма баллов по ответам."),
    )

    class Meta:
        verbose_name = _("Аудит")
        verbose_name_plural = _("Аудиты")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        planned = self.planned_date.strftime("%Y-%m-%d") if self.planned_date else _("без даты")
        return f"{self.elevator} — {planned}"


class AuditResponse(models.Model):
    """Ответ аудитора на конкретный вопрос чек-листа."""

    audit = models.ForeignKey(
        "audits.Audit",
        on_delete=models.CASCADE,
        related_name="responses",
        verbose_name=_("Аудит"),
        help_text=_("Проверка, к которой относится ответ."),
    )
    question = models.ForeignKey(
        "catalog.ChecklistQuestion",
        on_delete=models.PROTECT,
        related_name="audit_responses",
        verbose_name=_("Вопрос"),
        help_text=_("Позиция чек-листа."),
    )
    score = models.IntegerField(
        _("Баллы"),
        null=True,
        blank=True,
        help_text=_("Выбранный балл или значение для вопроса."),
    )
    comment = models.TextField(
        _("Комментарий"),
        blank=True,
        help_text=_("Пояснение аудитора."),
    )
    is_flagged = models.BooleanField(
        _("Требует внимания"),
        default=False,
        help_text=_("Дополнительная пометка для администратора."),
    )
    is_offline_cached = models.BooleanField(
        _("Получен офлайн"),
        default=False,
        help_text=_("Отмечает ответы, пришедшие из офлайн-синхронизации."),
    )
    created_at = models.DateTimeField(
        _("Создан"),
        auto_now_add=True,
        help_text=_("Когда ответ был сохранён впервые."),
    )
    updated_at = models.DateTimeField(
        _("Обновлён"),
        auto_now=True,
        help_text=_("Когда ответ последний раз изменялся."),
    )

    class Meta:
        verbose_name = _("Ответ аудита")
        verbose_name_plural = _("Ответы аудита")
        constraints = [
            models.UniqueConstraint(
                fields=["audit", "question"],
                name="unique_question_per_audit",
            )
        ]

    def __str__(self) -> str:
        return f"{self.audit_id}:{self.question_id}"


def attachment_upload_to(instance: "AuditAttachment", filename: str) -> str:
    """Структурируем хранение файлов вложений по аудитам."""

    audit_id = instance.response.audit_id if instance.response_id else "pending"
    response_id = instance.response_id or "pending"
    return f"audits/{audit_id}/responses/{response_id}/{filename}"


class AuditAttachment(models.Model):
    """Фотографии и файлы, прикреплённые к ответу."""

    response = models.ForeignKey(
        "audits.AuditResponse",
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name=_("Ответ"),
        help_text=_("Ответ, к которому прикреплён файл."),
    )
    file = models.ImageField(
        _("Файл"),
        upload_to=attachment_upload_to,
        help_text=_("Вложение с подтверждающими материалами."),
    )
    caption = models.CharField(
        _("Описание"),
        max_length=255,
        blank=True,
        help_text=_("Краткое пояснение к вложению."),
    )
    offline_uuid = models.UUIDField(
        _("Offline UUID"),
        blank=True,
        null=True,
        unique=True,
        help_text=_("Временный идентификатор до синхронизации."),
    )
    stored_size = models.PositiveIntegerField(
        _("Размер файла, байт"),
        editable=False,
        help_text=_("Фактический размер вложения."),
    )
    uploaded_at = models.DateTimeField(
        _("Загружено"),
        auto_now_add=True,
        help_text=_("Когда файл был загружен."),
    )

    class Meta:
        verbose_name = _("Вложение аудита")
        verbose_name_plural = _("Вложения аудита")
        indexes = [models.Index(fields=["uploaded_at"])]

    def __str__(self) -> str:
        return f"Attachment #{self.pk} for response {self.response_id}"

    def clean(self) -> None:
        super().clean()

        errors: dict[str, list[ValidationError]] = {}

        if self.file and hasattr(self.file, "size"):
            if self.file.size > MAX_ATTACHMENT_SIZE_BYTES:
                errors.setdefault("file", []).append(
                    ValidationError(
                        _("Размер файла превышает ограничение в 8 МБ."),
                    ),
                )

        if self.response_id:
            response_qs = AuditAttachment.objects.filter(response=self.response)
            if self.pk:
                response_qs = response_qs.exclude(pk=self.pk)
            response_count = response_qs.count()
            if response_count >= MAX_ATTACHMENTS_PER_RESPONSE:
                errors.setdefault("response", []).append(
                    ValidationError(
                        _("Для одного вопроса доступно не более %(limit)d вложений."),
                        params={"limit": MAX_ATTACHMENTS_PER_RESPONSE},
                    ),
                )

            audit_qs = AuditAttachment.objects.filter(response__audit=self.response.audit)
            if self.pk:
                audit_qs = audit_qs.exclude(pk=self.pk)
            audit_count = audit_qs.count()
            if audit_count >= MAX_ATTACHMENTS_PER_AUDIT:
                errors.setdefault("response__audit", []).append(
                    ValidationError(
                        _("Для одного аудита доступно не более %(limit)d вложений."),
                        params={"limit": MAX_ATTACHMENTS_PER_AUDIT},
                    ),
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        if self.file and hasattr(self.file, "size"):
            self.stored_size = int(self.file.size)
        else:
            self.stored_size = 0
        super().save(*args, **kwargs)


def signature_upload_to(instance: "AuditSignature", filename: str) -> str:
    """Store signature images next to the audit folder."""

    audit_id = instance.audit_id or "pending"
    return f"audits/{audit_id}/signature/{filename}"


class AuditSignature(models.Model):
    """Подпись ответственного лица по завершённому аудиту."""

    audit = models.OneToOneField(
        "audits.Audit",
        on_delete=models.CASCADE,
        related_name="signature",
        verbose_name=_("Аудит"),
    )
    signed_by = models.CharField(
        _("Подписант"),
        max_length=255,
        help_text=_("ФИО или должность лица, подтвердившего аудит."),
    )
    signature_image = models.ImageField(
        _("Подпись"),
        upload_to=signature_upload_to,
        help_text=_("Изображение подписи."),
    )
    signed_at = models.DateTimeField(
        _("Дата подписи"),
        default=timezone.now,
        help_text=_("Когда была оставлена подпись."),
    )

    class Meta:
        verbose_name = _("Подпись аудита")
        verbose_name_plural = _("Подписи аудита")

    def __str__(self) -> str:
        return f"Signature for audit {self.audit_id}"
