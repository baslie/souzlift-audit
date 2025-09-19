"""Views for the audits application."""
from __future__ import annotations

import mimetypes
import os
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.signing import BadSignature, SignatureExpired
from django.db.models import Count, Q, QuerySet
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import ListView, TemplateView

from accounts.models import UserProfile
from accounts.permissions import RoleQuerysetMixin, RoleRequiredMixin, is_admin

from .models import AttachmentLimits, Audit, AuditAttachment
from .tokens import read_attachment_token
from .services import build_catalog_snapshot_for_user, build_checklist_structure


class AuditListView(RoleQuerysetMixin, ListView):
    """List of audits available to the current user with filtering support."""

    model = Audit
    template_name = "audits/audit_list.html"
    context_object_name = "audits"
    paginate_by = 20
    ordering = "-created_at"
    allowed_roles = (UserProfile.Roles.AUDITOR, UserProfile.Roles.ADMIN)

    search_param = "q"
    status_param = "status"
    period_param = "period"

    _role_filtered_queryset: QuerySet[Audit] | None = None
    _status_filter: str | None = None
    _period_filter_value: str | None = None
    _search_query: str | None = None

    def dispatch(self, request, *args, **kwargs):  # type: ignore[override]
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Audit]:  # type: ignore[override]
        queryset = (
            super()
            .get_queryset()
            .select_related("elevator", "elevator__building", "created_by__profile")
        )
        self._role_filtered_queryset = queryset
        queryset = self.filter_by_status(queryset)
        queryset = self.filter_by_period(queryset)
        queryset = self.apply_search(queryset)
        return queryset.order_by(self.ordering)

    # --- filters ---------------------------------------------------------

    def get_status_choices(self) -> list[tuple[str, str]]:
        return [("", _("Все статусы"))] + list(Audit.Status.choices)

    def get_period_choices(self) -> list[tuple[str, str]]:
        return [
            ("", _("За всё время")),
            ("7", _("За последние 7 дней")),
            ("30", _("За последние 30 дней")),
            ("90", _("За последние 90 дней")),
        ]

    def get_status_filter(self) -> str:
        if self._status_filter is not None:
            return self._status_filter
        raw = self.request.GET.get(self.status_param, "").strip()
        valid_values = {value for value, _ in self.get_status_choices() if value}
        self._status_filter = raw if raw in valid_values else ""
        return self._status_filter

    def get_period_filter(self) -> int | None:
        raw = self.request.GET.get(self.period_param, "").strip()
        self._period_filter_value = raw
        if not raw:
            return None
        valid_values = {value for value, _ in self.get_period_choices() if value}
        if raw not in valid_values:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def get_search_query(self) -> str:
        if self._search_query is None:
            self._search_query = self.request.GET.get(self.search_param, "").strip()
        return self._search_query

    def filter_by_status(self, queryset: QuerySet[Audit]) -> QuerySet[Audit]:
        status = self.get_status_filter()
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def filter_by_period(self, queryset: QuerySet[Audit]) -> QuerySet[Audit]:
        period_days = self.get_period_filter()
        if period_days:
            threshold = timezone.now() - timedelta(days=period_days)
            queryset = queryset.filter(created_at__gte=threshold)
        return queryset

    def apply_search(self, queryset: QuerySet[Audit]) -> QuerySet[Audit]:
        query = self.get_search_query()
        if not query:
            return queryset
        return queryset.filter(
            Q(elevator__identifier__icontains=query)
            | Q(elevator__building__address__icontains=query)
        )

    def get_preserved_querystring(self) -> str:
        params = self.request.GET.copy()
        params.pop("page", None)
        non_empty = {key: value for key, value in params.items() if value}
        return urlencode(non_empty)

    # --- context ---------------------------------------------------------

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        base_queryset = self._role_filtered_queryset or self.model.objects.none()
        summary = {
            entry["status"]: entry["total"]
            for entry in base_queryset.values("status").annotate(total=Count("id"))
        }
        total_count = base_queryset.count()

        status_filter = self.get_status_filter()
        status_filters: list[dict[str, object]] = []
        for value, label in self.get_status_choices():
            if value:
                count = summary.get(value, 0)
            else:
                count = total_count
            status_filters.append(
                {
                    "value": value,
                    "label": label,
                    "count": count,
                    "selected": value == status_filter,
                }
            )

        period_value = self._period_filter_value or ""
        period_filters = [
            {
                "value": value,
                "label": label,
                "selected": value == period_value,
            }
            for value, label in self.get_period_choices()
        ]

        active_filters: list[dict[str, str]] = []
        if status_filter:
            status_label = next(
                (label for value, label in self.get_status_choices() if value == status_filter),
                status_filter,
            )
            active_filters.append({"label": _("Статус"), "value": status_label})
        if period_value:
            period_label = next(
                (label for value, label in self.get_period_choices() if value == period_value),
                period_value,
            )
            active_filters.append({"label": _("Период"), "value": period_label})
        search_query = self.get_search_query()
        if search_query:
            active_filters.append({"label": _("Поиск"), "value": search_query})

        context.update(
            {
                "status_filters": status_filters,
                "period_filters": period_filters,
                "active_filters": active_filters,
                "search_query": search_query,
                "search_param": self.search_param,
                "status_param": self.status_param,
                "period_param": self.period_param,
                "querystring": self.get_preserved_querystring(),
                "AuditStatus": Audit.Status,
                "catalog_snapshot_url": reverse("catalog-snapshot"),
            }
        )
        badge_classes = self.get_status_badge_classes()
        default_class = "border-slate-200 bg-slate-50 text-slate-600"
        page_obj = context.get("page_obj")
        if page_obj is None:
            possible_page = context.get(self.context_object_name)
            if hasattr(possible_page, "object_list"):
                page_obj = possible_page
        if hasattr(page_obj, "object_list"):
            for audit in getattr(page_obj, "object_list", []):
                setattr(audit, "badge_class", badge_classes.get(audit.status, default_class))
        context["default_status_badge_class"] = default_class
        return context

    @staticmethod
    def get_status_badge_classes() -> dict[str, str]:
        return {
            Audit.Status.DRAFT: "border-slate-300 bg-slate-50 text-slate-700",
            Audit.Status.IN_PROGRESS: "border-amber-200 bg-amber-50 text-amber-800",
            Audit.Status.SUBMITTED: "border-sky-200 bg-sky-50 text-sky-800",
            Audit.Status.REVIEWED: "border-emerald-200 bg-emerald-50 text-emerald-800",
        }


