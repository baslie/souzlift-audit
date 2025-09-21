"""Views for managing catalog entities and imports."""
from __future__ import annotations

import json
from typing import Any, Sequence

from django.contrib import messages
from django.db.models import Count, Q, QuerySet
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from accounts.models import UserProfile
from accounts.permissions import AdminRequiredMixin, RoleRequiredMixin

from .forms import (
    BuildingForm,
    CatalogImportConfirmForm,
    CatalogImportUploadForm,
    ElevatorForm,
)
from .models import Building, CatalogImportLog, Elevator, ReviewStatus
from .services import (
    CatalogImportError,
    CatalogImportExecutionError,
    CatalogImportPreview,
    CatalogImportResult,
    build_building_preview,
    build_elevator_preview,
    import_buildings,
    import_elevators,
)


class CatalogListView(RoleRequiredMixin, ListView):
    """Base list view with shared search behaviour for catalog entities."""

    allowed_roles = (UserProfile.Roles.ADMIN, UserProfile.Roles.AUDITOR)
    search_param = "q"
    paginate_by = 25

    def get_search_query(self) -> str:
        return self.request.GET.get(self.search_param, "").strip()

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        queryset = super().get_queryset()
        query = self.get_search_query()
        if query:
            queryset = queryset.filter(self.get_search_filter(query))
        return queryset

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "search_param": self.search_param,
                "search_query": self.get_search_query(),
                "can_manage": bool(self.profile and self.profile.is_admin),
            }
        )
        return context

    def get_search_filter(self, query: str) -> Q:
        raise NotImplementedError


class BuildingListView(CatalogListView):
    model = Building
    template_name = "catalog/building_list.html"

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        queryset = (
            Building.objects.visible_for_user(self.request.user)
            .annotate(elevator_count=Count("elevators"))
            .select_related("created_by__profile")
            .order_by("address", "entrance")
        )
        query = self.get_search_query()
        if query:
            queryset = queryset.filter(
                Q(address__icontains=query)
                | Q(entrance__icontains=query)
                | Q(notes__icontains=query)
            )
        return queryset


class ElevatorListView(CatalogListView):
    model = Elevator
    template_name = "catalog/elevator_list.html"

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        queryset = (
            Elevator.objects.visible_for_user(self.request.user)
            .select_related("building", "created_by__profile")
            .order_by("building__address", "identifier")
        )
        query = self.get_search_query()
        if query:
            queryset = queryset.filter(
                Q(identifier__icontains=query)
                | Q(description__icontains=query)
                | Q(building__address__icontains=query)
            )
        return queryset


class CatalogAdminFormMixin(AdminRequiredMixin):
    """Shared logic for create and update views in the catalog."""

    success_message: str = ""
    success_url: str | None = None

    def get_success_url(self) -> str:
        if self.success_url is None:
            raise NotImplementedError("success_url must be defined")
        return str(self.success_url)

    def form_valid(self, form):  # type: ignore[override]
        instance = form.save(commit=False)
        user = self.request.user
        if getattr(user, "is_authenticated", False):
            if getattr(instance, "created_by_id", None) is None:
                instance.created_by = user
            if hasattr(instance, "verified_by"):
                instance.verified_by = user
            if hasattr(instance, "verified_at"):
                instance.verified_at = timezone.now()
        if hasattr(instance, "review_status"):
            instance.review_status = ReviewStatus.APPROVED
        instance.save()
        form.save_m2m()
        self.object = instance
        if self.success_message:
            messages.success(self.request, self.success_message)
        return HttpResponseRedirect(self.get_success_url())


class BuildingCreateView(CatalogAdminFormMixin, CreateView):
    model = Building
    form_class = BuildingForm
    template_name = "catalog/building_form.html"
    success_url = reverse_lazy("catalog:building-list")
    success_message = _("Здание сохранено.")


class BuildingUpdateView(CatalogAdminFormMixin, UpdateView):
    model = Building
    form_class = BuildingForm
    template_name = "catalog/building_form.html"
    success_url = reverse_lazy("catalog:building-list")
    success_message = _("Изменения сохранены.")


