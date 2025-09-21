"""Simplified views for listing and inspecting audits."""
from __future__ import annotations

from typing import Any, List

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import HttpRequest
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView

from checklists.models import ChecklistItem

from .forms import AuditItemForm, AuditRequestChangesForm
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

    def get_queryset(self):  # type: ignore[override]
        return (
            super()
            .get_queryset()
            .select_related("building", "elevator", "template", "assigned_to")
            .prefetch_related(
                Prefetch(
                    "responses",
                    queryset=AuditResponse.objects.select_related("item").order_by(
                        "item__order",
                        "item_id",
                    ),
                ),
                Prefetch(
                    "template__items",
                    queryset=ChecklistItem.objects.order_by("order", "id"),
                ),
            )
        )

    def can_edit(self, user: object, audit: Audit) -> bool:
        if not audit.is_editable:
            return False
        assigned_to_id = audit.assigned_to_id
        if assigned_to_id is None:
            profile = getattr(user, "profile", None)
            return bool(profile and getattr(profile, "is_auditor", False))
        return assigned_to_id == getattr(user, "id", None)

    def can_request_changes(self, user: object, audit: Audit) -> bool:
        profile = getattr(user, "profile", None)
        if profile is not None and getattr(profile, "is_admin", False):
            return True
        return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))

    def build_response_forms(
        self,
        audit: Audit,
        *,
        data: dict[str, Any] | None = None,
        read_only: bool | None = None,
    ) -> List[AuditItemForm]:
        if read_only is None:
            read_only = not self.can_edit(self.request.user, audit)
        responses_map = {response.item_id: response for response in audit.responses.all()}
        forms: List[AuditItemForm] = []
        items = audit.template.items.all().order_by("order", "id")
        for item in items:
            instance = responses_map.get(item.id)
            form = AuditItemForm(
                data=data,
                audit=audit,
                item=item,
                instance=instance,
                read_only=read_only,
                prefix=f"item-{item.pk}",
            )
            forms.append(form)
        return forms

    def build_request_changes_form(
        self,
        audit: Audit,
        *,
        data: dict[str, Any] | None = None,
    ) -> AuditRequestChangesForm:
        if data is not None:
            return AuditRequestChangesForm(data)
        initial = {}
        if audit.admin_comment:
            initial["message"] = audit.admin_comment
        return AuditRequestChangesForm(initial=initial)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        context = super().get_context_data(**kwargs)
        audit: Audit = context["audit"]
        response_forms: List[AuditItemForm] = kwargs.get("response_forms")  # type: ignore[assignment]
        if response_forms is None:
            response_forms = self.build_response_forms(audit)
        can_edit = self.can_edit(self.request.user, audit)
        can_request_changes = self.can_request_changes(self.request.user, audit) and (
            audit.status == Audit.Status.SUBMITTED
        )
        context.update(
            {
                "response_forms": response_forms,
                "can_edit": can_edit,
                "can_submit": can_edit,
                "is_read_only": not can_edit,
                "show_read_only_alert": (not can_edit) and (
                    audit.status == Audit.Status.SUBMITTED
                ),
                "completed_count": sum(1 for form in response_forms if form.has_answer()),
                "total_items": len(response_forms),
                "can_request_changes": can_request_changes,
            }
        )
        if can_request_changes:
            context["request_changes_form"] = kwargs.get("request_changes_form") or self.build_request_changes_form(
                audit
            )
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any):  # type: ignore[override]
        audit = getattr(self, "object", None)
        if audit is None or not isinstance(audit, Audit):
            audit = self.get_object()
            self.object = audit
        action = request.POST.get("action", "").strip()

        if action in {"save_draft", "submit"}:
            if not self.can_edit(request.user, audit):
                raise PermissionDenied("Недостаточно прав для изменения аудита")
            response_forms = self.build_response_forms(
                audit,
                data=request.POST,
                read_only=False,
            )
            forms_valid = all(form.is_valid() for form in response_forms)
            if not forms_valid:
                return self.render_to_response(
                    self.get_context_data(response_forms=response_forms)
                )

            if action == "submit":
                missing_forms = [form for form in response_forms if not form.has_answer()]
                if missing_forms:
                    error_message = _("Заполните ответ, чтобы отправить аудит.")
                    for form in missing_forms:
                        field_name = (
                            "numeric_answer"
                            if form.item.score_type == form.item.ScoreType.NUMERIC
                            else "selected_option"
                        )
                        form.add_error(field_name, error_message)
                    return self.render_to_response(
                        self.get_context_data(response_forms=response_forms)
                    )

            for form in response_forms:
                form.save()

            if action == "submit":
                audit.mark_submitted()
                messages.success(request, _("Аудит отправлен на проверку."))
            else:
                messages.success(request, _("Черновик сохранён."))
            return redirect("audits:audit-detail", pk=audit.pk)

        if action == "request_changes":
            if audit.status != Audit.Status.SUBMITTED or not self.can_request_changes(request.user, audit):
                raise PermissionDenied("Недостаточно прав для возврата аудита")
            request_form = self.build_request_changes_form(
                audit,
                data=request.POST,
            )
            if request_form.is_valid():
                audit.request_changes(comment=request_form.cleaned_data["message"])
                messages.success(request, _("Аудит возвращён в черновик."))
                return redirect("audits:audit-detail", pk=audit.pk)
            response_forms = self.build_response_forms(audit)
            return self.render_to_response(
                self.get_context_data(
                    response_forms=response_forms,
                    request_changes_form=request_form,
                )
            )

        return self.get(request, *args, **kwargs)

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
        self.object = audit
        return super().dispatch(request, *args, **kwargs)
