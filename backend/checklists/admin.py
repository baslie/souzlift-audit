from django.contrib import admin

from .models import ChecklistItem, ChecklistTemplate


class ChecklistItemInline(admin.TabularInline):
    model = ChecklistItem
    extra = 0
    fields = (
        "order",
        "area",
        "category",
        "question",
        "score_type",
        "min_score",
        "max_score",
        "step",
        "requires_comment",
        "weight",
    )
    ordering = ("order", "id")


@admin.register(ChecklistTemplate)
class ChecklistTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "published_at", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    inlines = [ChecklistItemInline]


@admin.register(ChecklistItem)
class ChecklistItemAdmin(admin.ModelAdmin):
    list_display = (
        "template",
        "order",
        "area",
        "category",
        "score_type",
        "requires_comment",
        "weight",
    )
    list_filter = ("template", "score_type", "requires_comment")
    search_fields = ("question", "area", "category")
    ordering = ("template", "order", "id")
