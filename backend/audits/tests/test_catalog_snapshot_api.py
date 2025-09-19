from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Building, Elevator, ObjectInfoField, ReviewStatus


class CatalogSnapshotApiTests(TestCase):
    """Tests for the catalogue snapshot endpoint used by offline forms."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.auditor = UserModel.objects.create_user(username="auditor", password="Secret123!")
        self.auditor.profile.mark_password_changed()
        self.other_user = UserModel.objects.create_user(username="other", password="Secret123!")
        self.other_user.profile.mark_password_changed()
        self.client.force_login(self.auditor)

    def test_returns_visible_catalog_and_fields(self) -> None:
        approved_building = Building.objects.create(
            address="Советская, 10",
            entrance="1",
            review_status=ReviewStatus.APPROVED,
            created_by=self.other_user,
        )
        pending_building = Building.objects.create(
            address="Вершинина, 5",
            review_status=ReviewStatus.PENDING,
            created_by=self.auditor,
        )
        hidden_building = Building.objects.create(
            address="Никитина, 20",
            review_status=ReviewStatus.PENDING,
            created_by=self.other_user,
        )

        visible_elevator = Elevator.objects.create(
            building=approved_building,
            identifier="EL-001",
            review_status=ReviewStatus.APPROVED,
            created_by=self.auditor,
        )
        pending_elevator = Elevator.objects.create(
            building=approved_building,
            identifier="EL-002",
            review_status=ReviewStatus.PENDING,
            created_by=self.auditor,
        )
        hidden_elevator = Elevator.objects.create(
            building=approved_building,
            identifier="EL-003",
            review_status=ReviewStatus.PENDING,
            created_by=self.other_user,
        )

        ObjectInfoField.objects.create(
            code="manager",
            label="Ответственный",
            field_type=ObjectInfoField.FieldType.TEXT,
            is_required=True,
            order=1,
        )
        ObjectInfoField.objects.create(
            code="class",
            label="Класс",
            field_type=ObjectInfoField.FieldType.CHOICE,
            choices="A\nB",
            order=2,
        )

        url = reverse("catalog-snapshot")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        buildings = payload.get("buildings", [])
        building_ids = {item["id"] for item in buildings}
        self.assertIn(approved_building.pk, building_ids)
        self.assertIn(pending_building.pk, building_ids)
        self.assertNotIn(hidden_building.pk, building_ids)

        elevators = payload.get("elevators", [])
        elevator_ids = {item["id"] for item in elevators}
        self.assertIn(visible_elevator.pk, elevator_ids)
        self.assertIn(pending_elevator.pk, elevator_ids)
        self.assertNotIn(hidden_elevator.pk, elevator_ids)

        fields = payload.get("object_fields", [])
        field_codes = {field["code"] for field in fields}
        self.assertIn("manager", field_codes)
        self.assertIn("class", field_codes)
        choice_field = next(field for field in fields if field["code"] == "class")
        self.assertEqual(choice_field["choices"], ["A", "B"])

        generated_at = payload.get("generated_at")
        self.assertIsInstance(generated_at, str)
        self.assertTrue(generated_at)

    def test_forbidden_for_user_without_role(self) -> None:
        self.client.logout()
        UserModel = get_user_model()
        guest = UserModel.objects.create_user(username="guest", password="Secret123!")
        guest.profile.role = "MANAGER"
        guest.profile.mark_password_changed()
        guest.profile.save(update_fields=["role", "password_changed_at"])
        self.client.force_login(guest)

        response = self.client.get(reverse("catalog-snapshot"))
        self.assertEqual(response.status_code, 403)
