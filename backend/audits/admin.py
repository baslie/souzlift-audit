from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from typing import Any

from django.contrib import admin
from django.db.models import Avg, Count, Prefetch, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import models
from .services import build_checklist_structure
from catalog.models import ChecklistQuestion, ObjectInfoField


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
        object_info_items = self._prepare_object_info_items(audit)
        checklist_structure = build_checklist_structure()
        checklist_context, summary = self._prepare_checklist_context(
            audit, checklist_structure
        )

        allowed_fields = [
            {
                "name": name,
                "label": str(self.model._meta.get_field(name).verbose_name),
            }
            for name in ("elevator", "planned_date", "started_at", "finished_at", "status")
        ]

        summary["unanswered_questions"] = (
            summary["total_questions"] - summary["answered_questions"]
        )

        return {
            "audit_object_info": object_info_items,
            "audit_object_info_has_values": any(
                not item["is_empty"] for item in object_info_items
            ),
            "audit_object_info_has_extra": any(item["is_extra"] for item in object_info_items),
            "audit_checklist": checklist_context,
            "audit_summary": summary,
            "audit_allowed_fields": allowed_fields,
            "audit_responses_present": summary["answered_questions"] > 0,
        }

    def _prepare_object_info_items(self, audit: models.Audit) -> list[dict[str, Any]]:
        stored_info = audit.object_info or {}
        items: list[dict[str, Any]] = []
        known_codes: set[str] = set()

        fields = ObjectInfoField.objects.all().order_by("order", "label")
        for field in fields:
            raw_value = stored_info.get(field.code)
            value = self._format_object_info_value(field.field_type, raw_value)
            items.append(
                {
                    "code": field.code,
                    "label": field.label,
                    "value": value,
                    "raw_value": raw_value,
                    "field_type": field.field_type,
                    "is_empty": value == "",
                    "is_extra": False,
                    "is_multiline": "\n" in value if isinstance(value, str) else False,
                }
            )
            known_codes.add(field.code)

        for code, raw_value in stored_info.items():
            if code in known_codes:
                continue
            value = self._format_object_info_value(None, raw_value)
            items.append(
                {
                    "code": code,
                    "label": code,
                    "value": value,
                    "raw_value": raw_value,
                    "field_type": None,
                    "is_empty": value == "",
                    "is_extra": True,
                    "is_multiline": "\n" in value if isinstance(value, str) else False,
                }
            )

        return items

    def _prepare_checklist_context(
        self,
        audit: models.Audit,
        checklist_structure: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        responses = list(audit.responses.all())
        response_map = {response.question_id: response for response in responses}

        summary = {
            "total_questions": 0,
            "answered_questions": 0,
            "attachments_total": 0,
            "comments_total": 0,
            "flagged_total": 0,
        }

        checklist_context: list[dict[str, Any]] = []
        for category in checklist_structure.get("categories", []):
            section_context: list[dict[str, Any]] = []
            for section in category.get("sections", []):
                questions_context: list[dict[str, Any]] = []
                for question in section.get("questions", []):
                    summary["total_questions"] += 1
                    response = response_map.get(question["id"])
                    attachments = list(response.attachments.all()) if response else []
                    if response:
                        summary["answered_questions"] += 1
                        summary["attachments_total"] += len(attachments)
                        if self._has_comment(response, question["type"]):
                            summary["comments_total"] += 1
                        if response.is_flagged:
                            summary["flagged_total"] += 1
                    question_entry = self._build_question_entry(
                        question, response, attachments
                    )
                    questions_context.append(question_entry)
                section_context.append(
                    {
                        "id": section.get("id"),
                        "title": section.get("title"),
                        "description": section.get("description"),
                        "questions": questions_context,
                    }
                )
            checklist_context.append(
                {
                    "id": category.get("id"),
                    "name": category.get("name"),
                    "code": category.get("code"),
                    "sections": section_context,
                }
            )

        return checklist_context, summary

    def _build_question_entry(
        self,
        question: dict[str, Any],
        response: models.AuditResponse | None,
        attachments: list[models.AuditAttachment],
    ) -> dict[str, Any]:
        question_type = question.get("type")
        answer_display = ""
        comment_display = ""
        value_display = ""
        has_comment = False

        if response is not None:
            comment_text = (response.comment or "").strip()
            if question_type == ChecklistQuestion.QuestionType.TEXT:
                answer_display = comment_text
                value_display = comment_text or ""
                has_comment = bool(comment_text)
            elif question_type == ChecklistQuestion.QuestionType.BOOLEAN:
                if response.score is not None:
                    answer_display = _("Да") if self._coerce_boolean(response.score) else _("Нет")
                    value_display = answer_display
                has_comment = bool(comment_text)
                comment_display = comment_text
            else:
                if response.score is not None:
                    max_score = question.get("max_score") or 0
                    if max_score:
                        value_display = _("%(score)d из %(max)d") % {
                            "score": int(response.score),
                            "max": int(max_score),
                        }
                    else:
                        value_display = str(response.score)
                has_comment = bool(comment_text)
                comment_display = comment_text

        if not value_display:
            value_display = "—"

        return {
            "id": question.get("id"),
            "text": question.get("text"),
            "type": question_type,
            "max_score": question.get("max_score"),
            "guideline": question.get("guideline"),
            "requires_comment": question.get("requires_comment"),
            "response": response,
            "attachments": attachments,
            "value_display": value_display,
            "answer_display": answer_display,
            "comment_display": comment_display,
            "has_response": response is not None,
            "has_comment": has_comment,
            "is_flagged": bool(getattr(response, "is_flagged", False)),
            "is_offline": bool(getattr(response, "is_offline_cached", False)),
        }

    def _format_object_info_value(self, field_type: str | None, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            if not value.strip():
                return ""
            text_value = value.strip()
        else:
            text_value = value

        if field_type == ObjectInfoField.FieldType.BOOLEAN:
            return str(_("Да") if self._coerce_boolean(text_value) else _("Нет"))

        if isinstance(text_value, (list, tuple)):
            cleaned = [str(item).strip() for item in text_value if str(item).strip()]
            return ", ".join(cleaned)

        if isinstance(text_value, dict):
            return json.dumps(text_value, ensure_ascii=False, sort_keys=True, indent=2)

        if isinstance(text_value, (date, datetime)):
            return text_value.isoformat()

        return str(text_value)

    def _has_comment(self, response: models.AuditResponse, question_type: str | None) -> bool:
        del question_type
        return bool((response.comment or "").strip())

    def _coerce_boolean(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "да"}
        return bool(value)


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
