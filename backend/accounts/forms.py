"""Form classes for the accounts app."""
from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UsernameField
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _


class TailwindFormMixin:
    """Общие настройки оформления для форм аутентификации."""

    input_css_classes = (
        "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm "
        "focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-200"
    )
    error_css_classes = "text-sm text-red-600"
    help_text_css_classes = "text-xs text-slate-500"

    def _apply_styling(self) -> None:
        for field in self.fields.values():
            css_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css_classes} {self.input_css_classes}".strip()
            if field.help_text:
                field.help_text = format_html(
                    '<span class="{}">{}</span>', self.help_text_css_classes, field.help_text
                )

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self._apply_styling()


class StyledAuthenticationForm(TailwindFormMixin, AuthenticationForm):
    """Форма входа с едиными стилями."""

    username = UsernameField(
        label=_("Имя пользователя"),
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label=_("Пароль"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class StyledPasswordChangeForm(TailwindFormMixin, PasswordChangeForm):
    """Форма смены пароля с пользовательским оформлением."""

    old_password = forms.CharField(
        label=_("Текущий пароль"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    new_password1 = forms.CharField(
        label=_("Новый пароль"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=PasswordChangeForm.base_fields["new_password1"].help_text,
    )
    new_password2 = forms.CharField(
        label=_("Подтверждение пароля"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
