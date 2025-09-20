"""URL patterns for the audits application."""
from __future__ import annotations

from django.urls import path

from .views import (
    AttachmentDownloadView,
    AuditCSVExportView,
    AuditDetailView,
    AuditExcelExportView,
    AuditListView,
    AuditMarkReviewedView,
    AuditPrintView,
    OfflineChecklistView,
    OfflineObjectInfoView,
)

app_name = "audits"

urlpatterns = [
    path("", AuditListView.as_view(), name="audit-list"),
    path(
        "offline/object-info/",
        OfflineObjectInfoView.as_view(),
        name="offline-object-info",
    ),
    path(
        "offline/checklist/",
        OfflineChecklistView.as_view(),
        name="offline-checklist",
    ),
    path("<int:pk>/", AuditDetailView.as_view(), name="audit-detail"),
    path(
        "<int:pk>/review/",
        AuditMarkReviewedView.as_view(),
        name="audit-mark-reviewed",
    ),
    path(
        "<int:pk>/export/print/",
        AuditPrintView.as_view(),
        name="audit-export-print",
    ),
    path(
        "<int:pk>/export/csv/",
        AuditCSVExportView.as_view(),
        name="audit-export-csv",
    ),
    path(
        "<int:pk>/export/excel/",
        AuditExcelExportView.as_view(),
        name="audit-export-excel",
    ),
    path("attachments/<str:token>/download/", AttachmentDownloadView.as_view(), name="attachment-download"),
]
