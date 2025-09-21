from __future__ import annotations

import io
import json

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command

from audits.models import Audit, AuditAttachment, AuditResponse
from checklists.models import ChecklistItem


@pytest.mark.django_db
def test_migration_rehearsal_command_generates_report(
    tmp_path,
    admin_user,
    auditor_user,
    building_factory,
    elevator_factory,
    checklist_template_factory,
    checklist_item_factory,
):
    template = checklist_template_factory()
    numeric_item = checklist_item_factory(
        template=template,
        order=1,
        score_type=ChecklistItem.ScoreType.NUMERIC,
        min_score=0,
        max_score=5,
        step=1,
    )
    option_item = checklist_item_factory(
        template=template,
        order=2,
        score_type=ChecklistItem.ScoreType.OPTION,
        options=["Да", "Нет"],
    )
    building = building_factory(created_by=admin_user)
    elevator = elevator_factory(building=building, created_by=admin_user)

    audit = Audit.objects.create(
        building=building,
        elevator=elevator,
        template=template,
        assigned_to=auditor_user,
    )

    numeric_response = AuditResponse.objects.create(
        audit=audit,
        item=numeric_item,
        numeric_answer=4,
    )
    AuditResponse.objects.create(
        audit=audit,
        item=option_item,
        selected_option="Да",
        comment="Приложены фото",
    )
    audit.calculate_score(commit=True)
    audit.mark_submitted(commit=True)

    AuditAttachment.objects.create(
        audit=audit,
        response=numeric_response,
        uploaded_by=admin_user,
        caption="Фото",
        file=ContentFile(b"demo", name="attachment-demo.txt"),
    )

    output_file = tmp_path / "migration-report.json"
    stdout = io.StringIO()
    call_command(
        "migration_rehearsal",
        stdout=stdout,
        stderr=io.StringIO(),
        output=str(output_file),
        max_file_checks=5,
    )

    console_output = stdout.getvalue()
    assert "Отчёт репетиции миграции" in console_output
    assert "Итог: критичных ошибок не обнаружено" in console_output

    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["summary"]["passed"] is True
    assert data["audits"]["status_breakdown"].get(Audit.Status.SUBMITTED, 0) == 1
    assert data["checklists"]["items_total"] == 2
    assert data["attachments"]["total"] == 1

