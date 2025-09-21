from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_building_list(admin_client, building_factory):
    building_factory(address="Пушкина, 10")
    response = admin_client.get(reverse("catalog:building-list"))
    assert response.status_code == 200
    assert "Пушкина, 10" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_elevator_create_form(admin_client, building_factory):
    building = building_factory()
    response = admin_client.get(reverse("catalog:elevator-create"))
    assert response.status_code == 200
    assert building.address in response.content.decode("utf-8")
