"""Simplified audit domain models aligned with architecture 3.0."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from checklists.models import ChecklistItem, ChecklistTemplate


class Audit(models.Model):
    """Audit of an elevator using a particular checklist template."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Черновик")
        SUBMITTED = "submitted", _("Отправлен")

    building = models.ForeignKey(
        "catalog.Building",
        on_delete=models.PROTECT,
        related_name="audits",
        verbose_name=_("Здание"),
    )
    elevator = models.ForeignKey(
        "catalog.Elevator",
        on_delete=models.PROTECT,
        related_name="audits",
        verbose_name=_("Лифт"),
    )
    template = models.ForeignKey(
        ChecklistTemplate,
        on_delete=models.PROTECT,
        related_name="audits",
        verbose_name=_("Чек-лист"),
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_audits",
        verbose_name=_("Исполнитель"),
    )
    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    deadline = models.DateField(
        _("Дедлайн"),
        blank=True,
        null=True,
    )
    submitted_at = models.DateTimeField(
        _("Отправлен"),
        blank=True,
        null=True,
    )
    score = models.DecimalField(
        _("Итоговый балл"),
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    admin_comment = models.TextField(
        _("Комментарий администратора"),
        blank=True,
    )
    created_at = models.DateTimeField(
        _("Создан"),
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        _("Обновлён"),
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Аудит")
        verbose_name_plural = _("Аудиты")
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "elevator", "status"],
                condition=models.Q(status="draft"),
                name="unique_draft_per_elevator",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"Аудит #{self.pk}"

    @property
    def is_editable(self) -> bool:
        """Draft audits can be modified by auditors."""

        return self.status == self.Status.DRAFT

    def mark_submitted(self, *, commit: bool = True) -> None:
        """Transition audit to submitted status, ensure score is up-to-date."""

        self.calculate_score(commit=False)
        if self.submitted_at is None:
            self.submitted_at = timezone.now()
        self.status = self.Status.SUBMITTED
        if commit:
            self.save(update_fields=["status", "submitted_at", "score", "updated_at"])

    def request_changes(self, *, comment: str | None = None, commit: bool = True) -> None:
        """Return audit to draft state with administrator comment."""

        self.status = self.Status.DRAFT
        self.submitted_at = None
        if comment is not None:
            self.admin_comment = comment
        if commit:
            self.save(update_fields=["status", "submitted_at", "admin_comment", "updated_at"])

    def calculate_score(self, *, commit: bool = True) -> Decimal:
        """Recalculate and persist weighted score based on responses."""

        total_weight = Decimal("0")
        total_value = Decimal("0")
        for response in self.responses.select_related("item"):
            value = response.get_numeric_value()
            if value is None:
                continue
            weight = response.item.weight or Decimal("0")
            if weight <= 0:
                continue
            total_weight += weight
            total_value += weight * value
        if total_weight > 0:
            raw_score = total_value / total_weight
        else:
            raw_score = Decimal("0")
        score = raw_score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.score = score
        if commit:
            self.save(update_fields=["score", "updated_at"])
        return score

    def save(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - behaviour
        super().save(*args, **kwargs)
        if self.status == self.Status.SUBMITTED and self.submitted_at is None:
            # Ensure submitted_at is set even when status is assigned manually.
            self.submitted_at = timezone.now()
            super().save(update_fields=["submitted_at"])


class AuditResponse(models.Model):
    """Response to a particular checklist item within an audit."""

    audit = models.ForeignKey(
        Audit,
        on_delete=models.CASCADE,
        related_name="responses",
        verbose_name=_("Аудит"),
    )
    item = models.ForeignKey(
        ChecklistItem,
        on_delete=models.PROTECT,
        related_name="responses",
        verbose_name=_("Пункт чек-листа"),
    )
    numeric_answer = models.DecimalField(
        _("Числовой ответ"),
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )
    selected_option = models.CharField(
        _("Выбранный вариант"),
        max_length=255,
        blank=True,
    )
    comment = models.TextField(
        _("Комментарий"),
        blank=True,
    )
    created_at = models.DateTimeField(
        _("Создан"),
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        _("Обновлён"),
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Ответ")
        verbose_name_plural = _("Ответы")
        unique_together = ("audit", "item")

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"Ответ на {self.item_id} для аудита {self.audit_id}"

    def clean(self) -> None:
        super().clean()
        errors: dict[str, list[str]] = {}

        if self.item.score_type == self.item.ScoreType.NUMERIC:
            if self.numeric_answer is None:
                errors.setdefault("numeric_answer", []).append(
                    _("Необходимо указать числовое значение."),
                )
            else:
                bounds = self.item.numeric_range()
                if bounds is not None:
                    min_score, max_score, step = bounds
                    if self.numeric_answer < min_score or self.numeric_answer > max_score:
                        errors.setdefault("numeric_answer", []).append(
                            _("Значение выходит за пределы допустимого диапазона."),
                        )
                    else:
                        remainder = (self.numeric_answer - min_score) % step
                        if remainder != 0:
                            errors.setdefault("numeric_answer", []).append(
                                _("Значение должно соответствовать шагу шкалы."),
                            )
            if self.selected_option:
                errors.setdefault("selected_option", []).append(
                    _("Для числовых вопросов нельзя выбирать варианты."),
                )
        else:
            if not self.selected_option:
                errors.setdefault("selected_option", []).append(
                    _("Необходимо выбрать один из вариантов ответа."),
                )
            elif self.selected_option not in self.item.normalized_options():
                errors.setdefault("selected_option", []).append(
                    _("Выбран недопустимый вариант ответа."),
                )
            if self.numeric_answer is not None:
                errors.setdefault("numeric_answer", []).append(
                    _("Для вопросов с вариантами числовой ответ не используется."),
                )
        if self.item.requires_comment and not self.comment.strip():
            errors.setdefault("comment", []).append(
                _("Комментарий обязателен для данного вопроса."),
            )
        if errors:
            raise ValidationError(errors)

    def get_numeric_value(self) -> Decimal | None:
        """Return numeric equivalent of the response if available."""

        if self.item.score_type != self.item.ScoreType.NUMERIC:
            return None
        if self.numeric_answer is None:
            return None
        return Decimal(self.numeric_answer)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
        # Update audit score eagerly to keep cached value in sync.
        self.audit.calculate_score(commit=True)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        audit = self.audit
        result = super().delete(*args, **kwargs)
        audit.calculate_score(commit=True)
        return result


class AuditAttachment(models.Model):
    """File attached to an audit or a particular response."""

    audit = models.ForeignKey(
        Audit,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name=_("Аудит"),
    )
    response = models.ForeignKey(
        AuditResponse,
        on_delete=models.CASCADE,
        related_name="attachments",
        null=True,
        blank=True,
        verbose_name=_("Ответ"),
    )
    file = models.FileField(
        _("Файл"),
        upload_to="audits/attachments/",
    )
    caption = models.CharField(
        _("Описание"),
        max_length=255,
        blank=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_audit_files",
        verbose_name=_("Загрузил"),
    )
    uploaded_at = models.DateTimeField(
        _("Загружено"),
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _("Вложение")
        verbose_name_plural = _("Вложения")
        ordering = ["-uploaded_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.file.name

    def clean(self) -> None:
        super().clean()
        if self.response and self.response.audit_id != self.audit_id:
            raise ValidationError(
                {"response": _("Вложение должно относиться к ответу текущего аудита.")}
            )
        limits = getattr(settings, "AUDIT_ATTACHMENT_LIMITS", {})
        max_size_bytes = int(limits.get("max_size_bytes", 0) or 0)
        if self.file and max_size_bytes:
            try:
                file_size = int(self.file.size)
            except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensive
                file_size = 0
            if file_size > max_size_bytes:
                limit_mb = max_size_bytes / (1024 * 1024)
                raise ValidationError(
                    {
                        "file": _(
                            "Размер файла превышает допустимый лимит %(limit).1f МБ."
                        )
                        % {"limit": limit_mb}
                    }
                )

        attachment_qs = self.__class__.objects.filter(audit_id=self.audit_id)
        if self.pk:
            attachment_qs = attachment_qs.exclude(pk=self.pk)

        max_per_audit = int(limits.get("max_per_audit", 0) or 0)
        if max_per_audit and attachment_qs.count() >= max_per_audit:
            raise ValidationError(
                {
                    "audit": _(
                        "Превышено количество вложений для аудита: максимум %(limit)d файлов."
                    )
                    % {"limit": max_per_audit}
                }
            )

        if self.response_id:
            response_qs = self.__class__.objects.filter(response_id=self.response_id)
            if self.pk:
                response_qs = response_qs.exclude(pk=self.pk)
            max_per_response = int(limits.get("max_per_response", 0) or 0)
            if max_per_response and response_qs.count() >= max_per_response:
                raise ValidationError(
                    {
                        "response": _(
                            "Превышено количество вложений для ответа: максимум %(limit)d файлов."
                        )
                        % {"limit": max_per_response}
                    }
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


__all__ = [
    "Audit",
    "AuditResponse",
    "AuditAttachment",
]
