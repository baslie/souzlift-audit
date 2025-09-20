"""Form classes for the accounts app."""
from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UsernameField
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _


class TailwindFormMixin:
    """Общие настройки оформления для форм и элементов ввода."""

    input_css_classes = "app-input"
    textarea_css_classes = "app-input app-input--textarea"
    select_css_classes = "app-input app-input--select"
    file_css_classes = "app-input app-input--file"
    checkbox_css_classes = "app-checkbox"
    error_css_classes = "form-error"
    help_text_css_classes = "form-help"

    def _apply_styling(self) -> None:
        for field in self.fields.values():
            widget = field.widget
            css_classes = widget.attrs.get("class", "").strip()
            if isinstance(widget, forms.Textarea):
                base_classes = self.textarea_css_classes
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                base_classes = self.select_css_classes
            elif isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                base_classes = self.checkbox_css_classes
            elif isinstance(widget, (forms.FileInput, forms.ClearableFileInput)):
                base_classes = self.file_css_classes
            else:
                base_classes = self.input_css_classes

            widget.attrs["class"] = " ".join(filter(None, [css_classes, base_classes]))

            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("aria-checked", "false")

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
