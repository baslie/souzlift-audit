"""Forms for managing catalog objects in the user interface."""
from __future__ import annotations

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.forms import TailwindFormMixin

from .models import Building, Elevator


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

