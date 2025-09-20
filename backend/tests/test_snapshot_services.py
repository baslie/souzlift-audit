from __future__ import annotations

import pytest
from django.urls import reverse

from audits.services import build_audit_filter_snapshot, build_checklist_structure

from .factories import (
    AdminUserFactory,
    AuditorUserFactory,
    ChecklistQuestionFactory,
)
from accounts.permissions import is_admin


@pytest.mark.django_db
def test_checklist_structure_exposes_path_metadata(client) -> None:
    """Checklist snapshot should expose category and section references."""

    question = ChecklistQuestionFactory()

    structure = build_checklist_structure()
    assert structure["categories"]

    category = structure["categories"][0]
    section = category["sections"][0]
    question_data = section["questions"][0]

    assert question_data["category_id"] == question.section.category_id
    assert question_data["category_code"] == question.section.category.code
    assert question_data["category_name"] == question.section.category.name
    assert question_data["section_id"] == question.section_id
    assert question_data["section_title"] == question.section.title


@pytest.mark.django_db
def test_audit_filter_snapshot_respects_user_role() -> None:
    """Administrators should receive review filters, auditors should not."""

    admin_user = AdminUserFactory()
    auditor_user = AuditorUserFactory()

    admin_filters = build_audit_filter_snapshot(admin_user)
    assert "status" in admin_filters
    assert "period" in admin_filters
    assert "review" in admin_filters
    assert any(option["value"] == "pending" for option in admin_filters["review"])

    auditor_filters = build_audit_filter_snapshot(auditor_user)
    assert "status" in auditor_filters
    assert "period" in auditor_filters
    assert "review" not in auditor_filters


@pytest.mark.django_db
def test_catalog_snapshot_endpoint_includes_checklist_and_filters(client) -> None:
    """API snapshot should expose checklist data and filter metadata."""

    admin = AdminUserFactory()
    admin.profile.mark_password_changed()
    assert admin.profile.role == admin.profile.Roles.ADMIN
    assert is_admin(admin)
    ChecklistQuestionFactory()
    assert client.login(username=admin.username, password="Password123!")

    response = client.get(reverse("catalog-snapshot"))
    if response.status_code != 200:
        request_user = response.wsgi_request.user
        details = {
            "is_authenticated": getattr(request_user, "is_authenticated", False),
            "role": getattr(getattr(request_user, "profile", None), "role", None),
        }
        pytest.fail(
            f"Unexpected response {response.status_code}: {response.json()} with user details {details}"
        )
    payload = response.json()

    assert "checklist" in payload
    assert payload["checklist"]["categories"]
    assert "audit_filters" in payload
    assert any(option["value"] == "pending" for option in payload["audit_filters"]["review"])
