"""Domain models for checklist templates and their items."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ChecklistTemplate(models.Model):
    """A single version of a checklist used to run audits."""

    name = models.CharField(
        _("Название"),
        max_length=255,
        help_text=_("Отображаемое имя чек-листа."),
    )
    description = models.TextField(
        _("Описание"),
        blank=True,
        help_text=_("Дополнительные инструкции или область применения."),
    )
    published_at = models.DateTimeField(
        _("Опубликован"),
        null=True,
        blank=True,
        help_text=_(
            "Дата, когда чек-лист стал доступен для назначения аудитов."
        ),
    )
    is_active = models.BooleanField(
        _("Активен"),
        default=True,
        help_text=_(
            "Флаг, разрешающий использовать шаблон для новых аудитов."
        ),
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
        verbose_name = _("Чек-лист")
        verbose_name_plural = _("Чек-листы")
        ordering = ["-published_at", "name", "id"]

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.name

    def publish(self, *, commit: bool = True) -> None:
        """Mark the template as published and optionally persist the change."""

        self.published_at = timezone.now()
        if commit:
            self.save(update_fields=["published_at"])

    def clone(self, *, name: str | None = None) -> "ChecklistTemplate":
        """Create a copy of the template together with its items."""

        copy = ChecklistTemplate.objects.create(
            name=name or self.name,
            description=self.description,
            is_active=self.is_active,
            published_at=None,
        )
        items: list[ChecklistItem] = []
        for item in self.items.all().order_by("order", "id"):
            items.append(
                ChecklistItem(
                    template=copy,
                    order=item.order,
                    area=item.area,
                    category=item.category,
                    question=item.question,
                    help_text=item.help_text,
                    score_type=item.score_type,
                    min_score=item.min_score,
                    max_score=item.max_score,
                    step=item.step,
                    options=item.options,
                    requires_comment=item.requires_comment,
                    weight=item.weight,
                )
            )
        ChecklistItem.objects.bulk_create(items)
        return copy


class ChecklistItem(models.Model):
    """Single question from a checklist template."""

    class ScoreType(models.TextChoices):
        NUMERIC = "numeric", _("Числовая шкала")
        OPTION = "option", _("Выбор варианта")

    template = models.ForeignKey(
        ChecklistTemplate,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Чек-лист"),
    )
    order = models.PositiveIntegerField(
        _("Порядок"),
        default=0,
        help_text=_("Используется для сортировки вопросов."),
    )
    area = models.CharField(
        _("Зона"),
        max_length=100,
        blank=True,
        help_text=_("Логическая зона или раздел обследования."),
    )
    category = models.CharField(
        _("Категория"),
        max_length=100,
        blank=True,
        help_text=_("Категория или тематическая группа."),
    )
    question = models.TextField(
        _("Формулировка"),
        help_text=_("Текст вопроса, отображаемый аудитору."),
    )
    help_text = models.TextField(
        _("Подсказка"),
        blank=True,
        help_text=_("Дополнительные инструкции для аудитора."),
    )
    score_type = models.CharField(
        _("Тип оценки"),
        max_length=20,
        choices=ScoreType.choices,
        default=ScoreType.NUMERIC,
    )
    min_score = models.DecimalField(
        _("Минимальный балл"),
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )
    max_score = models.DecimalField(
        _("Максимальный балл"),
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )
    step = models.DecimalField(
        _("Шаг"),
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
    )
    options = models.JSONField(
        _("Варианты"),
        default=list,
        blank=True,
        help_text=_("Возможные варианты ответа для выбора."),
    )
    requires_comment = models.BooleanField(
        _("Комментарий обязателен"),
        default=False,
    )
    weight = models.DecimalField(
        _("Вес"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("1.0"),
        help_text=_("Множитель при расчёте итогового балла."),
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
        verbose_name = _("Пункт чек-листа")
        verbose_name_plural = _("Пункты чек-листа")
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "order"],
                name="unique_order_per_template",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.template.name}: {self.question[:60]}"

    def clean(self) -> None:
        super().clean()
        errors: dict[str, list[str]] = {}

        if self.score_type == self.ScoreType.NUMERIC:
            if self.min_score is None or self.max_score is None:
                errors.setdefault("min_score", []).append(
                    _(
                        "Для числовой шкалы необходимо указать значения «Минимальный балл» и «Максимальный балл»."
                    ),
                )
            elif self.min_score > self.max_score:
                errors.setdefault("max_score", []).append(
                    _("Минимальный балл не может превышать максимальный."),
                )
            if self.step is None or self.step <= 0:
                errors.setdefault("step", []).append(
                    _("Для числовой шкалы необходимо указать положительный шаг."),
                )
        else:
            if not self.options:
                errors.setdefault("options", []).append(
                    _("Для вопросов с вариантами необходимо задать хотя бы один вариант."),
                )
            if any(not isinstance(option, str) or not option.strip() for option in self.options):
                errors.setdefault("options", []).append(
                    _("Каждый вариант должен быть непустой строкой."),
                )
        if errors:
            raise ValidationError(errors)

    def normalized_options(self) -> list[str]:
        """Return a list of option strings, trimming whitespace."""

        if self.score_type != self.ScoreType.OPTION:
            return []
        normalized: list[str] = []
        for option in self.options:
            if isinstance(option, str):
                normalized.append(option.strip())
        return normalized

    def numeric_range(self) -> tuple[Decimal, Decimal, Decimal] | None:
        """Return numeric range definition for numeric questions."""

        if self.score_type != self.ScoreType.NUMERIC:
            return None
        assert self.min_score is not None
        assert self.max_score is not None
        assert self.step is not None
        return (self.min_score, self.max_score, self.step)

    def to_dict(self) -> dict[str, Any]:
        """Serialize item fields for exports and APIs."""

        payload: dict[str, Any] = {
            "id": self.pk,
            "area": self.area,
            "category": self.category,
            "question": self.question,
            "help_text": self.help_text,
            "requires_comment": self.requires_comment,
            "weight": str(self.weight),
            "score_type": self.score_type,
        }
        if self.score_type == self.ScoreType.NUMERIC:
            payload.update(
                {
                    "min_score": str(self.min_score),
                    "max_score": str(self.max_score),
                    "step": str(self.step),
                }
            )
        else:
            payload["options"] = self.normalized_options()
        return payload
