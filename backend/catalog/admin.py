"""Customisations for the Django admin related to catalog objects."""
from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.db import models
from django.db.models import Count, Max
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _

from .models import (
    Building,
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    Elevator,
    ObjectInfoField,
    ScoreOption,
)


@admin.action(description="Утвердить выбранные записи")
def approve_records(modeladmin, request, queryset):
    for obj in queryset:
        obj.approve(request.user)


@admin.action(description="Отклонить выбранные записи")
def reject_records(modeladmin, request, queryset):
    for obj in queryset:
        obj.reject(request.user)


@admin.action(description="Вернуть на проверку")
def return_to_review(modeladmin, request, queryset):
    for obj in queryset:
        obj.send_to_review()


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    """Admin configuration for managing buildings."""

    list_display = ("address", "entrance", "review_status", "created_by", "verified_by", "created_at")
    list_filter = ("review_status", "verified_by", "created_by")
    search_fields = ("address", "entrance", "notes")
    readonly_fields = ("created_at", "verified_at")
    actions = (approve_records, reject_records, return_to_review)
    ordering = ("address", "entrance")

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Elevator)
class ElevatorAdmin(admin.ModelAdmin):
    """Admin configuration for managing elevators."""

    list_display = (
        "identifier",
        "building",
        "status",
        "review_status",
        "created_by",
        "verified_by",
        "created_at",
    )
    list_filter = ("review_status", "status", "building", "verified_by", "created_by")
    search_fields = ("identifier", "description", "building__address")
    readonly_fields = ("created_at", "verified_at")
    actions = (approve_records, reject_records, return_to_review)
    ordering = ("building__address", "identifier")
    autocomplete_fields = ("building",)

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class ChecklistSectionInline(admin.TabularInline):
    """Inline editor for sections inside a category."""

    model = ChecklistSection
    extra = 0
    fields = ("title", "order", "description")
    show_change_link = True
    ordering = ("order", "id")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 2})},
    }


class ChecklistQuestionInline(admin.TabularInline):
    """Inline editor for questions in a section."""

    model = ChecklistQuestion
    extra = 0
    fields = ("text", "type", "max_score", "order", "requires_comment")
    show_change_link = True
    ordering = ("order", "id")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }


class ScoreOptionInline(admin.TabularInline):
    """Inline editor for score options of a question."""

    model = ScoreOption
    extra = 1
    fields = ("score", "description")
    ordering = ("score", "id")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 2})},
    }


@admin.register(ChecklistCategory)
class ChecklistCategoryAdmin(admin.ModelAdmin):
    """Admin configuration for checklist categories."""

    list_display = ("name", "code", "order", "section_total")
    list_display_links = ("name",)
    list_editable = ("order",)
    search_fields = ("name", "code")
    ordering = ("order", "name")
    prepopulated_fields = {"code": ("name",)}
    inlines = (ChecklistSectionInline,)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.annotate(section_count=Count("sections", distinct=True))

    @admin.display(description=_("Секции"), ordering="section_count")
    def section_total(self, obj: ChecklistCategory) -> int:
        return obj.section_count


class SectionMoveActionForm(ActionForm):
    """Action form used to select a target category for moving sections."""

    target_category = forms.ModelChoiceField(
        queryset=ChecklistCategory.objects.all(),
        required=True,
        label=_("Целевая категория"),
        help_text=_("Категория, в которую будут перенесены выбранные секции."),
    )


@admin.register(ChecklistSection)
class ChecklistSectionAdmin(admin.ModelAdmin):
    """Admin configuration for checklist sections."""

    list_display = ("title", "category", "order", "question_total")
    list_display_links = ("title",)
    list_editable = ("order",)
    list_filter = ("category",)
    search_fields = ("title", "description")
    ordering = ("category__order", "order", "id")
    list_select_related = ("category",)
    inlines = (ChecklistQuestionInline,)
    actions = ("move_to_category",)
    action_form = SectionMoveActionForm

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.annotate(question_count=Count("questions", distinct=True))

    @admin.display(description=_("Вопросы"), ordering="question_count")
    def question_total(self, obj: ChecklistSection) -> int:
        return obj.question_count

    @admin.action(description=_("Перенести выбранные секции в категорию"))
    def move_to_category(self, request, queryset):
        target_category_id = request.POST.get("target_category")
        if not target_category_id:
            self.message_user(
                request,
                _("Не выбрана целевая категория для переноса секций."),
                level=messages.ERROR,
            )
            return

        try:
            target_category = ChecklistCategory.objects.get(pk=target_category_id)
        except ChecklistCategory.DoesNotExist:
            self.message_user(
                request,
                _("Выбранная категория не найдена."),
                level=messages.ERROR,
            )
            return

        current_max = target_category.sections.aggregate(max_order=Max("order"))[
            "max_order"
        ]
        next_order = current_max or 0
        moved = 0

        for section in queryset.order_by("order", "pk"):
            if section.category_id == target_category.pk:
                continue
            moved += 1
            next_order += 1
            section.category = target_category
            section.order = next_order
            section.save(update_fields=["category", "order"])

        if moved == 0:
            self.message_user(
                request,
                _(
                    "Выбранные секции уже находятся в категории «%(category)s»."
                )
                % {"category": target_category.name},
                level=messages.INFO,
            )
            return

        if moved == 1:
            message = _(
                "Перенесена %(count)d секция в категорию «%(category)s»."
            ) % {"count": moved, "category": target_category.name}
        else:
            message = _(
                "Перенесено %(count)d секций в категорию «%(category)s»."
            ) % {"count": moved, "category": target_category.name}
        self.message_user(request, message, level=messages.SUCCESS)


@admin.register(ChecklistQuestion)
class ChecklistQuestionAdmin(admin.ModelAdmin):
    """Admin configuration for checklist questions."""

    list_display = (
        "text_preview",
        "section",
        "category_name",
        "type",
        "max_score",
        "order",
        "requires_comment",
        "score_option_total",
    )
    list_display_links = ("text_preview",)
    list_editable = ("max_score", "order", "requires_comment")
    list_filter = ("type", "requires_comment", "section__category")
    search_fields = ("text", "guideline")
    ordering = (
        "section__category__order",
        "section__order",
        "order",
        "id",
    )
    autocomplete_fields = ("section",)
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }
    inlines = (ScoreOptionInline,)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("section", "section__category").annotate(
            score_option_count=Count("score_options", distinct=True)
        )

    @admin.display(description=_("Варианты баллов"), ordering="score_option_count")
    def score_option_total(self, obj: ChecklistQuestion) -> int:
        return obj.score_option_count

    @admin.display(description=_("Категория"), ordering="section__category__name")
    def category_name(self, obj: ChecklistQuestion) -> str:
        return obj.section.category.name

    @admin.display(description=_("Вопрос"))
    def text_preview(self, obj: ChecklistQuestion) -> str:
        return Truncator(obj.text).chars(80)


@admin.register(ObjectInfoField)
class ObjectInfoFieldAdmin(admin.ModelAdmin):
    """Admin configuration for configurable object information fields."""

    list_display = ("label", "code", "field_type", "is_required", "order")
    list_display_links = ("label",)
    list_editable = ("is_required", "order")
    list_filter = ("field_type", "is_required")
    search_fields = ("label", "code")
    ordering = ("order", "label")
    prepopulated_fields = {"code": ("label",)}
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 2})},
    }

