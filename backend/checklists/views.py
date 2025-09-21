"""Views for managing checklist templates and items."""
from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView, ListView

from .models import ChecklistTemplate


class ChecklistTemplateListView(LoginRequiredMixin, ListView):
    model = ChecklistTemplate
    template_name = "checklists/template_list.html"
    context_object_name = "templates"
    paginate_by = 25
    ordering = ["-published_at", "name"]


class ChecklistTemplateDetailView(LoginRequiredMixin, DetailView):
    model = ChecklistTemplate
    template_name = "checklists/template_detail.html"
    context_object_name = "template"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        context = super().get_context_data(**kwargs)
        context["items"] = self.object.items.order_by("order", "id")
        return context


__all__ = [
    "ChecklistTemplateListView",
    "ChecklistTemplateDetailView",
]
