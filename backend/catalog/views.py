"""Views for catalog management in the user-facing interface."""
from __future__ import annotations

from typing import Iterable
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from accounts.models import UserProfile
from accounts.permissions import AdminRequiredMixin, RoleRequiredMixin

from .forms import BuildingForm, ElevatorForm
from .models import Building, Elevator, ReviewStatus


class VisibleForUserQuerysetMixin(RoleRequiredMixin):
    """Базовый mixin, ограничивающий queryset доступными пользователю записями."""

    model: type[Building | Elevator]
    allowed_roles = (UserProfile.Roles.ADMIN, UserProfile.Roles.AUDITOR)

    def prepare_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        queryset = self.model.objects.visible_for_user(self.request.user)
        return self.prepare_queryset(queryset)


class BaseCatalogListView(VisibleForUserQuerysetMixin, ListView):
    """Общий список записей справочника с фильтрацией и поиском."""

    paginate_by = 20
    ordering = "-created_at"
    status_param = "status"
    search_param = "q"

    def get_status_choices(self) -> Iterable[tuple[str, str]]:
        return (
            ("", _("Все статусы")),
            (ReviewStatus.PENDING, _("Ожидают утверждения")),
            (ReviewStatus.APPROVED, _("Утверждённые")),
            (ReviewStatus.REJECTED, _("Отклонённые")),
            ("mine", _("Созданные мной")),
        )

    def get_status_filter(self) -> str:
        value = self.request.GET.get(self.status_param, "").strip()
        valid_values = {choice for choice, _ in self.get_status_choices() if choice}
        if value in valid_values or value == "mine":
            return value
        return ""

    def get_search_query(self) -> str:
        return self.request.GET.get(self.search_param, "").strip()

    def filter_queryset_by_status(self, queryset: QuerySet) -> QuerySet:
        status = self.get_status_filter()
        if not status:
            return queryset
        if status == "mine":
            return queryset.filter(created_by=self.request.user)
        return queryset.filter(review_status=status)

    def apply_search(self, queryset: QuerySet) -> QuerySet:
        query = self.get_search_query()
        if not query:
            return queryset
        return queryset.filter(self.get_search_filter(query))

    def get_search_filter(self, query: str) -> Q:
        raise NotImplementedError

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        queryset = super().get_queryset().order_by(self.ordering)
        queryset = self.filter_queryset_by_status(queryset)
        return self.apply_search(queryset)

    def get_preserved_querystring(self) -> str:
        params = self.request.GET.copy()
        params.pop("page", None)
        encoded = urlencode({k: v for k, v in params.items() if v})
        return encoded

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "status_choices": list(self.get_status_choices()),
                "selected_status": self.get_status_filter(),
                "search_query": self.get_search_query(),
                "search_param": self.search_param,
                "status_param": self.status_param,
                "querystring": self.get_preserved_querystring(),
                "can_moderate": bool(self.profile and self.profile.is_admin),
                "ReviewStatus": ReviewStatus,
            }
        )
        return context


class BuildingListView(BaseCatalogListView):
    """Список зданий с фильтрами и управлением модерацией."""

    model = Building
    template_name = "catalog/building_list.html"

    def prepare_queryset(self, queryset: QuerySet) -> QuerySet:  # type: ignore[override]
        return queryset.select_related("created_by__profile", "verified_by__profile")

    def get_search_filter(self, query: str) -> Q:
        return Q(address__icontains=query) | Q(entrance__icontains=query) | Q(notes__icontains=query)


class ElevatorListView(BaseCatalogListView):
    """Список лифтов с фильтрами и возможностью модерации."""

    model = Elevator
    template_name = "catalog/elevator_list.html"

    def prepare_queryset(self, queryset: QuerySet) -> QuerySet:  # type: ignore[override]
        return queryset.select_related("building", "created_by__profile", "verified_by__profile")

    def get_search_filter(self, query: str) -> Q:
        return (
            Q(identifier__icontains=query)
            | Q(description__icontains=query)
            | Q(building__address__icontains=query)
        )


class CatalogFormMixin(VisibleForUserQuerysetMixin):
    """Общие настройки для форм создания и редактирования каталога."""

    success_url: str | None = None
    success_message: str = ""

    def get_success_url(self) -> str:
        if self.success_url is not None:
            return str(self.success_url)
        raise NotImplementedError("success_url must be defined")

    def form_valid(self, form):  # type: ignore[override]
        if form.instance.created_by_id is None:
            form.instance.created_by = self.request.user
        response = super().form_valid(form)
        if self.success_message:
            messages.success(self.request, self.success_message)
        return response


