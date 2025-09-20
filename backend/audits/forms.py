"""Forms used in the audits application."""
from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _


class AuditRequestChangesForm(forms.Form):
    """Form allowing administrators to request changes from an auditor."""

    message = forms.CharField(
        label=_("Комментарий для аудитора"),
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "class": "app-input app-input--textarea",
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


__all__ = ["AuditRequestChangesForm"]

