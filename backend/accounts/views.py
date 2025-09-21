"""Views for the accounts app."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeDoneView,
    PasswordChangeView,
)
from django.http import HttpRequest, HttpResponse
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from .forms import StyledAuthenticationForm, StyledPasswordChangeForm


class AccountLoginView(LoginView):
    """Страница входа в систему."""

    template_name = "accounts/login.html"
    form_class = StyledAuthenticationForm

    def form_valid(self, form: StyledAuthenticationForm) -> HttpResponse:
        messages.success(self.request, _("Вы успешно вошли в систему."))
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return reverse_lazy("accounts:dashboard")


class AccountLogoutView(LogoutView):
    """Завершение сессии и возврат на форму входа."""

    next_page = reverse_lazy("accounts:login")

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        messages.success(request, _("Вы вышли из системы."))
        return super().dispatch(request, *args, **kwargs)


class AccountDashboardView(LoginRequiredMixin, TemplateView):
    """Простой дашборд, отображающий информацию о пользователе."""

    template_name = "accounts/dashboard.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["profile"] = getattr(self.request.user, "profile", None)
        return context


class AccountPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    """Смена пароля по инициативе пользователя."""

    template_name = "accounts/password_change_form.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("accounts:password-change-done")

    def form_valid(self, form: StyledPasswordChangeForm) -> HttpResponse:
        response = super().form_valid(form)
        profile = getattr(self.request.user, "profile", None)
        if profile:
            profile.mark_password_changed()
        messages.success(self.request, _("Пароль успешно обновлён."))
        return response


class AccountPasswordChangeDoneView(LoginRequiredMixin, PasswordChangeDoneView):
    """Подтверждение смены пароля."""

    template_name = "accounts/password_change_done.html"