class BuildingDeleteView(AdminRequiredMixin, DeleteView):
    model = Building
    template_name = "catalog/object_confirm_delete.html"
    success_url = reverse_lazy("catalog:building-list")
    success_message = _("Здание удалено.")

    def delete(self, request, *args: Any, **kwargs: Any):  # type: ignore[override]
        response = super().delete(request, *args, **kwargs)
        messages.success(self.request, self.success_message)
        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = str(self.success_url)
        return context


class ElevatorCreateView(CatalogAdminFormMixin, CreateView):
    model = Elevator
    form_class = ElevatorForm
    template_name = "catalog/elevator_form.html"
    success_url = reverse_lazy("catalog:elevator-list")
    success_message = _("Лифт сохранён.")

    def get_form_kwargs(self):  # type: ignore[override]
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class ElevatorUpdateView(CatalogAdminFormMixin, UpdateView):
    model = Elevator
    form_class = ElevatorForm
    template_name = "catalog/elevator_form.html"
    success_url = reverse_lazy("catalog:elevator-list")
    success_message = _("Изменения сохранены.")

    def get_form_kwargs(self):  # type: ignore[override]
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class ElevatorDeleteView(AdminRequiredMixin, DeleteView):
    model = Elevator
    template_name = "catalog/object_confirm_delete.html"
    success_url = reverse_lazy("catalog:elevator-list")
    success_message = _("Лифт удалён.")

    def delete(self, request, *args: Any, **kwargs: Any):  # type: ignore[override]
        response = super().delete(request, *args, **kwargs)
        messages.success(self.request, self.success_message)
        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = str(self.success_url)
        return context


