from __future__ import annotations

from django.contrib import admin

from . import models


@admin.register(models.Audit)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("id", "elevator", "status", "planned_date", "created_at", "created_by")
    list_filter = ("status", "planned_date")
    search_fields = ("elevator__identifier", "elevator__building__address")
    date_hierarchy = "created_at"


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
