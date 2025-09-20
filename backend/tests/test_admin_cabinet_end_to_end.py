from __future__ import annotations

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from audits.models import Audit
from audits.services import build_checklist_structure
from catalog.models import Building, ChecklistCategory, ChecklistQuestion, Elevator, ReviewStatus

from .factories import AdminUserFactory, AuditorUserFactory

pytestmark = pytest.mark.django_db


def test_admin_configures_checklist_and_preview_updates() -> None:
    """Full flow of configuring checklist elements through the administrator cabinet."""

    admin = AdminUserFactory()
    auditor = AuditorUserFactory()
    admin.profile.mark_password_changed()
    auditor.profile.mark_password_changed()
    client = Client()

    overview_url = reverse("catalog:checklist-overview")

    response = client.get(overview_url)
    assert response.status_code == 302
    assert reverse("accounts:login") in response.headers.get("Location", "")

    client.force_login(auditor)
    forbidden = client.get(overview_url)
    assert forbidden.status_code == 403
    client.logout()

    client.force_login(admin)

    category_response = client.post(
        reverse("catalog:checklist-category-create"),
        data={"code": "safety", "name": "Безопасность", "order": 0},
    )
    assert category_response.status_code == 302
    category = ChecklistCategory.objects.get(code="safety")

    section_response = client.post(
        reverse("catalog:checklist-section-create", args=[category.pk]),
        data={
            "category": category.pk,
            "title": "Общие требования",
            "description": "Базовые проверки",
            "order": 0,
        },
    )
    assert section_response.status_code == 302
    section = category.sections.get(title="Общие требования")

    question_response = client.post(
        reverse("catalog:checklist-question-create", args=[section.pk]),
        data={
            "section": section.pk,
            "text": "Проверка механики",
            "type": ChecklistQuestion.QuestionType.SCORE,
            "max_score": 5,
            "guideline": "Убедитесь в отсутствии посторонних шумов",
            "requires_comment": "",
            "order": 0,
        },
    )
    assert question_response.status_code == 302
    question = section.questions.get(text="Проверка механики")

    option_response = client.post(
        reverse("catalog:checklist-option-create", args=[question.pk]),
        data={
            "question": question.pk,
            "score": 4,
            "description": "Небольшие замечания",
            "order": 0,
        },
    )
    assert option_response.status_code == 302

    overview = client.get(overview_url)
    assert overview.status_code == 200
    assert overview.context["category_count"] == 1
    assert overview.context["section_count"] == 1
    assert overview.context["question_count"] == 1

    preview = overview.context["checklist_preview"]
    assert preview["total_questions"] == 1
    categories = preview["categories"]
    assert len(categories) == 1
    section_data = categories[0]["sections"][0]
    assert section_data["title"] == "Общие требования"
    question_data = section_data["questions"][0]
    assert question_data["text"] == "Проверка механики"
    assert question_data["score_options"][0]["score"] == 4

    structure = build_checklist_structure()
    assert structure["total_questions"] == 1
    assert structure["categories"][0]["sections"][0]["questions"][0]["text"] == "Проверка механики"


def test_admin_moderates_audit_and_restricts_access() -> None:
    """Simulate moderator workflow for audits including role-based restrictions."""

    admin = AdminUserFactory()
    auditor = AuditorUserFactory()
    admin.profile.mark_password_changed()
    auditor.profile.mark_password_changed()
    client = Client()

    client.force_login(auditor)
    building_response = client.post(
        reverse("catalog:building-create"),
        data={
            "address": "Проспект Мира, 10",
            "entrance": "1",
            "notes": "Создано аудитором для проверки",
        },
    )
    assert building_response.status_code == 302
    building = Building.objects.get(address="Проспект Мира, 10")

    client.force_login(admin)
    approve_response = client.post(
        reverse("catalog:building-moderate", args=[building.pk]),
        data={"action": "approve", "next": reverse("catalog:building-list")},
    )
    assert approve_response.status_code == 302
    building.refresh_from_db()
    assert building.review_status == ReviewStatus.APPROVED
    assert building.verified_by == admin

    client.force_login(auditor)
    elevator_response = client.post(
        reverse("catalog:elevator-create"),
        data={
            "building": building.pk,
            "identifier": "EL-900",
            "status": Elevator.Status.IN_SERVICE,
            "description": "Испытательный лифт",
        },
    )
    assert elevator_response.status_code == 302
    elevator = Elevator.objects.get(identifier="EL-900")

    audit = Audit.objects.create(elevator=elevator, created_by=auditor)
    audit.start(actor=auditor)
    audit.submit(actor=auditor)
    mail.outbox.clear()

    client.force_login(admin)
    list_response = client.get(reverse("audits:audit-list"), {"review": "pending"})
    assert list_response.status_code == 200
    page = list_response.context["page_obj"]
    assert any(item.pk == audit.pk for item in page.object_list)
    assert any(
        item["value"] == "pending" and item["selected"]
        for item in list_response.context["review_filters"]
    )

    mark_response = client.post(
        reverse("audits:audit-mark-reviewed", args=[audit.pk]),
        data={"next": reverse("audits:audit-list")},
    )
    assert mark_response.status_code == 302
    audit.refresh_from_db()
    assert audit.status == Audit.Status.REVIEWED
    assert len(mail.outbox) == 1
    assert auditor.email in mail.outbox[0].recipients()

    reviewed_response = client.get(reverse("audits:audit-list"), {"review": "reviewed"})
    assert reviewed_response.status_code == 200
    reviewed_page = reviewed_response.context["page_obj"]
    assert any(item.pk == audit.pk for item in reviewed_page.object_list)

    client.force_login(auditor)
    auditor_list = client.get(reverse("audits:audit-list"), {"review": "reviewed"})
    assert auditor_list.status_code == 200
    assert auditor_list.context["review_filters"] == []
    auditor_page = auditor_list.context["page_obj"]
    assert any(item.pk == audit.pk for item in auditor_page.object_list)

    detail_response = client.get(reverse("audits:audit-detail", args=[audit.pk]))
    assert detail_response.status_code == 403
