"""Admin configuration for catalog models."""
from __future__ import annotations

from django.contrib import admin

from config.admin import SuperuserOnlyAdminMixin

from .models import Building, Elevator


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
class BuildingAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("address", "entrance", "review_status", "created_by", "verified_by", "created_at")
    list_filter = ("review_status", "verified_by", "created_by")
    search_fields = ("address", "entrance", "notes")
    readonly_fields = ("created_at", "verified_at")
    actions = (approve_records, reject_records, return_to_review)
    ordering = ("address", "entrance")

    def save_model(self, request, obj, form, change):  # type: ignore[override]
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Elevator)
class ElevatorAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
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

    def save_model(self, request, obj, form, change):  # type: ignore[override]
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
