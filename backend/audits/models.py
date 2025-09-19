from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

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


def _consume_log_actor(instance: object) -> Any | None:
    """Return and clear actor attached to instance for logging purposes."""

    actor = getattr(instance, "_log_actor", None)
    if actor is not None:
        try:
            delattr(instance, "_log_actor")
        except AttributeError:
            pass
    return actor


def _serialize_datetime(value: datetime | None) -> str | None:
    """Serialize datetime values to ISO 8601 for JSON payloads."""

    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.isoformat()


def _serialize_date(value: date | None) -> str | None:
    """Serialize dates to ISO 8601 for JSON payloads."""

    if value is None:
        return None
    return value.isoformat()


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
        status_related_changes: set[str] = set()

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
            status_related_changes = self._prepare_status_transition(
                previous_status,
                previous_started_at=previous_started_at,
                previous_finished_at=previous_finished_at,
            )
            if update_fields is not None and status_related_changes:
                update_fields.update(status_related_changes)

        if update_fields is not None:
            kwargs["update_fields"] = sorted(update_fields)

        is_creation = self.pk is None
        status_changed = previous_status is not None and self.status != previous_status

        super().save(*args, **kwargs)

        log_actor = _consume_log_actor(self)

        if is_creation:
            AuditLogEntry.objects.log_action(
                action=AuditLogEntry.Action.AUDIT_CREATED,
                entity=self,
                user=log_actor or getattr(self, "created_by", None),
                payload={
                    "status": self.status,
                    "elevator_id": self.elevator_id,
                    "planned_date": _serialize_date(self.planned_date),
                    "started_at": _serialize_datetime(self.started_at),
                    "finished_at": _serialize_datetime(self.finished_at),
                },
            )
        elif status_changed:
            payload: dict[str, Any] = {
                "from": previous_status,
                "to": self.status,
            }
            if "started_at" in status_related_changes:
                payload["started_at"] = _serialize_datetime(self.started_at)
            if "finished_at" in status_related_changes:
                payload["finished_at"] = _serialize_datetime(self.finished_at)

            AuditLogEntry.objects.log_action(
                action=AuditLogEntry.Action.AUDIT_STATUS_CHANGED,
                entity=self,
                user=log_actor,
                payload=payload,
            )

    def start(self, *, actor: object | None = None, commit: bool = True) -> None:
        """Перевести аудит в статус «В работе» и зафиксировать время старта."""

        self.status = self.Status.IN_PROGRESS
        if actor is not None:
            self._log_actor = actor
        if commit:
            if self.pk is None:
                self.save()
            else:
                self.save(update_fields=["status"])

    def submit(self, *, actor: object | None = None, commit: bool = True) -> None:
        """Перевести аудит в статус «Отправлен» и зафиксировать завершение."""

        self.status = self.Status.SUBMITTED
        if actor is not None:
            self._log_actor = actor
        if commit:
            if self.pk is None:
                self.save()
            else:
                self.save(update_fields=["status"])

    def mark_reviewed(self, *, actor: object | None = None, commit: bool = True) -> None:
        """Отметить аудит как просмотренный администратором."""

        self.status = self.Status.REVIEWED
        if actor is not None:
            self._log_actor = actor
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

        creating = self.pk is None
        previous_state: dict[str, Any] | None = None
        previous_audit_id: int | None = None
        if not creating and self.pk:
            previous_state = (
                AuditResponse.objects.filter(pk=self.pk)
                .values("audit_id", "score", "comment", "is_flagged")
                .first()
            )
            if previous_state is not None:
                previous_audit_id = int(previous_state.get("audit_id") or 0) or None

        super().save(*args, **kwargs)

        log_actor = _consume_log_actor(self)
        if creating:
            AuditLogEntry.objects.log_action(
                action=AuditLogEntry.Action.RESPONSE_CREATED,
                entity=self,
                user=log_actor or getattr(self.audit, "created_by", None),
                payload={
                    "audit_id": self.audit_id,
                    "question_id": self.question_id,
                    "score": self.score,
                    "is_flagged": self.is_flagged,
                },
            )
        else:
            changes: dict[str, Any] = {}
            if previous_state is not None:
                for field in ("score", "comment", "is_flagged"):
                    previous_value = previous_state.get(field)
                    current_value = getattr(self, field)
                    if previous_value != current_value:
                        changes[field] = {
                            "from": previous_value,
                            "to": current_value,
                        }

            if changes:
                AuditLogEntry.objects.log_action(
                    action=AuditLogEntry.Action.RESPONSE_UPDATED,
                    entity=self,
                    user=log_actor or getattr(self.audit, "created_by", None),
                    payload={
                        "audit_id": self.audit_id,
                        "question_id": self.question_id,
                        "changes": changes,
                    },
                )

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
        response_id = self.pk
        payload = {
            "audit_id": audit_id,
            "question_id": self.question_id,
            "score": self.score,
        }
        log_actor = _consume_log_actor(self)
        result = super().delete(*args, **kwargs)
        if response_id is not None:
            AuditLogEntry.objects.log_action(
                action=AuditLogEntry.Action.RESPONSE_DELETED,
                entity=(self._meta.label_lower, response_id),
                user=log_actor or getattr(audit, "created_by", None),
                payload=payload,
            )
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
        creating = self._state.adding
        previous_state: dict[str, Any] | None = None
        if not creating and self.pk:
            previous_state = (
                AuditAttachment.objects.filter(pk=self.pk)
                .values("caption", "stored_size", "file")
                .first()
            )

        self.full_clean()
        if self.file and hasattr(self.file, "size"):
            self.stored_size = int(self.file.size)
        else:
            self.stored_size = 0
        super().save(*args, **kwargs)

        log_actor = _consume_log_actor(self)
        fallback_actor = getattr(self.response.audit, "created_by", None)

        if creating:
            AuditLogEntry.objects.log_action(
                action=AuditLogEntry.Action.ATTACHMENT_CREATED,
                entity=self,
                user=log_actor or fallback_actor,
                payload={
                    "response_id": self.response_id,
                    "filename": self.file.name,
                    "stored_size": self.stored_size,
                },
            )
        else:
            changes: dict[str, Any] = {}
            if previous_state is not None:
                if previous_state.get("caption") != self.caption:
                    changes["caption"] = {
                        "from": previous_state.get("caption"),
                        "to": self.caption,
                    }
                previous_file = previous_state.get("file")
                if previous_file != self.file.name:
                    changes["file"] = {
                        "from": previous_file,
                        "to": self.file.name,
                    }
                previous_size = previous_state.get("stored_size")
                if previous_size != self.stored_size:
                    changes["stored_size"] = {
                        "from": previous_size,
                        "to": self.stored_size,
                    }

            if changes:
                AuditLogEntry.objects.log_action(
                    action=AuditLogEntry.Action.ATTACHMENT_UPDATED,
                    entity=self,
                    user=log_actor or fallback_actor,
                    payload={
                        "response_id": self.response_id,
                        "changes": changes,
                    },
                )

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        attachment_id = self.pk
        payload = {
            "response_id": self.response_id,
            "filename": self.file.name,
            "stored_size": self.stored_size,
        }
        log_actor = _consume_log_actor(self)
        result = super().delete(*args, **kwargs)
        if attachment_id is not None:
            AuditLogEntry.objects.log_action(
                action=AuditLogEntry.Action.ATTACHMENT_DELETED,
                entity=(self._meta.label_lower, attachment_id),
                user=log_actor or fallback_actor,
                payload=payload,
            )
        return result


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

    def save(self, *args: object, **kwargs: object) -> None:
        creating = self._state.adding
        previous_state: dict[str, Any] | None = None
        if not creating and self.pk:
            previous_state = (
                AuditSignature.objects.filter(pk=self.pk)
                .values("signed_by", "signed_at")
                .first()
            )

        super().save(*args, **kwargs)

        log_actor = _consume_log_actor(self)
        fallback_actor = getattr(self.audit, "created_by", None)

        if creating:
            AuditLogEntry.objects.log_action(
                action=AuditLogEntry.Action.SIGNATURE_CREATED,
                entity=self,
                user=log_actor or fallback_actor,
                payload={
                    "audit_id": self.audit_id,
                    "signed_by": self.signed_by,
                    "signed_at": _serialize_datetime(self.signed_at),
                },
            )
        else:
            changes: dict[str, Any] = {}
            if previous_state is not None:
                if previous_state.get("signed_by") != self.signed_by:
                    changes["signed_by"] = {
                        "from": previous_state.get("signed_by"),
                        "to": self.signed_by,
                    }
                previous_signed_at = previous_state.get("signed_at")
                if previous_signed_at != self.signed_at:
                    changes["signed_at"] = {
                        "from": _serialize_datetime(previous_signed_at),
                        "to": _serialize_datetime(self.signed_at),
                    }

            if changes:
                AuditLogEntry.objects.log_action(
                    action=AuditLogEntry.Action.SIGNATURE_UPDATED,
                    entity=self,
                    user=log_actor or fallback_actor,
                    payload={
                        "audit_id": self.audit_id,
                        "changes": changes,
                    },
                )

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        signature_id = self.pk
        payload = {
            "audit_id": self.audit_id,
            "signed_by": self.signed_by,
            "signed_at": _serialize_datetime(self.signed_at),
        }
        log_actor = _consume_log_actor(self)
        fallback_actor = getattr(self.audit, "created_by", None)
        result = super().delete(*args, **kwargs)
        if signature_id is not None:
            AuditLogEntry.objects.log_action(
                action=AuditLogEntry.Action.SIGNATURE_DELETED,
                entity=(self._meta.label_lower, signature_id),
                user=log_actor or fallback_actor,
                payload=payload,
            )
        return result


