"""URL patterns for the audits application."""
from __future__ import annotations

from django.urls import path

from .views import AttachmentDownloadView

app_name = "audits"

urlpatterns = [
    path("attachments/<str:token>/download/", AttachmentDownloadView.as_view(), name="attachment-download"),
]
