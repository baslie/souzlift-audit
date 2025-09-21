"""Views for managing catalog entities."""
from __future__ import annotations

from typing import Iterable

from django.contrib import messages
from django.db.models import Q, QuerySet
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView, UpdateView

from accounts.models import UserProfile
from accounts.permissions import RoleRequiredMixin

from .forms import BuildingForm, ElevatorForm
from .models import Building, Elevator, ReviewStatus


class VisibleForUserQuerysetMixin(RoleRequiredMixin):
    model = Building
    allowed_roles = (UserProfile.Roles.ADMIN, UserProfile.Roles.AUDITOR)

    def prepare_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        queryset = self.model.objects.visible_for_user(self.request.user)
        return self.prepare_queryset(queryset)

    @property
    def profile(self) -> UserProfile | None:
        return getattr(self.request.user, "profile", None)


class BaseCatalogListView(VisibleForUserQuerysetMixin, ListView):
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

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "status_choices": list(self.get_status_choices()),
                "selected_status": self.get_status_filter(),
                "search_query": self.get_search_query(),
                "search_param": self.search_param,
                "status_param": self.status_param,
                "can_moderate": bool(self.profile and self.profile.is_admin),
                "ReviewStatus": ReviewStatus,
            }
        )
        return context


class BuildingListView(BaseCatalogListView):
    model = Building
    template_name = "catalog/building_list.html"

    def prepare_queryset(self, queryset: QuerySet) -> QuerySet:  # type: ignore[override]
        return queryset.select_related("created_by__profile", "verified_by__profile")

    def get_search_filter(self, query: str) -> Q:
        return Q(address__icontains=query) | Q(entrance__icontains=query) | Q(notes__icontains=query)


class ElevatorListView(BaseCatalogListView):
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
    model = Building
    form_class = BuildingForm
    template_name = "catalog/building_form.html"
    success_url = reverse_lazy("catalog:building-list")
    success_message = _("Здание сохранено и отправлено на модерацию.")


class BuildingUpdateView(CatalogFormMixin, UpdateView):
    model = Building
    form_class = BuildingForm
    template_name = "catalog/building_form.html"
    success_url = reverse_lazy("catalog:building-list")
    success_message = _("Изменения сохранены. Запись будет отображаться после утверждения администратора.")


class ElevatorCreateView(CatalogFormMixin, CreateView):
    model = Elevator
    form_class = ElevatorForm
    template_name = "catalog/elevator_form.html"
    success_url = reverse_lazy("catalog:elevator-list")
    success_message = _("Лифт сохранён и отправлен на модерацию.")

    def get_form_kwargs(self):  # type: ignore[override]
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class ElevatorUpdateView(CatalogFormMixin, UpdateView):
    model = Elevator
    form_class = ElevatorForm
    template_name = "catalog/elevator_form.html"
    success_url = reverse_lazy("catalog:elevator-list")
    success_message = _("Изменения лифта сохранены. После подтверждения они будут доступны аудиторам.")

    def get_form_kwargs(self):  # type: ignore[override]
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs
