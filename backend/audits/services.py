"""Helper functions for auditor-facing catalogue snapshots."""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from catalog.models import Building, Elevator, ObjectInfoField


def _serialise_building(building: Building) -> dict[str, Any]:
    """Convert a building instance to a JSON-friendly structure."""

    return {
        "id": building.pk,
        "address": building.address,
        "entrance": building.entrance or "",
        "notes": building.notes or "",
        "label": str(building),
        "review_status": building.review_status,
    }


def _serialise_elevator(elevator: Elevator) -> dict[str, Any]:
    """Convert an elevator instance to a JSON-friendly structure."""

    return {
        "id": elevator.pk,
        "building_id": elevator.building_id,
        "identifier": elevator.identifier,
        "description": elevator.description or "",
        "status": elevator.status,
        "label": elevator.identifier,
        "building_label": str(elevator.building),
        "review_status": elevator.review_status,
    }


def _serialise_object_info_field(field: ObjectInfoField) -> dict[str, Any]:
    """Prepare object info field metadata for UI consumption."""

    choices = [value.strip() for value in field.choices.splitlines() if value.strip()]
    return {
        "code": field.code,
        "label": field.label,
        "field_type": field.field_type,
        "is_required": field.is_required,
        "order": field.order,
        "choices": choices,
    }


def build_catalog_snapshot_for_user(user: object) -> dict[str, Any]:
    """Return a catalogue snapshot containing buildings, elevators and object fields."""

    buildings_qs = Building.objects.visible_for_user(user).select_related("created_by__profile")
    elevators_qs = Elevator.objects.visible_for_user(user).select_related("building")
    fields_qs = ObjectInfoField.objects.all().order_by("order", "label")

    return {
        "generated_at": timezone.now().isoformat(),
        "buildings": [_serialise_building(item) for item in buildings_qs],
        "elevators": [_serialise_elevator(item) for item in elevators_qs],
        "object_fields": [_serialise_object_info_field(item) for item in fields_qs],
    }

