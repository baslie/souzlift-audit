from __future__ import annotations

import pytest
from django.urls import reverse


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
