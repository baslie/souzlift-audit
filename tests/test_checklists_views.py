from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_template_list_view(admin_client, checklist_template_factory):
    checklist_template_factory(name="Шаблон 1")
    response = admin_client.get(reverse("checklists:template-list"))
    assert response.status_code == 200
    assert "Шаблон 1" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_template_detail_view(admin_client, checklist_template_factory, checklist_item_factory):
    template = checklist_template_factory(name="Шаблон 2")
    checklist_item_factory(template=template, question="Проверка дверей")
    response = admin_client.get(reverse("checklists:template-detail", args=[template.pk]))
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Шаблон 2" in body
    assert "Проверка дверей" in body
