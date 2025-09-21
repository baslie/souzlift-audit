"""Simplified views for listing and inspecting audits."""
from __future__ import annotations

from typing import Any, Iterable

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import HttpRequest
from django.views.generic import DetailView, ListView

from checklists.models import ChecklistItem

from .models import Audit, AuditResponse


class AuditListView(LoginRequiredMixin, ListView):
    model = Audit
    template_name = "audits/audit_list.html"
    context_object_name = "audits"
    paginate_by = 25

    def get_queryset(self):  # type: ignore[override]
        queryset = (
            super()
            .get_queryset()
            .select_related("building", "elevator", "template", "assigned_to")
            .prefetch_related(
                Prefetch(
                    "responses",
                    queryset=AuditResponse.objects.select_related("item").order_by(
                        "item__order", "item_id"
                    ),
                )
            )
            .order_by("status", "deadline", "-updated_at")
        )
        user = self.request.user
        profile = getattr(user, "profile", None)
        if profile is not None and getattr(profile, "is_admin", False):
            return queryset
        if user.is_staff or user.is_superuser:
            return queryset
        return queryset.filter(assigned_to=user)


class AuditDetailView(LoginRequiredMixin, DetailView):
    model = Audit
    template_name = "audits/audit_detail.html"
    context_object_name = "audit"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        context = super().get_context_data(**kwargs)
        audit: Audit = context["audit"]
        responses = (
            audit.responses.select_related("item")
            .all()
            .order_by("item__order", "item_id")
        )
        context.update(
            {
                "responses": responses,
                "items_without_response": self._missing_items(audit, responses),
            }
        )
        return context

    def _missing_items(
        self,
        audit: Audit,
        responses: Iterable[AuditResponse],
    ) -> list[ChecklistItem]:
        answered_ids = {response.item_id for response in responses}
        return list(
            audit.template.items.exclude(pk__in=answered_ids)
            .order_by("order", "id")
            .all()
        )

    def has_permission(self, request: HttpRequest, audit: Audit) -> bool:
        user = request.user
        profile = getattr(user, "profile", None)
        if profile is not None and getattr(profile, "is_admin", False):
            return True
        if user.is_staff or user.is_superuser:
            return True
        return audit.assigned_to_id == user.id

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any):  # type: ignore[override]
        audit = self.get_object()
        if not self.has_permission(request, audit):
            raise PermissionDenied("Недостаточно прав для просмотра аудита")
        return super().dispatch(request, *args, **kwargs)
