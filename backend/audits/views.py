"""Views for the audits application."""
from __future__ import annotations

import csv
import io
import mimetypes
import os
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.signing import BadSignature, SignatureExpired
from django.db.models import Count, Prefetch, Q, QuerySet
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import ListView, TemplateView

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from accounts.models import UserProfile
from accounts.permissions import (
    RoleQuerysetMixin,
    RoleRequiredMixin,
    is_admin,
    restrict_queryset_for_user,
)

from .forms import AuditRequestChangesForm
from .models import AttachmentLimits, Audit, AuditAttachment, AuditResponse
from .tokens import read_attachment_token
from .reporting import build_audit_report
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
    review_param = "review"

    _role_filtered_queryset: QuerySet[Audit] | None = None
    _status_filter: str | None = None
    _period_filter_value: str | None = None
    _search_query: str | None = None
    _review_filter_value: str | None = None

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
        queryset = self.filter_by_review_state(queryset)
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

    def get_review_choices(self) -> list[tuple[str, str]]:
        return [
            ("", _("Все аудиты")),
            ("pending", _("Ожидают проверки")),
            ("active", _("В работе")),
            ("reviewed", _("Просмотренные")),
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

    def get_review_filter(self) -> str:
        if not is_admin(self.request.user):
            return ""
        if self._review_filter_value is not None:
            return self._review_filter_value
        raw = self.request.GET.get(self.review_param, "").strip()
        valid_values = {value for value, _ in self.get_review_choices() if value}
        self._review_filter_value = raw if raw in valid_values else ""
        return self._review_filter_value

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

    def filter_by_review_state(self, queryset: QuerySet[Audit]) -> QuerySet[Audit]:
        if not is_admin(self.request.user):
            return queryset
        review_value = self.get_review_filter()
        if review_value == "pending":
            return queryset.filter(status=Audit.Status.SUBMITTED)
        if review_value == "active":
            return queryset.filter(status__in=[Audit.Status.DRAFT, Audit.Status.IN_PROGRESS])
        if review_value == "reviewed":
            return queryset.filter(status=Audit.Status.REVIEWED)
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

        review_value = self.get_review_filter()
        review_filters: list[dict[str, object]] = []
        if is_admin(self.request.user):
            for value, label in self.get_review_choices():
                review_filters.append(
                    {
                        "value": value,
                        "label": label,
                        "selected": value == review_value,
                    }
                )
            if review_value:
                review_label = next(
                    (label for value, label in self.get_review_choices() if value == review_value),
                    review_value,
                )
                active_filters.append({"label": _("Проверка"), "value": review_label})

        context.update(
            {
                "status_filters": status_filters,
                "period_filters": period_filters,
                "active_filters": active_filters,
                "search_query": search_query,
                "search_param": self.search_param,
                "status_param": self.status_param,
                "period_param": self.period_param,
                "review_filters": review_filters,
                "review_param": self.review_param,
                "querystring": self.get_preserved_querystring(),
                "AuditStatus": Audit.Status,
                "catalog_snapshot_url": reverse("catalog-snapshot"),
                "is_admin": is_admin(self.request.user),
            }
        )
        badge_classes = self.get_status_badge_classes()
        default_class = "border-border-subtle bg-surface-subtle text-ink-600"
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
            Audit.Status.DRAFT: "border-border bg-surface-muted text-ink-700",
            Audit.Status.IN_PROGRESS: "border-warning-200 bg-warning-50 text-warning-700",
            Audit.Status.SUBMITTED: "border-brand-200 bg-brand-50 text-brand-700",
            Audit.Status.REVIEWED: "border-success-200 bg-success-50 text-success-700",
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


class AuditExportBaseView(RoleRequiredMixin):
    """Shared helpers for audit export views."""

    allowed_roles = (UserProfile.Roles.AUDITOR, UserProfile.Roles.ADMIN)

    _audit_instance: Audit | None = None
    _report_cache: dict[str, object] | None = None
    _checklist_structure: dict[str, object] | None = None

    def dispatch(self, request, *args, **kwargs):  # type: ignore[override]
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Audit]:  # type: ignore[override]
        response_qs = (
            AuditResponse.objects.select_related(
                "question",
                "question__section",
                "question__section__category",
            )
            .prefetch_related(
                Prefetch(
                    "attachments",
                    queryset=AuditAttachment.objects.order_by("uploaded_at"),
                )
            )
            .order_by(
                "question__section__category__order",
                "question__section__order",
                "question__order",
                "question_id",
            )
        )
        base_qs = (
            Audit.objects.select_related("elevator", "elevator__building", "created_by")
            .prefetch_related(Prefetch("responses", queryset=response_qs))
            .order_by("-created_at", "-id")
        )
        return restrict_queryset_for_user(
            base_qs, self.request.user, auditor_field="created_by"
        )

    def get_audit(self) -> Audit:
        if self._audit_instance is None:
            pk = self.kwargs.get("pk")
            audit = self.get_queryset().filter(pk=pk).first()
            if audit is None:
                raise Http404("Аудит не найден или недоступен.")
            self._audit_instance = audit
        return self._audit_instance

    def get_checklist_structure(self) -> dict[str, object]:
        if self._checklist_structure is None:
            self._checklist_structure = build_checklist_structure()
        return self._checklist_structure

    def get_report(self) -> dict[str, object]:
        if self._report_cache is None:
            self._report_cache = build_audit_report(
                self.get_audit(), checklist_structure=self.get_checklist_structure()
            )
        return self._report_cache

    def format_datetime(self, value) -> str:
        if value is None:
            return ""
        return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")

    def format_flag(self, value: bool) -> str:
        return str(_("Да")) if value else str(_("Нет"))

    def format_attachments(self, attachments: list[AuditAttachment]) -> str:
        if not attachments:
            return ""
        items: list[str] = []
        for attachment in attachments:
            url = attachment.get_download_url()
            if hasattr(self, "request"):
                url = self.request.build_absolute_uri(url)
            caption = (attachment.caption or "").strip()
            if caption:
                items.append(f"{caption} ({url})")
            else:
                items.append(url)
        return "; ".join(items)

    def get_question_answer(self, question: dict[str, object]) -> str:
        if question.get("type") == "text":
            return str(question.get("answer_display") or "—")
        return str(question.get("value_display") or "—")

    def get_question_comment(self, question: dict[str, object]) -> str:
        if question.get("type") == "text":
            return ""
        return str(question.get("comment_display") or "")


