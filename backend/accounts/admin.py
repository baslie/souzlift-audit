from __future__ import annotations

import secrets
import string
from typing import Iterable

from django.contrib import admin, messages
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.forms.models import BaseInlineFormSet
from django.utils.translation import gettext_lazy as _

from .models import UserProfile


def generate_temporary_password(length: int = 12) -> str:
    """Генерирует временный пароль, удовлетворяющий базовым требованиям сложности."""

    if length < 6:
        msg = "Password length must be at least 6 characters."
        raise ValueError(msg)

    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%?-_"

    alphabet = lowercase + uppercase + digits + special

    required_characters = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(special),
    ]

    while len(required_characters) < length:
        required_characters.append(secrets.choice(alphabet))

    secrets.SystemRandom().shuffle(required_characters)
    return "".join(required_characters)


def _format_credentials(credentials: Iterable[tuple[str, str]]) -> str:
    """Формирует человеко-читаемое сообщение для администратора."""

    lines = [
        _(
            "Временные пароли сгенерированы. Передайте их пользователям и попросите сменить при первом входе.",
        )
    ]

    for username, password in credentials:
        lines.append(f"• {username}: {password}")

    return "\n".join(str(line) for line in lines)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "full_name",
        "role",
        "phone",
        "employee_id",
        "password_changed_at",
    )
    list_filter = ("role",)
    search_fields = (
        "user__username",
        "user__email",
        "full_name",
        "phone",
        "employee_id",
    )


class UserProfileInlineFormSet(BaseInlineFormSet):
    """Формсет, обновляющий существующий профиль вместо создания дубликата."""

    def save_new(self, form, commit: bool = True):  # type: ignore[override]
        if self._should_delete_form(form):
            return super().save_new(form, commit=commit)

        profile, _ = UserProfile.objects.get_or_create(user=self.instance)

        for field_name, value in form.cleaned_data.items():
            if field_name in {"id", "DELETE"}:
                continue
            if field_name not in form.fields:
                continue
            setattr(profile, field_name, value)

        if commit:
            profile.save()

        form.instance = profile
        return profile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    formset = UserProfileInlineFormSet
    can_delete = False
    extra = 0
    max_num = 1

    def get_extra(self, request, obj=None, **kwargs):
        return 1 if obj is None else 0


User = get_user_model()


try:
    admin.site.unregister(User)
except NotRegistered:
    pass


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = [UserProfileInline]
    list_display = DjangoUserAdmin.list_display + ("profile_role",)
    list_filter = DjangoUserAdmin.list_filter + ("profile__role",)
    actions = ("activate_users", "deactivate_users", "reset_passwords")
    list_select_related = ("profile",)

    @admin.display(ordering="profile__role", description="Роль")
    def profile_role(self, obj: User) -> str:
        if hasattr(obj, "profile"):
            return obj.profile.get_role_display()
        return "—"

    @admin.action(description=_("Активировать выбранных пользователей"))
    def activate_users(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            _("Активировано %(count)d пользователей.") % {"count": updated},
            level=messages.SUCCESS,
        )

    @admin.action(description=_("Деактивировать выбранных пользователей"))
    def deactivate_users(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            _("Деактивировано %(count)d пользователей.") % {"count": updated},
            level=messages.WARNING,
        )

    @admin.action(description=_("Сгенерировать временный пароль"))
    def reset_passwords(self, request, queryset):
        credentials: list[tuple[str, str]] = []

        for user in queryset:
            password = generate_temporary_password()
            user.set_password(password)
            user.save(update_fields=["password"])
            profile = getattr(user, "profile", None)
            if profile:
                profile.mark_password_changed()
            credentials.append((user.get_username(), password))

        if not credentials:
            self.message_user(
                request,
                _("Не выбрано ни одного пользователя."),
                level=messages.WARNING,
            )
            return

        self.message_user(
            request,
            _format_credentials(credentials),
            level=messages.SUCCESS,
        )
