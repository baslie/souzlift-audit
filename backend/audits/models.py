from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from collections.abc import Mapping
import json
import logging
from typing import Any, Final

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .storages import protected_media_storage
from .tokens import build_attachment_token

DEFAULT_ATTACHMENT_LIMITS: Final[dict[str, int]] = {
    "max_size_bytes": 8 * 1024 * 1024,
    "max_per_response": 10,
    "max_per_audit": 100,
}


def _attachment_limits_config() -> dict[str, int]:
    """Return attachment limits merged with optional overrides from settings."""

    raw_config = getattr(settings, "AUDIT_ATTACHMENT_LIMITS", None) or {}
    limits: dict[str, int] = DEFAULT_ATTACHMENT_LIMITS.copy()

    for key in ("max_size_bytes", "max_per_response", "max_per_audit"):
        value = raw_config.get(key)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            limits[key] = parsed

    return limits


def _default_max_per_response() -> int:
    return _attachment_limits_config()["max_per_response"]


def _default_max_per_audit() -> int:
    return _attachment_limits_config()["max_per_audit"]


def _default_max_size_bytes() -> int:
    return _attachment_limits_config()["max_size_bytes"]


def _format_size_label(bytes_value: int) -> str:
    """Format attachment size limit in megabytes for human readable messages."""

    size_mb = bytes_value / (1024 * 1024)
    if float(size_mb).is_integer():
        return str(int(size_mb))
    return f"{size_mb:.1f}".rstrip("0").rstrip(".")

