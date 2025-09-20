"""Customisations shared across the Django admin site."""

from __future__ import annotations

from django.http import HttpRequest


class SuperuserOnlyAdminMixin:
    """Limit admin access to active superusers.

    Согласно архитектуре 2.0 (`docs/architecture/v2.md#61-django-admin`),
    прикладные администраторы больше не должны работать через Django Admin.
    Эта примесь проверяет, что все действия разрешены только техническому
    оператору — активному суперпользователю. Для остальных пользователей
    интерфейс админки скрывается, а прямой доступ к URL возвращает 403.
    """

    def _is_superuser(self, request: HttpRequest) -> bool:
        user = getattr(request, "user", None)
        return bool(user and user.is_active and user.is_superuser)

    def has_module_permission(self, request: HttpRequest) -> bool:  # type: ignore[override]
        if not self._is_superuser(request):
            return False
        return super().has_module_permission(request)

    def has_view_permission(  # type: ignore[override]
        self, request: HttpRequest, obj=None
    ) -> bool:
        if not self._is_superuser(request):
            return False
        return super().has_view_permission(request, obj=obj)

    def has_add_permission(self, request: HttpRequest) -> bool:  # type: ignore[override]
        if not self._is_superuser(request):
            return False
        return super().has_add_permission(request)

    def has_change_permission(  # type: ignore[override]
        self, request: HttpRequest, obj=None
    ) -> bool:
        if not self._is_superuser(request):
            return False
        return super().has_change_permission(request, obj=obj)

    def has_delete_permission(  # type: ignore[override]
        self, request: HttpRequest, obj=None
    ) -> bool:
        if not self._is_superuser(request):
            return False
        return super().has_delete_permission(request, obj=obj)
