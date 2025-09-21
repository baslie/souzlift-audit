"""URL routes for checklist templates."""
from __future__ import annotations

from django.urls import path

from .views import ChecklistTemplateDetailView, ChecklistTemplateListView

app_name = "checklists"

urlpatterns = [
    path("", ChecklistTemplateListView.as_view(), name="template-list"),
    path("<int:pk>/", ChecklistTemplateDetailView.as_view(), name="template-detail"),
]