sync_logger = logging.getLogger("audits.offline_sync")


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

    max_per_response: int = field(default_factory=_default_max_per_response)
    max_per_audit: int = field(default_factory=_default_max_per_audit)
    max_size_bytes: int = field(default_factory=_default_max_size_bytes)

    @property
    def max_size_mb(self) -> float:
        """Return the limit converted to megabytes for calculations."""

        return self.max_size_bytes / (1024 * 1024)

    @property
    def max_size_label(self) -> str:
        """Return a short label (in MB) suitable for error messages."""

        return _format_size_label(self.max_size_bytes)


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

        # Stash transition context for signal handlers.
        self._previous_status = previous_status
        self._status_changed = status_changed
        self._status_related_changes = status_related_changes
        self._is_creation = is_creation

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
        actor_model = actor if isinstance(actor, models.Model) else None
        if actor_model is not None:
            self._log_actor = actor_model
        if commit:
            if self.pk is None:
                self.save()
            else:
                self.save(update_fields=["status"])

            if getattr(self, "_status_changed", False):
                AuditLogEntry.objects.log_action(
                    action=AuditLogEntry.Action.AUDIT_REVIEWED,
                    entity=self,
                    user=actor_model or getattr(self, "created_by", None),
                    payload={
                        "status": self.status,
                        "reviewed_at": _serialize_datetime(self.updated_at),
                    },
                )

    def request_changes(self, *, actor: object | None = None, message: str) -> None:
        """Запросить у аудитора корректировки по отправленному аудиту."""

        if self.status != self.Status.SUBMITTED:
            raise ValidationError(
                {
                    "status": ValidationError(
                        _("Запрос правок доступен только для отправленных аудитов."),
                    )
                }
            )

        message_clean = (message or "").strip()
        if not message_clean:
            raise ValidationError(
                {
                    "message": ValidationError(
                        _("Опишите, какие изменения требуются."),
                    )
                }
            )

        log_actor = actor if isinstance(actor, models.Model) else None

        now = timezone.now()
        if self.pk:
            Audit.objects.filter(pk=self.pk).update(updated_at=now)
            self.updated_at = now

        AuditLogEntry.objects.log_action(
            action=AuditLogEntry.Action.AUDIT_CHANGES_REQUESTED,
            entity=self,
            user=log_actor or getattr(self, "_log_actor", None),
            payload={
                "message": message_clean,
                "status": self.status,
            },
        )

        from .emails import notify_audit_changes_requested

        notify_audit_changes_requested(
            self,
            message_clean,
            actor=log_actor or getattr(self, "_log_actor", None),
        )

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

        limits = AttachmentLimits()

        if self.file and hasattr(self.file, "size"):
            if self.file.size > limits.max_size_bytes:
                errors.setdefault("file", []).append(
                    ValidationError(
                        _("Размер файла превышает ограничение в %(limit)s МБ."),
                        params={"limit": limits.max_size_label},
                    ),
                )

        if self.response_id:
            response_qs = AuditAttachment.objects.filter(response=self.response)
            if self.pk:
                response_qs = response_qs.exclude(pk=self.pk)
            response_count = response_qs.count()
            if response_count >= limits.max_per_response:
                errors.setdefault("response", []).append(
                    ValidationError(
                        _("Для одного вопроса доступно не более %(limit)d вложений."),
                        params={"limit": limits.max_per_response},
                    ),
                )

            audit_qs = AuditAttachment.objects.filter(response__audit=self.response.audit)
            if self.pk:
                audit_qs = audit_qs.exclude(pk=self.pk)
            audit_count = audit_qs.count()
            if audit_count >= limits.max_per_audit:
                errors.setdefault("response__audit", []).append(
                    ValidationError(
                        _("Для одного аудита доступно не более %(limit)d вложений."),
                        params={"limit": limits.max_per_audit},
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
        response = getattr(self, "response", None)
        audit = getattr(response, "audit", None)
        fallback_actor = getattr(audit, "created_by", None)
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
        AUDIT_CHANGES_REQUESTED = "audit.changes_requested", _("Запрошены правки по аудиту")
        RESPONSE_CREATED = "response.created", _("Ответ добавлен")
        RESPONSE_UPDATED = "response.updated", _("Ответ обновлён")
        RESPONSE_DELETED = "response.deleted", _("Ответ удалён")
        ATTACHMENT_CREATED = "attachment.created", _("Вложение добавлено")
        ATTACHMENT_UPDATED = "attachment.updated", _("Вложение обновлено")
        ATTACHMENT_DELETED = "attachment.deleted", _("Вложение удалено")
        SIGNATURE_CREATED = "signature.created", _("Подпись добавлена")
        SIGNATURE_UPDATED = "signature.updated", _("Подпись обновлена")
        SIGNATURE_DELETED = "signature.deleted", _("Подпись удалена")
        AUDIT_REVIEWED = "audit.reviewed", _("Аудит просмотрен")
        OFFLINE_BATCH_CREATED = "offline.batch_created", _("Офлайн-пакет принят")
        OFFLINE_BATCH_APPLIED = "offline.batch_applied", _("Офлайн-пакет применён")
        OFFLINE_BATCH_ERROR = "offline.batch_error", _("Ошибка офлайн-пакета")

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


class OfflineSyncBatch(models.Model):
    """Журнал запросов офлайн-синхронизации."""

    class Status(models.TextChoices):
        PENDING = "pending", _("В обработке")
        APPLIED = "applied", _("Применён")
        ERROR = "error", _("Ошибка")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offline_batches",
        verbose_name=_("Пользователь"),
        help_text=_("Кто инициировал синхронизацию."),
    )
    device_id = models.CharField(
        _("Устройство"),
        max_length=255,
        help_text=_("Идентификатор устройства, выполнившего синхронизацию."),
    )
    payload = models.JSONField(
        _("Данные"),
        default=dict,
        blank=True,
        help_text=_("Содержимое запроса на синхронизацию."),
    )
    payload_hash = models.CharField(
        _("Хэш данных"),
        max_length=64,
        blank=True,
        default="",
        help_text=_("Детерминированный отпечаток исходного запроса."),
    )
    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text=_("Результат обработки пакета."),
    )
    error_details = models.JSONField(
        _("Сведения об ошибке"),
        default=dict,
        blank=True,
        help_text=_("Описание ошибок, если обработка завершилась неудачно."),
    )
    response_payload = models.JSONField(
        _("Ответ"),
        default=dict,
        blank=True,
        help_text=_("Снимок ответа, возвращённого клиенту."),
    )
    response_status = models.PositiveSmallIntegerField(
        _("Код ответа"),
        default=0,
        help_text=_("HTTP-статус ответа на запрос синхронизации."),
    )
    created_at = models.DateTimeField(
        _("Создано"),
        auto_now_add=True,
        help_text=_("Когда пакет был принят сервером."),
    )

    class Meta:
        verbose_name = _("Пакет офлайн-синхронизации")
        verbose_name_plural = _("Пакеты офлайн-синхронизации")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["payload_hash"]),
        ]

    def mark_applied(
        self,
        response: Mapping[str, Any] | None = None,
        *,
        status: int = 200,
        commit: bool = True,
    ) -> None:
        """Отметить пакет как успешно применённый."""

        self.status = self.Status.APPLIED
        self.response_status = status
        if response is not None:
            self.response_payload = dict(response)
        if not commit:
            return

        update_fields = ["status", "response_status"]
        if response is not None:
            update_fields.append("response_payload")

        self.save(update_fields=update_fields)

        log_actor = _consume_log_actor(self) or self.user
        payload_extra: dict[str, Any] = {"response_status": status}
        if response is not None:
            payload_extra["response"] = dict(response)

        AuditLogEntry.objects.log_action(
            action=AuditLogEntry.Action.OFFLINE_BATCH_APPLIED,
            entity=self,
            user=log_actor,
            payload=self._build_log_payload(payload_extra),
        )

    def mark_error(
        self,
        details: Mapping[str, Any] | None = None,
        *,
        status: int = 400,
        commit: bool = True,
    ) -> None:
        """Зафиксировать ошибку обработки пакета."""

        self.status = self.Status.ERROR
        self.error_details = dict(details or {})
        self.response_payload = {}
        self.response_status = status
        if commit:
            self.save(
                update_fields=[
                    "status",
                    "error_details",
                    "response_payload",
                    "response_status",
                ]
            )

            log_actor = _consume_log_actor(self) or self.user
            AuditLogEntry.objects.log_action(
                action=AuditLogEntry.Action.OFFLINE_BATCH_ERROR,
                entity=self,
                user=log_actor,
                payload=self._build_log_payload(
                    {
                        "response_status": status,
                        "details": dict(details or {}),
                    }
                ),
            )

            from .emails import notify_offline_sync_error

            notify_offline_sync_error(self)

        self._log_offline_sync_error(status)

    def __str__(self) -> str:
        status_label = self.get_status_display()
        identifier = self.pk if self.pk is not None else "pending"
        return f"Batch #{identifier} ({status_label})"

    def save(self, *args: object, **kwargs: object) -> None:  # type: ignore[override]
        creating = self.pk is None
        super().save(*args, **kwargs)

        if creating:
            log_actor = _consume_log_actor(self) or self.user
            AuditLogEntry.objects.log_action(
                action=AuditLogEntry.Action.OFFLINE_BATCH_CREATED,
                entity=self,
                user=log_actor,
                payload=self._build_log_payload(),
            )

    def _log_offline_sync_error(self, status: int) -> None:
        """Log structured information about offline sync errors."""

        if not sync_logger.isEnabledFor(logging.ERROR):
            return

        user_identifier: Any = self.user_id if self.user_id is not None else "anonymous"
        payload_kind = None
        if isinstance(self.payload, Mapping):
            payload_kind = self.payload.get("kind")

        try:
            details_serialized = json.dumps(
                self.error_details,
                ensure_ascii=False,
                sort_keys=True,
            )
        except TypeError:
            details_serialized = repr(self.error_details)

        sync_logger.error(
            "Offline sync error: batch=%s device=%s user=%s kind=%s status=%s payload_hash=%s details=%s",
            self.pk or "unsaved",
            self.device_id or "-",
            user_identifier,
            payload_kind or "-",
            status,
            self.payload_hash or "-",
            details_serialized,
        )

    def _payload_kind(self) -> str | None:
        if isinstance(self.payload, Mapping):
            kind = self.payload.get("kind")
            return str(kind) if kind is not None else None
        return None

    def _build_log_payload(self, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "device_id": self.device_id,
            "payload_hash": self.payload_hash or "",
        }
        kind = self._payload_kind()
        if kind:
            payload["kind"] = kind
        if extra:
            payload.update(dict(extra))
        return payload

