"""Ролевые проверки и ограничения выборок."""
from __future__ import annotations

from typing import Iterable, Sequence

from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db.models import Model, QuerySet
from django.http import HttpRequest, HttpResponse
from django.urls import reverse_lazy
from django.utils.functional import cached_property

from .models import UserProfile


def _get_profile(user: object) -> UserProfile | None:
    profile = getattr(user, "profile", None)
    if isinstance(profile, UserProfile):
        return profile
    return None


def is_admin(user: object) -> bool:
    """Проверка, что пользователь относится к роли администратора."""

    profile = _get_profile(user)
    return bool(profile and profile.is_admin)


def is_auditor(user: object) -> bool:
    """Проверка, что пользователь относится к роли аудитора."""

    profile = _get_profile(user)
    return bool(profile and profile.is_auditor)


def role_required(*roles: str, redirect_field_name: str = "next"):
    """Декоратор, ограничивающий доступ к указанным ролям."""

    allowed: frozenset[str] = frozenset(roles)

    def predicate(user: object) -> bool:
        profile = _get_profile(user)
        return bool(profile and profile.role in allowed)

    return user_passes_test(predicate, login_url=reverse_lazy("accounts:login"), redirect_field_name=redirect_field_name)


class RoleRequiredMixin(LoginRequiredMixin):
    """Базовый mixin для ограничений по ролям."""

    allowed_roles: Sequence[str] = ()

    @cached_property
    def profile(self) -> UserProfile | None:
        return _get_profile(self.request.user)

    def get_allowed_roles(self) -> Iterable[str]:
        return self.allowed_roles

    def has_role_permission(self) -> bool:
        profile = self.profile
        if profile is None:
            return False
        allowed = set(self.get_allowed_roles())
        return not allowed or profile.role in allowed

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not self.has_role_permission():
            raise PermissionDenied("Недостаточно прав для выполнения операции.")
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(RoleRequiredMixin):
    """Доступ только для администраторов."""

    allowed_roles = (UserProfile.Roles.ADMIN,)


class AuditorRequiredMixin(RoleRequiredMixin):
    """Доступ только для аудиторов."""

    allowed_roles = (UserProfile.Roles.AUDITOR,)


class RoleQuerysetMixin(RoleRequiredMixin):
    """Mixin для фильтрации queryset в зависимости от роли."""

    auditor_field_name = "created_by"

    def filter_queryset_for_role(self, queryset: QuerySet[Model]) -> QuerySet[Model]:
        return restrict_queryset_for_user(queryset, self.request.user, auditor_field=self.auditor_field_name)

    def get_queryset(self) -> QuerySet[Model]:  # type: ignore[override]
        queryset = super().get_queryset()  # type: ignore[misc]
        return self.filter_queryset_for_role(queryset)


def restrict_queryset_for_user(
    queryset: QuerySet[Model],
    user: object,
    *,
    auditor_field: str | None = "created_by",
) -> QuerySet[Model]:
    """Сужает queryset в зависимости от роли пользователя."""

    profile = _get_profile(user)
    if profile is None:
        return queryset.none()
    if profile.is_admin:
        return queryset

    if auditor_field:
        try:
            queryset.model._meta.get_field(auditor_field)
        except FieldDoesNotExist:
            pass
        else:
            return queryset.filter(**{auditor_field: profile.user})

    for field_name in ("user", "owner", "author"):
        try:
            queryset.model._meta.get_field(field_name)
        except FieldDoesNotExist:
            continue
        return queryset.filter(**{field_name: profile.user})

    if isinstance(user, Model) and queryset.model is user.__class__:
        return queryset.filter(pk=user.pk)

    return queryset.none()
