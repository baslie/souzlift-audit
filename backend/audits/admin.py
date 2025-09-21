"""Admin configuration for simplified audit models."""
from __future__ import annotations

from django.contrib import admin

from .models import Audit, AuditAttachment, AuditResponse


class AuditResponseInline(admin.TabularInline):
    model = AuditResponse
    extra = 0
    fields = (
        "item",
        "numeric_answer",
        "selected_option",
        "comment",
        "updated_at",
    )
    readonly_fields = ("updated_at", "created_at")
    ordering = ("item__order", "item_id")


class AuditAttachmentInline(admin.TabularInline):
    model = AuditAttachment
    extra = 0
    fields = ("file", "caption", "response", "uploaded_by", "uploaded_at")
    readonly_fields = ("uploaded_at",)


@admin.register(Audit)
class AuditAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "building",
        "elevator",
        "template",
        "status",
        "assigned_to",
        "deadline",
        "score",
        "updated_at",
    )
    list_filter = ("status", "template", "building")
    search_fields = (
        "elevator__identifier",
        "building__address",
        "assigned_to__username",
    )
    readonly_fields = ("created_at", "updated_at", "submitted_at", "score")
    inlines = [AuditResponseInline, AuditAttachmentInline]
    ordering = ("-created_at", "-id")


@admin.register(AuditResponse)
class AuditResponseAdmin(admin.ModelAdmin):
    list_display = (
        "audit",
        "item",
        "numeric_answer",
        "selected_option",
        "updated_at",
    )
    list_filter = ("item__template",)
    search_fields = ("comment", "item__question")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("audit", "item__order", "item_id")


@admin.register(AuditAttachment)
class AuditAttachmentAdmin(admin.ModelAdmin):
    list_display = ("audit", "response", "uploaded_by", "uploaded_at")
    search_fields = ("caption", "file")
    list_filter = ("uploaded_at",)
    readonly_fields = ("uploaded_at",)
