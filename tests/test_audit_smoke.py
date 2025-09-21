from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from audits.models import Audit
from checklists.models import ChecklistItem


@pytest.mark.django_db
def test_smoke_audit_assignment_fill_submit(
    admin_client,
    auditor_client,
    admin_user,
    auditor_user,
    building_factory,
    elevator_factory,
    checklist_template_factory,
    checklist_item_factory,
):
    template = checklist_template_factory()
    item_numeric = checklist_item_factory(
        template=template,
        order=1,
        requires_comment=False,
    )
    item_option = checklist_item_factory(
        template=template,
        order=2,
        score_type=ChecklistItem.ScoreType.OPTION,
        options=["Соответствует", "Не соответствует"],
        requires_comment=True,
    )
    building = building_factory(created_by=admin_user)
    elevator = elevator_factory(building=building, created_by=admin_user)

    audit = Audit.objects.create(
        building=building,
        elevator=elevator,
        template=template,
        assigned_to=None,
        deadline=date.today(),
    )

    audit.assigned_to = auditor_user
    audit.save(update_fields=["assigned_to"])

    list_response = admin_client.get(reverse("audits:audit-list"))
    assert list_response.status_code == 200
    body = list_response.content.decode("utf-8")
    assert building.address in body
    assert elevator.identifier in body

    list_response = auditor_client.get(reverse("audits:audit-list"))
    assert list_response.status_code == 200
    auditor_body = list_response.content.decode("utf-8")
    assert audit.template.name in auditor_body

    detail_url = reverse("audits:audit-detail", args=[audit.pk])
    detail_response = auditor_client.get(detail_url)
    assert detail_response.status_code == 200

    draft_response = auditor_client.post(
        detail_url,
        data={
            f"item-{item_numeric.pk}-numeric_answer": "4",
            f"item-{item_numeric.pk}-comment": "Промежуточный осмотр",
            f"item-{item_option.pk}-selected_option": "",
            f"item-{item_option.pk}-comment": "",
            "action": "save_draft",
        },
    )
    assert draft_response.status_code == 302

    audit.refresh_from_db()
    assert audit.status == Audit.Status.DRAFT
    numeric_response = audit.responses.get(item=item_numeric)
    assert numeric_response.numeric_answer == Decimal("4.00")
    assert numeric_response.comment == "Промежуточный осмотр"
    assert not audit.responses.filter(item=item_option).exists()

    submit_response = auditor_client.post(
        detail_url,
        data={
            f"item-{item_numeric.pk}-numeric_answer": "5",
            f"item-{item_numeric.pk}-comment": "Итоговая оценка",
            f"item-{item_option.pk}-selected_option": "Соответствует",
            f"item-{item_option.pk}-comment": "Фото загружены",
            "action": "submit",
        },
    )
    assert submit_response.status_code == 302

    audit.refresh_from_db()
    assert audit.status == Audit.Status.SUBMITTED
    assert audit.submitted_at is not None
    assert audit.score == Decimal("5.00")
    assert audit.responses.count() == 2

    option_response = audit.responses.get(item=item_option)
    assert option_response.selected_option == "Соответствует"
    assert option_response.comment == "Фото загружены"
