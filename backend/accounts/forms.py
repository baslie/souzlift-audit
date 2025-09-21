"""Form classes for the accounts app."""
from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UsernameField
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _


class BootstrapFormMixin:
    """Общие настройки оформления для форм и элементов ввода под Bootstrap."""

    input_css_classes = "form-control"
    textarea_css_classes = "form-control"
    select_css_classes = "form-select"
    file_css_classes = "form-control"
    checkbox_css_classes = "form-check-input"
    help_text_css_classes = "form-text"

    def _apply_styling(self) -> None:
        for name, field in self.fields.items():
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

            bound_field = self[name]
            errors = getattr(bound_field, "errors", ())

            classes = " ".join(filter(None, [css_classes, base_classes]))
            if errors and base_classes != self.checkbox_css_classes:
                classes = f"{classes} is-invalid".strip()

            widget.attrs["class"] = classes

            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("aria-checked", "false")
                if errors:
                    widget.attrs["class"] = f"{widget.attrs['class']} is-invalid".strip()

            if field.help_text:
                field.help_text = format_html(
                    '<div class="{}">{}</div>', self.help_text_css_classes, field.help_text
                )

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self._apply_styling()


class StyledAuthenticationForm(BootstrapFormMixin, AuthenticationForm):
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


class StyledPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
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
