from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from checklists.models import ChecklistItem


@pytest.mark.django_db
def test_audit_list_shows_assigned_audit(auditor_client, audit_factory):
    audit = audit_factory()
    response = auditor_client.get(reverse("audits:audit-list"))
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert audit.elevator.identifier in body


@pytest.mark.django_db
def test_audit_detail_requires_permission(admin_client, audit_factory):
    audit = audit_factory()
    response = admin_client.get(reverse("audits:audit-detail", args=[audit.pk]))
    assert response.status_code == 200
    assert audit.template.name in response.content.decode("utf-8")


@pytest.mark.django_db
def test_auditor_can_save_draft(
    auditor_client,
    audit_factory,
    checklist_item_factory,
):
    audit = audit_factory()
    item_numeric = checklist_item_factory(template=audit.template, order=1)
    item_option = checklist_item_factory(
        template=audit.template,
        order=2,
        score_type=ChecklistItem.ScoreType.OPTION,
        options=["Да", "Нет"],
    )

    url = reverse("audits:audit-detail", args=[audit.pk])
    response = auditor_client.post(
        url,
        data={
            f"item-{item_numeric.pk}-numeric_answer": "4",
            f"item-{item_numeric.pk}-comment": "Выполнено",
            f"item-{item_option.pk}-selected_option": "",
            f"item-{item_option.pk}-comment": "",
            "action": "save_draft",
        },
    )

    assert response.status_code == 302
    audit.refresh_from_db()
    numeric_response = audit.responses.get(item=item_numeric)
    assert numeric_response.numeric_answer == Decimal("4")
    assert numeric_response.comment == "Выполнено"
    assert not audit.responses.filter(item=item_option).exists()


@pytest.mark.django_db
def test_auditor_cannot_submit_with_missing_answers(
    auditor_client,
    audit_factory,
    checklist_item_factory,
):
    audit = audit_factory()
    item_numeric = checklist_item_factory(template=audit.template, order=1)
    item_option = checklist_item_factory(
        template=audit.template,
        order=2,
        score_type=ChecklistItem.ScoreType.OPTION,
        options=["Да", "Нет"],
    )

    url = reverse("audits:audit-detail", args=[audit.pk])
    response = auditor_client.post(
        url,
        data={
            f"item-{item_numeric.pk}-numeric_answer": "",
            f"item-{item_numeric.pk}-comment": "",
            f"item-{item_option.pk}-selected_option": "",
            f"item-{item_option.pk}-comment": "",
            "action": "submit",
        },
    )

    assert response.status_code == 200
    assert "Заполните ответ, чтобы отправить аудит." in response.content.decode("utf-8")
    audit.refresh_from_db()
    assert audit.status == audit.Status.DRAFT


@pytest.mark.django_db
def test_auditor_can_submit_completed_audit(
    auditor_client,
    audit_factory,
    checklist_item_factory,
):
    audit = audit_factory()
    item_numeric = checklist_item_factory(template=audit.template, order=1)
    item_option = checklist_item_factory(
        template=audit.template,
        order=2,
        score_type=ChecklistItem.ScoreType.OPTION,
        options=["Соответствует", "Не соответствует"],
        requires_comment=True,
    )

    url = reverse("audits:audit-detail", args=[audit.pk])
    response = auditor_client.post(
        url,
        data={
            f"item-{item_numeric.pk}-numeric_answer": "5",
            f"item-{item_numeric.pk}-comment": "Замечаний нет",
            f"item-{item_option.pk}-selected_option": "Соответствует",
            f"item-{item_option.pk}-comment": "Фотографии приложены",
            "action": "submit",
        },
    )

    assert response.status_code == 302
    audit.refresh_from_db()
    assert audit.status == audit.Status.SUBMITTED
    assert audit.submitted_at is not None
    assert audit.responses.count() == 2


@pytest.mark.django_db
def test_admin_can_return_audit_to_draft_with_comment(
    admin_client,
    audit_factory,
    checklist_item_factory,
    audit_response_factory,
):
    audit = audit_factory()
    item = checklist_item_factory(template=audit.template, order=1)
    audit_response_factory(audit=audit, item=item, numeric_answer=4, comment="Заполнено")
    audit.mark_submitted()
    audit.refresh_from_db()

    url = reverse("audits:audit-detail", args=[audit.pk])
    response = admin_client.post(
        url,
        data={"action": "request_changes", "message": "Добавьте фотографии шахты"},
    )

    assert response.status_code == 302
    audit.refresh_from_db()
    assert audit.status == audit.Status.DRAFT
    assert audit.submitted_at is None
    assert audit.admin_comment == "Добавьте фотографии шахты"


@pytest.mark.django_db
def test_submitted_audit_is_read_only_for_auditor(
    auditor_client,
    audit_factory,
    checklist_item_factory,
    audit_response_factory,
):
    audit = audit_factory()
    item = checklist_item_factory(template=audit.template, order=1)
    audit_response_factory(audit=audit, item=item, numeric_answer=3, comment="Приложена запись")
    audit.mark_submitted()
    audit.refresh_from_db()

    url = reverse("audits:audit-detail", args=[audit.pk])
    response = auditor_client.get(url)

    content = response.content.decode("utf-8")
    assert "Аудит отправлен и доступен только для чтения" in content
    assert "name=\"action\" value=\"save_draft\"" not in content
