"""Forms for managing catalog objects in the user interface."""
from __future__ import annotations

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.forms import TailwindFormMixin

from .models import (
    Building,
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    Elevator,
    ScoreOption,
)


class BuildingForm(TailwindFormMixin, forms.ModelForm):
    """Форма создания и редактирования зданий."""

    class Meta:
        model = Building
        fields = ["address", "entrance", "notes"]
        labels = {
            "address": _("Адрес"),
            "entrance": _("Подъезд"),
            "notes": _("Примечания"),
        }
        widgets = {
            "address": forms.TextInput(attrs={"placeholder": _("Улица, дом")}),
            "entrance": forms.TextInput(attrs={"placeholder": _("Например, подъезд 1")}),
            "notes": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": _(
                        "Особенности объекта, ориентиры или дополнительная информация"
                    ),
                }
            ),
        }


class ElevatorForm(TailwindFormMixin, forms.ModelForm):
    """Форма создания и редактирования лифтов."""

    class Meta:
        model = Elevator
        fields = ["building", "identifier", "status", "description"]
        labels = {
            "building": _("Здание"),
            "identifier": _("Идентификатор"),
            "status": _("Статус"),
            "description": _("Описание"),
        }
        widgets = {
            "identifier": forms.TextInput(
                attrs={"placeholder": _("Заводской или внутренний номер")}
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": _(
                        "Дополнительные сведения: грузоподъёмность, особенности обслуживания"
                    ),
                }
            ),
        }

    def __init__(self, *args: Any, user: object | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["building"].queryset = (
                Building.objects.visible_for_user(user)
                .select_related("created_by", "verified_by")
                .order_by("address", "entrance")
            )
        self.fields["status"].choices = Elevator.Status.choices
        self.fields["status"].help_text = _(
            "Выберите текущее состояние лифта. После утверждения администратором статус будет"
            " доступен всем аудиторам."
        )


class ChecklistCategoryForm(TailwindFormMixin, forms.ModelForm):
    """Форма управления категориями чек-листа."""

    class Meta:
        model = ChecklistCategory
        fields = ["code", "name", "order"]
        labels = {
            "code": _("Код"),
            "name": _("Название"),
            "order": _("Порядок"),
        }
        help_texts = {
            "code": _(
                "Используется для импорта и интеграций. Изменение кода влияет на офлайн-снапшоты"
                " после следующей синхронизации."
            ),
            "order": _("Число определяет позицию категории в списке. Можно поменять кнопками на странице."),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["order"].widget.attrs.setdefault("min", 0)


class ChecklistSectionForm(TailwindFormMixin, forms.ModelForm):
    """Форма управления секциями чек-листа."""

    class Meta:
        model = ChecklistSection
        fields = ["category", "title", "description", "order"]
        labels = {
            "category": _("Категория"),
            "title": _("Название"),
            "description": _("Описание"),
            "order": _("Порядок"),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "description": _("Краткие инструкции для аудитора. Необязательно."),
            "order": _("Определяет позицию секции внутри категории."),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ChecklistCategory.objects.all().order_by("order", "name")
        self.fields["order"].widget.attrs.setdefault("min", 0)


class ChecklistQuestionForm(TailwindFormMixin, forms.ModelForm):
    """Форма управления вопросами чек-листа."""

    class Meta:
        model = ChecklistQuestion
        fields = [
            "section",
            "text",
            "type",
            "max_score",
            "guideline",
            "requires_comment",
            "order",
        ]
        labels = {
            "section": _("Секция"),
            "text": _("Формулировка"),
            "type": _("Тип вопроса"),
            "max_score": _("Максимальный балл"),
            "guideline": _("Подсказка"),
            "requires_comment": _("Комментарий обязателен"),
            "order": _("Порядок"),
        }
        widgets = {
            "text": forms.Textarea(attrs={"rows": 3}),
            "guideline": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "type": _("Балльные вопросы поддерживают варианты оценок."),
            "max_score": _(
                "Используется для расчёта итогового балла. Для небалльных вопросов можно оставить 0."
            ),
            "requires_comment": _(
                "Обязывает аудитора оставлять комментарий независимо от выбранного значения."
            ),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["section"].queryset = (
            ChecklistSection.objects.select_related("category")
            .order_by("category__order", "category__name", "order", "id")
        )
        self.fields["type"].choices = ChecklistQuestion.QuestionType.choices
        self.fields["max_score"].widget.attrs.setdefault("min", 0)
        self.fields["order"].widget.attrs.setdefault("min", 0)


class ScoreOptionForm(TailwindFormMixin, forms.ModelForm):
    """Форма управления вариантами баллов."""

    class Meta:
        model = ScoreOption
        fields = ["question", "score", "description", "order"]
        labels = {
            "question": _("Вопрос"),
            "score": _("Баллы"),
            "description": _("Описание"),
            "order": _("Порядок"),
        }
        help_texts = {
            "description": _(
                "Кратко опишите условие получения указанного количества баллов."
            ),
            "order": _("Определяет порядок отображения вариантов в интерфейсе."),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["question"].queryset = (
            ChecklistQuestion.objects.select_related("section", "section__category")
            .order_by("section__category__order", "section__order", "order", "id")
        )
        self.fields["score"].widget.attrs.setdefault("min", 0)
        self.fields["order"].widget.attrs.setdefault("min", 0)