class AttachmentDownloadView(LoginRequiredMixin, View):
    """Serve audit attachments through authenticated, signed URLs."""

    http_method_names = ["get"]

    def get(self, request, token: str, *args, **kwargs) -> HttpResponse:  # type: ignore[override]
        try:
            attachment_id = read_attachment_token(token)
        except SignatureExpired as exc:
            raise Http404("Ссылка для скачивания истекла.") from exc
        except BadSignature as exc:
            raise Http404("Недействительная ссылка для скачивания.") from exc

        attachment = (
            AuditAttachment.objects.select_related("response__audit__created_by")
            .filter(pk=attachment_id)
            .first()
        )
        if attachment is None or not attachment.file:
            raise Http404("Вложение не найдено.")

        audit = attachment.response.audit
        user = request.user
        if not self._user_can_access(user, audit.created_by_id):
            raise Http404("Вложение не найдено.")

        storage = attachment.file.storage
        if not storage.exists(attachment.file.name):
            raise Http404("Файл вложения отсутствует на сервере.")

        filename = os.path.basename(attachment.file.name)
        content_type, _ = mimetypes.guess_type(filename)
        file_handle = attachment.file.open("rb")

        response = FileResponse(file_handle, as_attachment=True, filename=filename)
        if content_type:
            response.headers["Content-Type"] = content_type
        return response

    @staticmethod
    def _user_can_access(user: object, author_id: int | None) -> bool:
        if not hasattr(user, "is_authenticated") or not user.is_authenticated:
            return False
        if is_admin(user):
            return True
        return getattr(user, "pk", None) == author_id


class OfflineObjectInfoView(RoleRequiredMixin, TemplateView):
    """Offline-friendly form for filling audit object information."""

    template_name = "audits/offline_object_info.html"
    allowed_roles = (UserProfile.Roles.AUDITOR, UserProfile.Roles.ADMIN)

    def dispatch(self, request, *args, **kwargs):  # type: ignore[override]
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        client_id = self.request.GET.get("client_id", "").strip()
        snapshot = build_catalog_snapshot_for_user(self.request.user)
        context.update(
            {
                "client_id": client_id,
                "catalog_snapshot_url": reverse("catalog-snapshot"),
                "object_info_fields": snapshot.get("object_fields", []),
                "catalog_payload": {
                    "buildings": snapshot.get("buildings", []),
                    "elevators": snapshot.get("elevators", []),
                },
                "catalog_metadata": {
                    "generated_at": snapshot.get("generated_at"),
                },
                "return_url": reverse("audits:audit-list"),
            }
        )
        return context


class OfflineChecklistView(RoleRequiredMixin, TemplateView):
    """Offline-friendly checklist form for auditors."""

    template_name = "audits/offline_checklist.html"
    allowed_roles = (UserProfile.Roles.AUDITOR, UserProfile.Roles.ADMIN)

    def dispatch(self, request, *args, **kwargs):  # type: ignore[override]
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        client_id = self.request.GET.get("client_id", "").strip()
        checklist = build_checklist_structure()
        limits = AttachmentLimits()
        max_size_mb = limits.max_size_bytes / (1024 * 1024)

        context.update(
            {
                "client_id": client_id,
                "checklist": checklist,
                "attachment_limits": limits,
                "max_attachment_size_mb": max_size_mb,
                "return_url": reverse("audits:audit-list"),
            }
        )
        return context


__all__ = [
    "AuditListView",
    "AttachmentDownloadView",
    "OfflineChecklistView",
    "OfflineObjectInfoView",
]