class AuditDetailView(AuditExportBaseView, TemplateView):
    """Detailed view for administrators to review a specific audit."""

    template_name = "audits/admin_audit_detail.html"
    allowed_roles = (UserProfile.Roles.ADMIN,)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        audit = self.get_audit()
        report = self.get_report()
        badge_classes = AuditListView.get_status_badge_classes()
        default_badge = "border-border-subtle bg-surface-subtle text-ink-600"
        request_changes_form = kwargs.get("request_changes_form") or context.get(
            "request_changes_form"
        )
        if request_changes_form is None:
            request_changes_form = AuditRequestChangesForm()

        context.update(
            {
                "audit": audit,
                "report": report,
                "summary": report.get("summary", {}),
                "checklist": report.get("checklist", []),
                "object_info": report.get("object_info", []),
                "object_info_has_values": report.get("object_info_has_values", False),
                "object_info_has_extra": report.get("object_info_has_extra", False),
                "can_mark_reviewed": audit.status == Audit.Status.SUBMITTED,
                "can_request_changes": audit.status == Audit.Status.SUBMITTED,
                "request_changes_form": request_changes_form,
                "back_url": self.get_back_url(),
                "status_badge_class": badge_classes.get(audit.status, default_badge),
                "default_status_badge_class": default_badge,
                "AuditStatus": Audit.Status,
            }
        )
        return context

    def get_back_url(self) -> str:
        candidate = self.request.GET.get("next") or self.request.GET.get("back")
        if candidate and url_has_allowed_host_and_scheme(
            candidate,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return candidate
        return reverse("audits:audit-list")


class AuditMarkReviewedView(RoleRequiredMixin, View):
    """Mark an audit as reviewed from the administrator interface."""

    allowed_roles = (UserProfile.Roles.ADMIN,)

    def get_queryset(self) -> QuerySet[Audit]:
        base_qs = Audit.objects.select_related(
            "elevator",
            "elevator__building",
            "created_by",
            "created_by__profile",
        )
        return restrict_queryset_for_user(base_qs, self.request.user, auditor_field="created_by")

    def post(self, request, *args, **kwargs):  # type: ignore[override]
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        pk = kwargs.get("pk")
        audit = self.get_queryset().filter(pk=pk).first()
        if audit is None:
            raise Http404("Аудит не найден или недоступен.")

        if audit.status == Audit.Status.REVIEWED:
            messages.info(request, _("Аудит уже отмечен как просмотренный."))
        elif audit.status != Audit.Status.SUBMITTED:
            messages.warning(request, _("Отметить просмотр можно только для отправленных аудитов."))
        else:
            audit.mark_reviewed(actor=request.user)
            messages.success(request, _("Аудит отмечен как просмотренный."))

        next_url = (request.POST.get("next") or "").strip()
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("audits:audit-detail", pk=audit.pk)


class AuditRequestChangesView(AuditDetailView):
    """Handle administrator requests for auditor corrections."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):  # type: ignore[override]
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        audit = self.get_audit()
        form = AuditRequestChangesForm(request.POST)

        if audit.status != Audit.Status.SUBMITTED:
            messages.warning(
                request,
                _("Запросить правки можно только для отправленных аудитов."),
            )
            return redirect("audits:audit-detail", pk=audit.pk)

        if not form.is_valid():
            context = self.get_context_data(request_changes_form=form)
            return self.render_to_response(context, status=400)

        audit.request_changes(actor=request.user, message=form.cleaned_data["message"])
        messages.success(request, _("Запрос на правки отправлен автору аудита."))

        next_url = (request.POST.get("next") or "").strip()
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("audits:audit-detail", pk=audit.pk)


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


class AuditPrintView(AuditExportBaseView, TemplateView):
    """Render a printable HTML representation of an audit."""

    template_name = "audits/export_print.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        report = self.get_report()
        checklist_display: list[dict[str, object]] = []
        for category in report["checklist"]:
            section_entries: list[dict[str, object]] = []
            for section in category["sections"]:
                question_entries: list[dict[str, object]] = []
                for question in section["questions"]:
                    attachments_info = [
                        {
                            "caption": attachment.caption,
                            "url": self.request.build_absolute_uri(
                                attachment.get_download_url()
                            ),
                        }
                        for attachment in question.get("attachments", [])
                    ]
                    question_copy = question.copy()
                    question_copy["attachments_for_display"] = attachments_info
                    question_entries.append(question_copy)
                section_entries.append(
                    {
                        "title": section.get("title"),
                        "description": section.get("description"),
                        "questions": question_entries,
                    }
                )
            checklist_display.append(
                {
                    "name": category.get("name"),
                    "sections": section_entries,
                }
            )
        context.update(
            {
                "audit": self.get_audit(),
                "report": report,
                "object_info": report["object_info"],
                "object_info_has_values": report["object_info_has_values"],
                "checklist": checklist_display,
                "summary": report["summary"],
            }
        )
        return context


class AuditCSVExportView(AuditExportBaseView, View):
    """Generate a CSV export for an audit."""

    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):  # type: ignore[override]
        audit = self.get_audit()
        report = self.get_report()
        summary = report["summary"]

        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)

        metadata_rows = [
            ("Аудит", f"#{audit.pk}"),
            ("Объект", str(audit.elevator.building)),
            ("Лифт", audit.elevator.identifier),
            ("Статус", audit.get_status_display()),
            ("Автор", str(audit.created_by)),
            ("Суммарный балл", audit.total_score),
            ("Плановая дата", audit.planned_date.isoformat() if audit.planned_date else ""),
            ("Начато", self.format_datetime(audit.started_at)),
            ("Завершено", self.format_datetime(audit.finished_at)),
            ("Всего вопросов", summary["total_questions"]),
            ("Заполнено", summary["answered_questions"]),
            ("Комментарии", summary["comments_total"]),
            ("Вложения", summary["attachments_total"]),
            ("Пометки", summary["flagged_total"]),
        ]
        writer.writerows(metadata_rows)
        writer.writerow([])
        writer.writerow(
            [
                "Категория",
                "Раздел",
                "Вопрос",
                "Ответ",
                "Комментарий",
                "Пометка",
                "Вложения",
            ]
        )

        for category in report["checklist"]:
            for section in category["sections"]:
                for question in section["questions"]:
                    attachments = self.format_attachments(question.get("attachments", []))
                    writer.writerow(
                        [
                            category.get("name", ""),
                            section.get("title", ""),
                            question.get("text", ""),
                            self.get_question_answer(question),
                            self.get_question_comment(question),
                            self.format_flag(bool(question.get("is_flagged"))),
                            attachments,
                        ]
                    )

        response = HttpResponse(
            buffer.getvalue().encode("utf-8-sig"),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="audit-{audit.pk}.csv"'
        return response


class AuditExcelExportView(AuditExportBaseView, View):
    """Generate an XLSX spreadsheet with audit results."""

    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):  # type: ignore[override]
        audit = self.get_audit()
        report = self.get_report()
        summary = report["summary"]

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Аудит"

        workbook.properties.title = f"Audit #{audit.pk}"

        meta_rows = [
            ["Аудит", f"#{audit.pk}"],
            ["Объект", str(audit.elevator.building)],
            ["Лифт", audit.elevator.identifier],
            ["Статус", audit.get_status_display()],
            ["Автор", str(audit.created_by)],
            ["Суммарный балл", audit.total_score],
            ["Плановая дата", audit.planned_date.isoformat() if audit.planned_date else ""],
            ["Начато", self.format_datetime(audit.started_at)],
            ["Завершено", self.format_datetime(audit.finished_at)],
            ["Всего вопросов", summary["total_questions"]],
            ["Заполнено", summary["answered_questions"]],
            ["Комментарии", summary["comments_total"]],
            ["Вложения", summary["attachments_total"]],
            ["Пометки", summary["flagged_total"]],
        ]
        for row in meta_rows:
            sheet.append(row)

        sheet.append([])
        header_row_index = sheet.max_row + 1
        sheet.append(
            [
                "Категория",
                "Раздел",
                "Вопрос",
                "Ответ",
                "Комментарий",
                "Пометка",
                "Вложения",
            ]
        )

        for category in report["checklist"]:
            for section in category["sections"]:
                for question in section["questions"]:
                    attachments = self.format_attachments(question.get("attachments", []))
                    sheet.append(
                        [
                            category.get("name", ""),
                            section.get("title", ""),
                            question.get("text", ""),
                            self.get_question_answer(question),
                            self.get_question_comment(question),
                            self.format_flag(bool(question.get("is_flagged"))),
                            attachments,
                        ]
                    )

        column_widths = {
            1: 24,
            2: 24,
            3: 60,
            4: 18,
            5: 40,
            6: 12,
            7: 50,
        }
        for column_index, width in column_widths.items():
            sheet.column_dimensions[get_column_letter(column_index)].width = width

        sheet.freeze_panes = f"A{header_row_index + 1}"

        output = io.BytesIO()
        workbook.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = f'attachment; filename="audit-{audit.pk}.xlsx"'
        return response


__all__ = [
    "AuditListView",
    "AttachmentDownloadView",
    "AuditCSVExportView",
    "AuditExcelExportView",
    "AuditPrintView",
    "OfflineChecklistView",
    "OfflineObjectInfoView",
]
