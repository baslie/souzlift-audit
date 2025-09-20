from __future__ import annotations

from datetime import timedelta

from django.contrib import admin
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import models


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
class AuditAdmin(admin.ModelAdmin):
    change_list_template = "admin/audits/audit/change_list.html"
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


@admin.register(models.AuditResponse)
class AuditResponseAdmin(admin.ModelAdmin):
    list_display = ("id", "audit", "question", "score", "is_flagged")
    list_filter = ("is_flagged",)
    search_fields = ("audit__elevator__identifier", "question__text")


@admin.register(models.AuditAttachment)
class AuditAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "response", "stored_size", "uploaded_at")
    search_fields = ("response__audit__elevator__identifier",)
    readonly_fields = ("stored_size", "uploaded_at")


@admin.register(models.AuditSignature)
class AuditSignatureAdmin(admin.ModelAdmin):
    list_display = ("audit", "signed_by", "signed_at")
    search_fields = ("audit__elevator__identifier", "signed_by")
    readonly_fields = ("signed_at",)


@admin.register(models.AuditLogEntry)
class AuditLogEntryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "entity_type", "entity_id", "user")
    list_filter = ("action", "entity_type")
    search_fields = ("entity_type", "entity_id", "payload")
    readonly_fields = ("created_at", "payload")
    date_hierarchy = "created_at"
    autocomplete_fields = ("user",)