class AuditLogEntryManager(models.Manager["AuditLogEntry"]):
    """Custom manager that simplifies writing audit trail records."""

    def log_action(
        self,
        *,
        action: str,
        entity: models.Model | tuple[str, object | None],
        user: Any | None = None,
        payload: Any | None = None,
    ) -> "AuditLogEntry":
        if isinstance(entity, models.Model):
            entity_type = entity._meta.label_lower
            entity_id = getattr(entity, "pk", None)
        else:
            entity_type, entity_id = entity

        return self.create(
            user=user if isinstance(user, models.Model) else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else "",
            payload=payload or {},
        )


class AuditLogEntry(models.Model):
    """История ключевых действий пользователей в системе аудитов."""

    class Action(models.TextChoices):
        AUDIT_CREATED = "audit.created", _("Аудит создан")
        AUDIT_STATUS_CHANGED = "audit.status_changed", _("Статус аудита изменён")
        RESPONSE_CREATED = "response.created", _("Ответ добавлен")
        RESPONSE_UPDATED = "response.updated", _("Ответ обновлён")
        RESPONSE_DELETED = "response.deleted", _("Ответ удалён")
        ATTACHMENT_CREATED = "attachment.created", _("Вложение добавлено")
        ATTACHMENT_UPDATED = "attachment.updated", _("Вложение обновлено")
        ATTACHMENT_DELETED = "attachment.deleted", _("Вложение удалено")
        SIGNATURE_CREATED = "signature.created", _("Подпись добавлена")
        SIGNATURE_UPDATED = "signature.updated", _("Подпись обновлена")
        SIGNATURE_DELETED = "signature.deleted", _("Подпись удалена")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_log_entries",
        verbose_name=_("Пользователь"),
        help_text=_("Кто инициировал действие."),
    )
    action = models.CharField(
        _("Действие"),
        max_length=50,
        choices=Action.choices,
        help_text=_("Тип события."),
    )
    entity_type = models.CharField(
        _("Тип сущности"),
        max_length=100,
        help_text=_("Полное имя модели, к которой относится событие."),
    )
    entity_id = models.CharField(
        _("Идентификатор сущности"),
        max_length=64,
        blank=True,
        help_text=_("Первичный ключ записи или временный идентификатор."),
    )
    payload = models.JSONField(
        _("Данные"),
        blank=True,
        default=dict,
        help_text=_("Дополнительная информация о событии."),
    )
    created_at = models.DateTimeField(
        _("Создано"),
        auto_now_add=True,
        help_text=_("Время фиксации события."),
    )

    objects = AuditLogEntryManager()

    class Meta:
        verbose_name = _("Запись журнала аудита")
        verbose_name_plural = _("Журнал аудита")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["action"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} — {self.action}"

