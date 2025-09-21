"""Forms used in the audits application."""
from __future__ import annotations

from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.forms import BootstrapFormMixin

from .models import Audit, AuditResponse


class AuditItemForm(BootstrapFormMixin, forms.Form):
    """Single checklist item response form used on the audit detail page."""

    numeric_answer = forms.DecimalField(
        label=_("Баллы"),
        required=False,
        max_digits=8,
        decimal_places=2,
    )
    selected_option = forms.CharField(
        label=_("Ответ"),
        required=False,
    )
    comment = forms.CharField(
        label=_("Комментарий"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(
        self,
        *args: object,
        audit: Audit,
        item,
        instance: AuditResponse | None = None,
        read_only: bool = False,
        **kwargs: object,
    ) -> None:
        from checklists.models import ChecklistItem  # local import to avoid cycle

        if not isinstance(item, ChecklistItem):  # pragma: no cover - defensive
            raise TypeError("item must be an instance of ChecklistItem")

        self.audit = audit
        self.item = item
        self.read_only = read_only
        self.instance = instance or AuditResponse(audit=audit, item=item)

        initial = kwargs.setdefault("initial", {})
        if instance is not None:
            if item.score_type == item.ScoreType.NUMERIC:
                initial.setdefault("numeric_answer", instance.numeric_answer)
            else:
                initial.setdefault("selected_option", instance.selected_option)
            initial.setdefault("comment", instance.comment)

        super().__init__(*args, **kwargs)

        # Configure answer fields according to checklist definition.
        numeric_field = self.fields["numeric_answer"]
        option_field = self.fields["selected_option"]
        comment_field = self.fields["comment"]

        comment_field.help_text = ""

        if item.score_type == item.ScoreType.NUMERIC:
            bounds = item.numeric_range()
            if bounds is not None:
                min_score, max_score, step = bounds
                numeric_field.min_value = min_score
                numeric_field.max_value = max_score
                numeric_field.widget.attrs.setdefault("step", str(step))
                numeric_field.help_text = _(
                    "Допустимый диапазон: от %(min)s до %(max)s с шагом %(step)s."
                ) % {"min": min_score, "max": max_score, "step": step}
            option_field.widget = forms.HiddenInput()
            option_field.initial = ""
        else:
            options = list(item.option_definitions())
            option_field.widget = forms.Select(
                choices=[("", _("Выберите вариант"))]
                + [
                    (option.label, option.display_label)
                    for option in options
                ]
            )
            numeric_field.widget = forms.HiddenInput()
            numeric_field.help_text = ""

        if item.requires_comment:
            comment_field.help_text = _("Комментарий обязателен при заполнении этого пункта.")

        if read_only:
            for field in self.fields.values():
                field.disabled = True

        # Re-apply Bootstrap styling to reflect updated widgets.
        self._apply_styling()

    def clean_selected_option(self) -> str:
        value = self.cleaned_data.get("selected_option", "") or ""
        return value.strip()

    def clean_comment(self) -> str:
        comment = self.cleaned_data.get("comment", "") or ""
        return comment.strip()

    def clean(self) -> dict[str, object]:
        cleaned = super().clean()
        item = self.item

        if item.score_type == item.ScoreType.NUMERIC:
            answer = cleaned.get("numeric_answer")
            if answer is not None:
                bounds = item.numeric_range()
                if bounds is not None:
                    min_score, max_score, step = bounds
                    if answer < min_score or answer > max_score:
                        self.add_error(
                            "numeric_answer",
                            _("Значение выходит за пределы допустимого диапазона."),
                        )
                    else:
                        remainder = (answer - min_score) % step
                        if remainder != 0:
                            self.add_error(
                                "numeric_answer",
                                _("Значение должно соответствовать шагу шкалы."),
                            )
            cleaned["selected_option"] = ""
        else:
            option = cleaned.get("selected_option", "") or ""
            if option and item.find_option_by_label(option) is None:
                self.add_error(
                    "selected_option",
                    _("Выбран недопустимый вариант ответа."),
                )
            cleaned["numeric_answer"] = None

        comment = cleaned.get("comment", "") or ""
        if item.requires_comment and self._has_provided_answer(cleaned) and not comment:
            self.add_error(
                "comment",
                _("Комментарий обязателен для данного вопроса."),
            )
        return cleaned

    def _has_provided_answer(self, data: dict[str, object]) -> bool:
        if self.item.score_type == self.item.ScoreType.NUMERIC:
            return data.get("numeric_answer") is not None
        option = data.get("selected_option")
        return bool(option)

    def has_answer(self) -> bool:
        if self.is_bound and hasattr(self, "cleaned_data"):
            return self._has_provided_answer(self.cleaned_data)
        if self.instance.pk:
            if self.item.score_type == self.item.ScoreType.NUMERIC:
                return self.instance.numeric_answer is not None
            return bool(self.instance.selected_option)
        return False

    def save(self, *, commit: bool = True) -> AuditResponse | None:
        if not self.is_valid():  # pragma: no cover - guard for misuse
            raise ValueError("Cannot save invalid form")

        provided = self._has_provided_answer(self.cleaned_data)
        instance = self.instance

        if not provided:
            if instance.pk and commit:
                instance.delete()
            return None

        if self.item.score_type == self.item.ScoreType.NUMERIC:
            instance.numeric_answer = Decimal(self.cleaned_data["numeric_answer"])
            instance.selected_option = ""
        else:
            instance.selected_option = str(self.cleaned_data["selected_option"])
            instance.numeric_answer = None
        instance.comment = str(self.cleaned_data.get("comment", ""))
        instance.audit = self.audit
        instance.item = self.item

        if commit:
            instance.save()
        return instance


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


__all__ = [
    "AuditItemForm",
    "AuditRequestChangesForm",
    "AttachmentLimitForm",
]

