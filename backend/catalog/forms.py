"""Forms for catalog entities."""
from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.forms import BootstrapFormMixin

from .models import Building, Elevator


class BuildingForm(BootstrapFormMixin, forms.ModelForm):
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


class ElevatorForm(BootstrapFormMixin, forms.ModelForm):
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

    def __init__(self, *args, user: object | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["building"].queryset = (
                Building.objects.visible_for_user(user)
                .select_related("created_by", "verified_by")
                .order_by("address", "entrance")
            )
        self.fields["status"].choices = Elevator.Status.choices
        self.fields["status"].help_text = _(
            "Выберите текущее состояние лифта. Значение можно изменить в любой момент."
        )
        self.fields["building"].empty_label = _("Выберите здание")


class CatalogImportUploadForm(BootstrapFormMixin, forms.Form):
    file = forms.FileField(
        label=_("Файл импорта"),
        help_text=_("Поддерживаются файлы CSV и XLSX."),
    )


class CatalogImportConfirmForm(forms.Form):
    payload = forms.CharField(widget=forms.HiddenInput)
    filename = forms.CharField(widget=forms.HiddenInput)
