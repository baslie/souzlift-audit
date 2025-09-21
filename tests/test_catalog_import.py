from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
import pytest

from catalog.models import Building, Elevator
from catalog.services import (
    CatalogImportExecutionError,
    build_building_preview,
    build_elevator_preview,
    import_buildings,
    import_elevators,
)


@pytest.mark.django_db
def test_build_building_preview_detects_errors(admin_user):
    content = "address,entrance,notes\n,1,Комментарий\n".encode("utf-8")
    uploaded = SimpleUploadedFile("buildings.csv", content, content_type="text/csv")

    preview = build_building_preview(uploaded)

    assert preview.total_rows == 1
    assert preview.error_rows[0].errors


@pytest.mark.django_db
def test_import_buildings_creates_and_updates(admin_user):
    rows = [
        {"row_number": 2, "address": "Адрес 1", "entrance": "", "notes": ""},
    ]
    result = import_buildings(rows, admin_user)

    building = Building.objects.get(address="Адрес 1")
    assert result.created_count == 1
    assert result.updated_count == 0
    assert building.created_by == admin_user

    rows = [
        {"row_number": 2, "address": "Адрес 1", "entrance": "", "notes": "Обновлено"},
    ]
    result = import_buildings(rows, admin_user)
    building.refresh_from_db()

    assert result.created_count == 0
    assert result.updated_count == 1
    assert building.notes == "Обновлено"


@pytest.mark.django_db
def test_build_elevator_preview_maps_buildings(building_factory):
    building = building_factory(address="Адрес 2", entrance="")
    content = "building_address,identifier,status\nАдрес 2,EL-001,В эксплуатации\n".encode("utf-8")
    uploaded = SimpleUploadedFile("elevators.csv", content, content_type="text/csv")

    preview = build_elevator_preview(uploaded)

    assert preview.total_rows == 1
    row = preview.valid_rows[0]
    assert row.data["building_id"] == building.id
    assert row.data["status"] == Elevator.Status.IN_SERVICE


@pytest.mark.django_db
def test_import_elevators_requires_existing_building(admin_user):
    rows = [
        {
            "row_number": 2,
            "building_id": 9999,
            "identifier": "EL-404",
            "status": Elevator.Status.IN_SERVICE,
            "description": "",
        }
    ]

    with pytest.raises(CatalogImportExecutionError):
        import_elevators(rows, admin_user)


@pytest.mark.django_db
def test_import_elevators_creates_records(admin_user, building_factory):
    building = building_factory(address="Адрес 3", entrance="1")
    rows = [
        {
            "row_number": 2,
            "building_id": building.id,
            "identifier": "EL-100",
            "status": Elevator.Status.IN_SERVICE,
            "description": "Грузовой",
        }
    ]

    result = import_elevators(rows, admin_user)

    elevator = Elevator.objects.get(building=building, identifier="EL-100")
    assert result.created_count == 1
    assert elevator.description == "Грузовой"
    assert elevator.created_by == admin_user
