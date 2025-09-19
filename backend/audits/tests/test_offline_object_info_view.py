from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Building, Elevator, ObjectInfoField, ReviewStatus


class OfflineObjectInfoViewTests(TestCase):
    """Integration tests for the offline object info form view."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.auditor = UserModel.objects.create_user(username="auditor", password="Secret123!")
        self.auditor.profile.mark_password_changed()

        self.other_user = UserModel.objects.create_user(username="other", password="Secret123!")
        self.other_user.profile.mark_password_changed()

        self.url = reverse("audits:offline-object-info")

        self.approved_building = Building.objects.create(
            address="Советская, 10",
            entrance="1",
            review_status=ReviewStatus.APPROVED,
            created_by=self.other_user,
        )
        self.own_pending_building = Building.objects.create(
            address="Вершинина, 5",
            review_status=ReviewStatus.PENDING,
            created_by=self.auditor,
        )
        self.hidden_building = Building.objects.create(
            address="Никитина, 20",
            review_status=ReviewStatus.PENDING,
            created_by=self.other_user,
        )

        self.visible_elevator = Elevator.objects.create(
            building=self.approved_building,
            identifier="EL-001",
            review_status=ReviewStatus.APPROVED,
            created_by=self.auditor,
        )
        self.pending_elevator = Elevator.objects.create(
            building=self.approved_building,
            identifier="EL-002",
            review_status=ReviewStatus.PENDING,
            created_by=self.auditor,
        )
        self.hidden_elevator = Elevator.objects.create(
            building=self.approved_building,
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

    def test_requires_authentication(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.headers.get("Location", ""))

    def test_denies_user_without_allowed_role(self) -> None:
        UserModel = get_user_model()
        outsider = UserModel.objects.create_user(username="guest", password="Secret123!")
        outsider.profile.role = "MANAGER"
        outsider.profile.mark_password_changed()
        outsider.profile.save(update_fields=["role", "password_changed_at"])

        self.client.force_login(outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_renders_catalog_snapshot_in_context(self) -> None:
        self.client.force_login(self.auditor)
        response = self.client.get(self.url, {"client_id": "draft-123"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "audits/offline_object_info.html")

        context = response.context
        self.assertEqual(context["client_id"], "draft-123")
        self.assertEqual(context["catalog_snapshot_url"], reverse("catalog-snapshot"))
        self.assertEqual(context["return_url"], reverse("audits:audit-list"))

        fields = context["object_info_fields"]
        field_codes = {field["code"] for field in fields}
        self.assertEqual(field_codes, {"manager", "class"})

        choices_field = next(field for field in fields if field["code"] == "class")
        self.assertEqual(choices_field["choices"], ["A", "B"])

        payload = context["catalog_payload"]
        building_ids = {item["id"] for item in payload["buildings"]}
        self.assertIn(self.approved_building.pk, building_ids)
        self.assertIn(self.own_pending_building.pk, building_ids)
        self.assertNotIn(self.hidden_building.pk, building_ids)

        elevator_ids = {item["id"] for item in payload["elevators"]}
        self.assertIn(self.visible_elevator.pk, elevator_ids)
        self.assertIn(self.pending_elevator.pk, elevator_ids)
        self.assertNotIn(self.hidden_elevator.pk, elevator_ids)

        metadata = context["catalog_metadata"]
        self.assertIn("generated_at", metadata)
        self.assertIsInstance(metadata["generated_at"], str)
        self.assertTrue(metadata["generated_at"])
