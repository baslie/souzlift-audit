from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .storages import protected_media_storage
from .tokens import build_attachment_token

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

    _STATUS_TRANSITIONS: Final[dict[str, tuple[str, ...]]] = {
        Status.DRAFT: (Status.IN_PROGRESS,),
        Status.IN_PROGRESS: (Status.SUBMITTED,),
        Status.SUBMITTED: (Status.REVIEWED,),
        Status.REVIEWED: (),
    }
    _STATUS_REQUIRING_STARTED_AT: Final[tuple[str, ...]] = (
        Status.IN_PROGRESS,
        Status.SUBMITTED,
        Status.REVIEWED,
    )
    _STATUS_REQUIRING_FINISHED_AT: Final[tuple[str, ...]] = (
        Status.SUBMITTED,
        Status.REVIEWED,
    )

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

    def _prepare_status_transition(
        self,
        previous_status: str | None,
        *,
        previous_started_at: datetime | None,
        previous_finished_at: datetime | None,
    ) -> set[str]:
        """Validate status changes and ensure timestamps are in sync."""

        changed_fields: set[str] = set()
        new_status = self.status or self.Status.DRAFT

        if previous_status is not None and new_status != previous_status:
            allowed = self._STATUS_TRANSITIONS.get(previous_status, ())
            if new_status not in allowed:
                current_label = self.Status(previous_status).label
                target_label = self.Status(new_status).label
                raise ValidationError(
                    {
                        "status": ValidationError(
                            _("Нельзя изменить статус аудита с «%(current)s» на «%(target)s»."),
                            params={"current": current_label, "target": target_label},
                        )
                    }
                )

        now = timezone.now()

        if new_status in self._STATUS_REQUIRING_STARTED_AT:
            if self.started_at is None:
                if previous_started_at is not None:
                    self.started_at = previous_started_at
                else:
                    self.started_at = now
                changed_fields.add("started_at")
        elif new_status == self.Status.DRAFT and self.started_at is not None and previous_status is None:
            # A brand new draft can carry a custom timestamp provided by caller.
            pass

        if new_status in self._STATUS_REQUIRING_FINISHED_AT:
            if self.finished_at is None:
                if previous_finished_at is not None:
                    self.finished_at = previous_finished_at
                else:
                    self.finished_at = now
                changed_fields.add("finished_at")
        elif new_status in (self.Status.DRAFT, self.Status.IN_PROGRESS) and self.finished_at is not None:
            # Prevent accidental clearing of completion timestamp by reverting to cached value.
            if previous_finished_at is not None:
                self.finished_at = previous_finished_at
            else:
                self.finished_at = None
            if self.finished_at is None:
                changed_fields.add("finished_at")

        if self.started_at and self.finished_at and self.finished_at < self.started_at:
            raise ValidationError(
                {
                    "finished_at": ValidationError(
                        _("Дата завершения не может быть раньше даты начала."),
                    )
                }
            )

        return changed_fields

    def save(self, *args: object, **kwargs: object) -> None:
        update_fields_param = kwargs.get("update_fields")
        update_fields: set[str] | None
        if update_fields_param is None:
            update_fields = None
        else:
            update_fields = set(update_fields_param)

        fields_requiring_status_check = {"status", "started_at", "finished_at"}
        should_check_status = self.pk is None or update_fields is None or bool(
            fields_requiring_status_check & update_fields
        )

        previous_status: str | None = None
        previous_started_at: datetime | None = None
        previous_finished_at: datetime | None = None

        if self.pk and should_check_status:
            persisted = (
                Audit.objects.only("status", "started_at", "finished_at")
                .filter(pk=self.pk)
                .first()
            )
            if persisted is not None:
                previous_status = persisted.status
                previous_started_at = persisted.started_at
                previous_finished_at = persisted.finished_at

        if should_check_status:
            changed_fields = self._prepare_status_transition(
                previous_status,
                previous_started_at=previous_started_at,
                previous_finished_at=previous_finished_at,
            )
            if update_fields is not None and changed_fields:
                update_fields.update(changed_fields)

        if update_fields is not None:
            kwargs["update_fields"] = sorted(update_fields)

        super().save(*args, **kwargs)

    def start(self, *, commit: bool = True) -> None:
        """Перевести аудит в статус «В работе» и зафиксировать время старта."""

        self.status = self.Status.IN_PROGRESS
        if commit:
            if self.pk is None:
                self.save()
            else:
                self.save(update_fields=["status"])

    def submit(self, *, commit: bool = True) -> None:
        """Перевести аудит в статус «Отправлен» и зафиксировать завершение."""

        self.status = self.Status.SUBMITTED
        if commit:
            if self.pk is None:
                self.save()
            else:
                self.save(update_fields=["status"])

    def mark_reviewed(self, *, commit: bool = True) -> None:
        """Отметить аудит как просмотренный администратором."""

        self.status = self.Status.REVIEWED
        if commit:
            if self.pk is None:
                self.save()
            else:
                self.save(update_fields=["status"])

    def recalculate_total_score(self, *, commit: bool = True) -> int:
        """Aggregate score across responses and optionally persist the result."""

        aggregated = self.responses.aggregate(total=models.Sum("score"))
        total = int(aggregated.get("total") or 0)
        self.total_score = total

        if commit and self.pk:
            now = timezone.now()
            Audit.objects.filter(pk=self.pk).update(total_score=total, updated_at=now)
            self.updated_at = now

        return total

    @classmethod
    def recalculate_total_score_for(cls, audit_id: int) -> int:
        """Recalculate aggregated score for a specific audit by identifier."""

        aggregated = AuditResponse.objects.filter(audit_id=audit_id).aggregate(total=models.Sum("score"))
        total = int(aggregated.get("total") or 0)
        now = timezone.now()
        cls.objects.filter(pk=audit_id).update(total_score=total, updated_at=now)
        return total


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

    def save(self, *args: object, **kwargs: object) -> None:
        update_fields_param = kwargs.get("update_fields")
        update_fields: set[str] | None
        if update_fields_param is None:
            update_fields = None
        else:
            update_fields = set(update_fields_param)

        previous_audit_id: int | None = None
        if self.pk:
            previous_audit = (
                AuditResponse.objects.only("audit_id").filter(pk=self.pk).first()
            )
            if previous_audit is not None:
                previous_audit_id = previous_audit.audit_id

        super().save(*args, **kwargs)

        if previous_audit_id and previous_audit_id != self.audit_id:
            Audit.recalculate_total_score_for(previous_audit_id)

        should_recalculate = (
            update_fields is None or bool({"audit", "score"} & update_fields)
        )
        if should_recalculate and self.audit_id:
            self.audit.recalculate_total_score()

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        audit = self.audit
        audit_id = self.audit_id
        result = super().delete(*args, **kwargs)
        if audit_id:
            audit.recalculate_total_score()
        return result


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
        storage=protected_media_storage,
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

    def get_download_token(self) -> str:
        """Сформировать подписанный токен для скачивания вложения."""

        if not self.pk:
            raise ValueError("Нельзя сформировать ссылку для несохранённого вложения.")
        return build_attachment_token(self.pk)

    def get_download_url(self) -> str:
        """Получить защищённый URL для скачивания вложения."""

        token = self.get_download_token()
        return reverse("audits:attachment-download", kwargs={"token": token})

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
        storage=protected_media_storage,
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
