from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib import admin
from django.db.models import Avg, Count, Prefetch, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from config.admin import SuperuserOnlyAdminMixin

from . import models
from .reporting import build_audit_report
from .services import build_checklist_structure


class AuditReviewStateFilter(admin.SimpleListFilter):
    """Provide quick filters for review status in the admin change list."""

    title = _("Статус просмотра")
    parameter_name = "review_state"

    def lookups(self, request, model_admin):
        return (
            ("pending", _("Ожидают просмотра")),
            ("reviewed", _("Просмотренные")),
            ("active", _("В работе")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "pending":
            return queryset.filter(status=models.Audit.Status.SUBMITTED)
        if value == "reviewed":
            return queryset.filter(status=models.Audit.Status.REVIEWED)
        if value == "active":
            return queryset.filter(
                status__in=(
                    models.Audit.Status.DRAFT,
                    models.Audit.Status.IN_PROGRESS,
                )
            )
        return queryset


class AuditDueFilter(admin.SimpleListFilter):
    """Expose quick filters for planned dates of audits."""

    title = _("Сроки")
    parameter_name = "due"

    def lookups(self, request, model_admin):
        return (
            ("overdue", _("Просроченные")),
            ("today", _("На сегодня")),
            ("week", _("На этой неделе")),
            ("without_plan", _("Без плановой даты")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        today = timezone.localdate()

        if value == "overdue":
            return queryset.filter(planned_date__lt=today).exclude(
                status=models.Audit.Status.REVIEWED
            )
        if value == "today":
            return queryset.filter(planned_date=today)
        if value == "week":
            end_of_week = today + timedelta(days=6 - today.weekday())
            return queryset.filter(planned_date__range=(today, end_of_week))
        if value == "without_plan":
            return queryset.filter(planned_date__isnull=True)
        return queryset


@admin.register(models.Audit)
class AuditAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/audits/audit/change_list.html"
    change_form_template = "admin/audits/audit/change_form.html"
    list_display = (
        "id",
        "elevator",
        "status_display",
        "is_reviewed_indicator",
        "planned_date",
        "created_at",
        "created_by",
        "total_score",
    )
    list_filter = (
        AuditReviewStateFilter,
        AuditDueFilter,
        "status",
        "created_by",
    )
    search_fields = (
        "elevator__identifier",
        "elevator__building__address",
        "created_by__username",
    )
    date_hierarchy = "created_at"
    list_select_related = ("elevator", "elevator__building", "created_by")
    ordering = ("-created_at", "-id")
    readonly_fields = ("created_by", "created_at", "updated_at", "total_score")
    exclude = ("object_info",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "elevator",
                    "status",
                    "planned_date",
                    "started_at",
                    "finished_at",
                )
            },
        ),
        (
            _("Служебные поля"),
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                    "total_score",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description=_("Статус"), ordering="status")
    def status_display(self, obj: models.Audit) -> str:
        return obj.get_status_display()

    @admin.display(description=_("Просмотрен"), boolean=True, ordering="status")
    def is_reviewed_indicator(self, obj: models.Audit) -> bool:
        return obj.status == models.Audit.Status.REVIEWED

    def get_row_css(self, obj, index):  # type: ignore[override]
        if obj.status == models.Audit.Status.SUBMITTED:
            return "row-status-submitted"
        if obj.status == models.Audit.Status.REVIEWED:
            return "row-status-reviewed"
        return ""

    def get_queryset(self, request):  # type: ignore[override]
        queryset = super().get_queryset(request)
        response_qs = (
            models.AuditResponse.objects.select_related(
                "question",
                "question__section",
                "question__section__category",
            )
            .prefetch_related(
                Prefetch(
                    "attachments",
                    queryset=models.AuditAttachment.objects.order_by("uploaded_at"),
                )
            )
            .order_by(
                "question__section__category__order",
                "question__section__order",
                "question__order",
                "question_id",
            )
        )
        return queryset.select_related(
            "elevator",
            "elevator__building",
            "created_by",
        ).prefetch_related(Prefetch("responses", queryset=response_qs))

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)

        try:
            context = response.context_data
        except AttributeError:
            return response

        changelist = context.get("cl")
        if changelist is None:
            return response

        queryset = changelist.queryset
        overall_queryset = self.get_queryset(request)

        filtered_summary = self._build_dashboard_summary(queryset)
        overall_summary = self._build_dashboard_summary(overall_queryset)
        status_breakdown = [
            {
                "value": choice.value,
                "label": choice.label,
                "filtered": filtered_summary.get(choice.value, 0),
                "overall": overall_summary.get(choice.value, 0),
            }
            for choice in models.Audit.Status
        ]

        dashboard = {
            "filtered_summary": filtered_summary,
            "overall_summary": overall_summary,
            "recent_audits": list(self._get_recent_audits(queryset)),
            "status_breakdown": status_breakdown,
        }

        context.setdefault("audit_dashboard", dashboard)
        return response

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        if object_id:
            audit = self.get_object(request, object_id)
            if audit is not None:
                extra_context.update(self._build_changeform_context(audit))
        return super().changeform_view(
            request,
            object_id,
            form_url,
            extra_context=extra_context,
        )

    def _build_dashboard_summary(self, queryset):
        today = timezone.localdate()
        return queryset.aggregate(
            total=Count("id"),
            draft=Count("id", filter=Q(status=models.Audit.Status.DRAFT)),
            in_progress=Count(
                "id", filter=Q(status=models.Audit.Status.IN_PROGRESS)
            ),
            submitted=Count("id", filter=Q(status=models.Audit.Status.SUBMITTED)),
            reviewed=Count("id", filter=Q(status=models.Audit.Status.REVIEWED)),
            overdue=Count(
                "id",
                filter=Q(planned_date__lt=today)
                & ~Q(status=models.Audit.Status.REVIEWED),
            ),
            avg_score=Avg("total_score"),
        )

    def _get_recent_audits(self, queryset):
        return (
            queryset.select_related("elevator", "elevator__building", "created_by")
            .order_by("-created_at")
            [:5]
        )

    # --- change form helpers -------------------------------------------------

    def _build_changeform_context(self, audit: models.Audit) -> dict[str, Any]:
        checklist_structure = build_checklist_structure()
        report = build_audit_report(audit, checklist_structure=checklist_structure)
        summary = report["summary"]

        allowed_fields = [
            {
                "name": name,
                "label": str(self.model._meta.get_field(name).verbose_name),
            }
            for name in ("elevator", "planned_date", "started_at", "finished_at", "status")
        ]

        return {
            "audit_object_info": report["object_info"],
            "audit_object_info_has_values": report["object_info_has_values"],
            "audit_object_info_has_extra": report["object_info_has_extra"],
            "audit_checklist": report["checklist"],
            "audit_summary": summary,
            "audit_allowed_fields": allowed_fields,
            "audit_responses_present": summary["answered_questions"] > 0,
        }


@admin.register(models.AuditResponse)
class AuditResponseAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("id", "audit", "question", "score", "is_flagged")
    list_filter = ("is_flagged",)
    search_fields = ("audit__elevator__identifier", "question__text")


@admin.register(models.AuditAttachment)
class AuditAttachmentAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("id", "response", "stored_size", "uploaded_at")
    search_fields = ("response__audit__elevator__identifier",)
    readonly_fields = ("stored_size", "uploaded_at")


@admin.register(models.AuditSignature)
class AuditSignatureAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("audit", "signed_by", "signed_at")
    search_fields = ("audit__elevator__identifier", "signed_by")
    readonly_fields = ("signed_at",)


@admin.register(models.AuditLogEntry)
class AuditLogEntryAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "action", "entity_type", "entity_id", "user")
    list_filter = ("action", "entity_type")
    search_fields = ("entity_type", "entity_id", "payload")
    readonly_fields = ("created_at", "payload")
    date_hierarchy = "created_at"
    autocomplete_fields = ("user",)
