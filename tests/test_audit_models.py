from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from audits.models import Audit, AuditResponse


@pytest.mark.django_db
def test_calculate_score_weights(audit_factory, checklist_item_factory, audit_response_factory):
    audit = audit_factory()
    item_a = checklist_item_factory(template=audit.template, weight=2, order=1)
    item_b = checklist_item_factory(template=audit.template, weight=1, order=2)

    audit_response_factory(audit=audit, item=item_a, numeric_answer=4)
    audit_response_factory(audit=audit, item=item_b, numeric_answer=1)

    score = audit.calculate_score()
    assert score == Decimal("3.00")
    audit.refresh_from_db()
    assert audit.score == Decimal("3.00")


@pytest.mark.django_db
def test_response_save_updates_audit_score(audit_factory, checklist_item_factory):
    audit = audit_factory(score=Decimal("0.00"))
    item = checklist_item_factory(template=audit.template, order=1)

    response = AuditResponse(audit=audit, item=item, numeric_answer=4)
    response.save()

    audit.refresh_from_db()
    assert audit.score == Decimal("4.00")


@pytest.mark.django_db
def test_mark_submitted_sets_timestamp(audit_factory):
    audit = audit_factory(status=Audit.Status.DRAFT)
    audit.mark_submitted()
    assert audit.status == Audit.Status.SUBMITTED
    assert audit.submitted_at is not None


@pytest.mark.django_db
def test_mark_submitted_recalculates_score(
    audit_factory,
    checklist_item_factory,
    audit_response_factory,
):
    audit = audit_factory(status=Audit.Status.DRAFT)
    item = checklist_item_factory(template=audit.template, order=1)
    audit_response_factory(audit=audit, item=item, numeric_answer=2)

    Audit.objects.filter(pk=audit.pk).update(score=Decimal("10.00"))
    audit.refresh_from_db()

    audit.mark_submitted()
    audit.refresh_from_db()

    assert audit.status == Audit.Status.SUBMITTED
    assert audit.score == Decimal("2.00")


@pytest.mark.django_db
def test_request_changes_sets_comment(audit_factory):
    audit = audit_factory(status=Audit.Status.SUBMITTED, admin_comment="")
    audit.request_changes(comment="Нужны фотографии")
    assert audit.status == Audit.Status.DRAFT
    assert audit.submitted_at is None
    assert audit.admin_comment == "Нужны фотографии"


@pytest.mark.django_db
def test_response_validates_range(audit_factory, checklist_item_factory, audit_response_factory):
    audit = audit_factory()
    item = checklist_item_factory(template=audit.template, min_score=0, max_score=5, step=1)
    response = audit_response_factory.build(audit=audit, item=item, numeric_answer=7)
    with pytest.raises(ValidationError):
        response.full_clean()
