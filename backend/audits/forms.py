"""Forms used in the audits application."""
from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.forms import BootstrapFormMixin


class AuditRequestChangesForm(BootstrapFormMixin, forms.Form):
    """Form allowing administrators to request changes from an auditor."""

    message = forms.CharField(
        label=_("Комментарий для аудитора"),
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": _("Опишите, какие корректировки необходимо внести."),
            }
        ),
        max_length=2000,
        help_text=_("Сообщение увидит автор аудита в письме и в журнале действий."),
    )

    def clean_message(self) -> str:
        message = self.cleaned_data.get("message", "")
        stripped = message.strip()
        if not stripped:
            raise forms.ValidationError(
                _("Опишите, какие изменения требуются — поле не может быть пустым."),
            )
        return stripped


class AttachmentLimitForm(BootstrapFormMixin, forms.Form):
    """Форма обновления лимитов вложений для кабинета администратора."""

    max_size_mb = forms.IntegerField(
        label=_("Максимальный размер файла (МБ)"),
        min_value=1,
        initial=8,
        help_text=_("Ограничение применяется к каждому загружаемому файлу."),
    )
    max_per_response = forms.IntegerField(
        label=_("Файлов на ответ"),
        min_value=1,
        initial=10,
        help_text=_("Сколько файлов можно прикрепить к одному вопросу чек-листа."),
    )
    max_per_audit = forms.IntegerField(
        label=_("Файлов на аудит"),
        min_value=1,
        initial=100,
        help_text=_("Совокупное количество вложений в рамках одного аудита."),
    )

    def clean(self) -> dict[str, object]:
        data = super().clean()
        max_per_response = data.get("max_per_response")
        max_per_audit = data.get("max_per_audit")
        if (
            isinstance(max_per_response, int)
            and isinstance(max_per_audit, int)
            and max_per_audit < max_per_response
        ):
            raise forms.ValidationError(
                _("Общее количество файлов на аудит не может быть меньше лимита на вопрос."),
            )
        return data

    def to_limits(self) -> dict[str, int]:
        cleaned = self.cleaned_data
        max_size_mb = int(cleaned["max_size_mb"])
        return {
            "max_size_bytes": max_size_mb * 1024 * 1024,
            "max_per_response": int(cleaned["max_per_response"]),
            "max_per_audit": int(cleaned["max_per_audit"]),
        }


__all__ = ["AuditRequestChangesForm", "AttachmentLimitForm"]

