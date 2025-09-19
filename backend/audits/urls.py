"""URL patterns for the audits application."""
from __future__ import annotations

from django.urls import path

from .views import AttachmentDownloadView, AuditListView, OfflineObjectInfoView

app_name = "audits"

urlpatterns = [
    path("", AuditListView.as_view(), name="audit-list"),
    path(
        "offline/object-info/",
        OfflineObjectInfoView.as_view(),
        name="offline-object-info",
    ),
    path("attachments/<str:token>/download/", AttachmentDownloadView.as_view(), name="attachment-download"),
]