class BuildingCreateView(CatalogFormMixin, CreateView):
    """Создание новой записи здания."""

    model = Building
    form_class = BuildingForm
    template_name = "catalog/building_form.html"
    success_url = reverse_lazy("catalog:building-list")
    success_message = _("Здание сохранено и отправлено на модерацию.")


class BuildingUpdateView(CatalogFormMixin, UpdateView):
    """Редактирование здания."""

    model = Building
    form_class = BuildingForm
    template_name = "catalog/building_form.html"
    success_url = reverse_lazy("catalog:building-list")
    success_message = _("Изменения сохранены. Запись будет отображаться после утверждения администратора.")

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        return Building.objects.select_related("created_by", "verified_by")

    def get_object(self, queryset: QuerySet | None = None):  # type: ignore[override]
        building = super().get_object(queryset)
        if not (self.profile and self.profile.is_admin):
            if building.created_by_id != self.request.user.id:
                raise PermissionDenied("Нельзя редактировать запись, созданную другим пользователем.")
            if building.review_status == ReviewStatus.APPROVED:
                raise PermissionDenied("Нельзя редактировать утверждённую запись.")
        return building

    def form_valid(self, form):  # type: ignore[override]
        is_admin = bool(self.profile and self.profile.is_admin)
        response = super().form_valid(form)
        if not is_admin and self.object.review_status != ReviewStatus.PENDING:
            self.object.send_to_review()
        return response


class ElevatorCreateView(CatalogFormMixin, CreateView):
    """Создание новой записи лифта."""

    model = Elevator
    form_class = ElevatorForm
    template_name = "catalog/elevator_form.html"
    success_url = reverse_lazy("catalog:elevator-list")
    success_message = _("Лифт сохранён и отправлен на модерацию.")

    def get_form_kwargs(self) -> dict[str, object]:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class ElevatorUpdateView(CatalogFormMixin, UpdateView):
    """Редактирование лифта."""

    model = Elevator
    form_class = ElevatorForm
    template_name = "catalog/elevator_form.html"
    success_url = reverse_lazy("catalog:elevator-list")
    success_message = _("Изменения сохранены. Запись вернётся в очередь на проверку.")

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        return Elevator.objects.select_related("building", "created_by", "verified_by")

    def get_form_kwargs(self) -> dict[str, object]:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_object(self, queryset: QuerySet | None = None):  # type: ignore[override]
        elevator = super().get_object(queryset)
        if not (self.profile and self.profile.is_admin):
            if elevator.created_by_id != self.request.user.id:
                raise PermissionDenied("Нельзя редактировать лифт другого пользователя.")
            if elevator.review_status == ReviewStatus.APPROVED:
                raise PermissionDenied("Нельзя редактировать утверждённую запись.")
        return elevator

    def form_valid(self, form):  # type: ignore[override]
        is_admin = bool(self.profile and self.profile.is_admin)
        response = super().form_valid(form)
        if not is_admin and self.object.review_status != ReviewStatus.PENDING:
            self.object.send_to_review()
        return response


class BuildingModerationView(AdminRequiredMixin, View):
    """Обработчик действий модерации для зданий."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest, pk: int, *args: object, **kwargs: object) -> HttpResponse:
        building = get_object_or_404(
            Building.objects.select_related("created_by", "verified_by"), pk=pk
        )
        action = request.POST.get("action")
        next_url = request.POST.get("next") or reverse_lazy("catalog:building-list")

        if action == "approve":
            building.approve(request.user)
            messages.success(request, _("Здание утверждено и доступно всем пользователям."))
        elif action == "reject":
            building.reject(request.user)
            messages.warning(request, _("Запись отклонена и скрыта из справочника."))
        elif action == "return":
            building.send_to_review()
            messages.info(request, _("Запись возвращена в очередь на проверку."))
        else:
            messages.error(request, _("Неизвестное действие модерации."))

        return redirect(next_url)


class ElevatorModerationView(AdminRequiredMixin, View):
    """Обработчик действий модерации для лифтов."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest, pk: int, *args: object, **kwargs: object) -> HttpResponse:
        elevator = get_object_or_404(
            Elevator.objects.select_related("building", "created_by", "verified_by"), pk=pk
        )
        action = request.POST.get("action")
        next_url = request.POST.get("next") or reverse_lazy("catalog:elevator-list")

        if action == "approve":
            elevator.approve(request.user)
            messages.success(request, _("Лифт утверждён и доступен всем пользователям."))
        elif action == "reject":
            elevator.reject(request.user)
            messages.warning(request, _("Запись отклонена и скрыта из справочника."))
        elif action == "return":
            elevator.send_to_review()
            messages.info(request, _("Запись возвращена на повторную проверку."))
        else:
            messages.error(request, _("Неизвестное действие модерации."))

        return redirect(next_url)