class BaseCatalogImportView(AdminRequiredMixin, TemplateView):
    """Shared logic for building and elevator import flows."""

    template_name = "catalog/import_form.html"
    upload_form_class = CatalogImportUploadForm
    confirm_form_class = CatalogImportConfirmForm
    success_url = ""
    success_message = _("Импорт завершён успешно.")
    entity: CatalogImportLog.Entity
    expected_columns: Sequence[tuple[str, str]] = ()
    page_title: str = ""
    page_subtitle: str = ""

    def get_success_url(self) -> str:
        if not self.success_url:
            raise NotImplementedError("success_url must be defined")
        return str(self.success_url)

    def get_preview(self, uploaded_file) -> CatalogImportPreview:
        raise NotImplementedError

    def run_import(self, rows: Sequence[dict[str, Any]]) -> CatalogImportResult:
        raise NotImplementedError

    def get_logs(self) -> QuerySet:
        return (
            CatalogImportLog.objects.filter(entity=self.entity)
            .select_related("created_by__profile")
            .order_by("-created_at")[:10]
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        context = super().get_context_data(**kwargs)
        context.setdefault("upload_form", self.upload_form_class())
        context.setdefault("confirm_form", self.confirm_form_class())
        context.setdefault("preview", None)
        context.setdefault("page_title", self.page_title)
        context.setdefault("page_subtitle", self.page_subtitle)
        context.setdefault("expected_columns", self.expected_columns)
        context["logs"] = self.get_logs()
        return context

    def post(self, request, *args: Any, **kwargs: Any):  # type: ignore[override]
        if "payload" in request.POST:
            return self._handle_confirm(request)
        return self._handle_upload(request)

    def _handle_upload(self, request):
        upload_form = self.upload_form_class(request.POST, request.FILES)
        if not upload_form.is_valid():
            return self.render_to_response(self.get_context_data(upload_form=upload_form))

        uploaded_file = upload_form.cleaned_data["file"]
        try:
            preview = self.get_preview(uploaded_file)
        except CatalogImportError as exc:
            messages.error(request, str(exc))
            return self.render_to_response(self.get_context_data(upload_form=self.upload_form_class()))

        if not preview.rows:
            messages.warning(request, _("Файл не содержит данных для импорта."))

        if preview.has_errors:
            messages.warning(
                request,
                _(
                    "Некоторые строки содержат ошибки и не будут импортированы. Исправьте файл или продолжите для загрузки корректных записей."
                ),
            )

        payload = json.dumps(preview.build_payload())
        confirm_form = self.confirm_form_class(initial={"payload": payload, "filename": preview.filename})
        context = self.get_context_data(
            preview=preview,
            upload_form=self.upload_form_class(),
            confirm_form=confirm_form,
        )
        context["payload"] = payload
        context["filename"] = preview.filename
        return self.render_to_response(context)

    def _handle_confirm(self, request):
        confirm_form = self.confirm_form_class(request.POST)
        if not confirm_form.is_valid():
            messages.error(request, _("Не удалось подтвердить импорт. Повторите попытку."))
            return self.render_to_response(self.get_context_data(confirm_form=confirm_form))

        payload_raw = confirm_form.cleaned_data["payload"]
        filename = confirm_form.cleaned_data.get("filename", "")
        try:
            rows = json.loads(payload_raw)
        except json.JSONDecodeError:
            messages.error(request, _("Переданы некорректные данные импорта."))
            return self.render_to_response(self.get_context_data())

        if not rows:
            messages.warning(request, _("Нет данных для импорта."))
            return self.render_to_response(self.get_context_data())

        try:
            result = self.run_import(rows)
        except CatalogImportExecutionError as exc:
            self._create_log(filename, exc.result, CatalogImportLog.Status.FAILED)
            messages.error(
                request,
                _("Импорт не выполнен из-за ошибок. Подробности см. в журнале ниже."),
            )
            return self.render_to_response(self.get_context_data())

        self._create_log(filename, result, CatalogImportLog.Status.SUCCESS)
        messages.success(request, self.success_message)
        return redirect(self.get_success_url())

    def _create_log(
        self,
        filename: str,
        result: CatalogImportResult,
        status: CatalogImportLog.Status,
    ) -> None:
        CatalogImportLog.objects.create(
            entity=self.entity,
            status=status,
            filename=filename or "",
            created_by=self.request.user if self.request.user.is_authenticated else None,
            total_rows=result.total_rows,
            created_count=result.created_count,
            updated_count=result.updated_count,
            error_rows=result.error_payload(),
            message=self.success_message if status == CatalogImportLog.Status.SUCCESS else "",
        )


class BuildingImportView(BaseCatalogImportView):
    entity = CatalogImportLog.Entity.BUILDING
    success_url = reverse_lazy("catalog:building-list")
    success_message = _("Импорт зданий завершён.")
    page_title = _("Импорт зданий")
    page_subtitle = _("Загрузите файл CSV или XLSX, чтобы добавить или обновить здания.")
    expected_columns = (
        ("address", _("Адрес (обязательно)")),
        ("entrance", _("Подъезд")),
        ("notes", _("Примечания")),
    )

    def get_preview(self, uploaded_file) -> CatalogImportPreview:
        return build_building_preview(uploaded_file)

    def run_import(self, rows: Sequence[dict[str, Any]]) -> CatalogImportResult:
        return import_buildings(rows, self.request.user)


class ElevatorImportView(BaseCatalogImportView):
    entity = CatalogImportLog.Entity.ELEVATOR
    success_url = reverse_lazy("catalog:elevator-list")
    success_message = _("Импорт лифтов завершён.")
    page_title = _("Импорт лифтов")
    page_subtitle = _(
        "Используйте файл CSV или XLSX для массового добавления лифтов. Здание должно существовать заранее."
    )
    expected_columns = (
        ("building_address", _("Адрес здания (обязательно)")),
        ("building_entrance", _("Подъезд")),
        ("identifier", _("Идентификатор лифта (обязательно)")),
        ("status", _("Статус")),
        ("description", _("Описание")),
    )

    def get_preview(self, uploaded_file) -> CatalogImportPreview:
        return build_elevator_preview(uploaded_file)

    def run_import(self, rows: Sequence[dict[str, Any]]) -> CatalogImportResult:
        return import_elevators(rows, self.request.user)


__all__ = [
    "BuildingCreateView",
    "BuildingDeleteView",
    "BuildingImportView",
    "BuildingListView",
    "BuildingUpdateView",
    "ElevatorCreateView",
    "ElevatorDeleteView",
    "ElevatorImportView",
    "ElevatorListView",
    "ElevatorUpdateView",
]
