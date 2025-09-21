"""URL configuration for the simplified audits module."""
from __future__ import annotations

from django.urls import path

from .views import AuditDetailView, AuditListView

app_name = "audits"

urlpatterns = [
    path("", AuditListView.as_view(), name="audit-list"),
    path("<int:pk>/", AuditDetailView.as_view(), name="audit-detail"),
]
