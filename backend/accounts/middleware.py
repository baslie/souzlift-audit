"""Промежуточное ПО для контроля политики смены пароля."""
from __future__ import annotations

from typing import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import Resolver404, resolve

from .models import UserProfile


class ForcePasswordChangeMiddleware:
    """Перенаправляет пользователей на страницу смены пароля при необходимости."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_view(
        self,
        request: HttpRequest,
        view_func: Callable[..., HttpResponse],
        view_args: list[object],
        view_kwargs: dict[str, object],
    ) -> HttpResponse | None:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None

        profile = getattr(user, "profile", None)
        if not isinstance(profile, UserProfile) or profile.password_changed_at:
            return None

        path = request.path_info
        if settings.STATIC_URL and path.startswith(settings.STATIC_URL):
            return None
        if settings.MEDIA_URL and path.startswith(settings.MEDIA_URL):
            return None

        try:
            match = resolve(path)
        except Resolver404:
            return None

        if match.app_name == "admin" and match.url_name == "logout":
            return None
        if match.app_name == "accounts" and match.url_name in {
            "force-password-change",
            "password-change",
            "password-change-done",
            "logout",
            "login",
        }:
            return None

        return redirect("accounts:force-password-change")
