"""Tests for moderation workflow of catalog records."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile

from .models import Building, Elevator, ReviewStatus


class CatalogModerationTests(TestCase):
    """Covers moderation queue behaviour for buildings and elevators."""

    def setUp(self) -> None:
        self.UserModel = get_user_model()

        self.admin = self.UserModel.objects.create_user(
            username="admin",
            password="StrongPass123",
        )
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])

        self.auditor = self.UserModel.objects.create_user(
            username="auditor",
            password="StrongPass123",
        )
        self.other_auditor = self.UserModel.objects.create_user(
            username="other",
            password="StrongPass123",
        )

        self.building = Building.objects.create(
            address="Ленина, 1",
            created_by=self.auditor,
        )
        self.other_building = Building.objects.create(
            address="Победы, 15",
            created_by=self.other_auditor,
        )

    def test_approve_and_reject_update_metadata(self) -> None:
        """Approving and rejecting records updates review metadata."""

        self.building.approve(self.admin)
        self.building.refresh_from_db()
        self.assertEqual(self.building.review_status, ReviewStatus.APPROVED)
        self.assertEqual(self.building.verified_by, self.admin)
        self.assertIsNotNone(self.building.verified_at)

        # Simulate a short delay to ensure timestamp refresh on rejection.
        self.building.verified_at = timezone.now() - timedelta(minutes=5)
        self.building.save(update_fields=["verified_at"])

        self.building.reject(self.admin)
        self.building.refresh_from_db()
        self.assertEqual(self.building.review_status, ReviewStatus.REJECTED)
        self.assertEqual(self.building.verified_by, self.admin)
        self.assertGreaterEqual(self.building.verified_at, timezone.now() - timedelta(minutes=1))

    def test_send_to_review_resets_verification(self) -> None:
        """Returning a record to moderation clears reviewer data."""

        self.building.approve(self.admin)
        self.building.refresh_from_db()
        self.assertIsNotNone(self.building.verified_by)

        self.building.send_to_review()
        self.building.refresh_from_db()
        self.assertEqual(self.building.review_status, ReviewStatus.PENDING)
        self.assertIsNone(self.building.verified_by)
        self.assertIsNone(self.building.verified_at)

    def test_visible_for_user_filters_records(self) -> None:
        """Only approved or own records are visible to non-admin users."""

        approved_building = Building.objects.create(
            address="Советская, 22",
            created_by=self.other_auditor,
        )
        approved_building.approve(self.admin)

        invisible_building = Building.objects.create(
            address="Томская, 9",
            created_by=self.other_auditor,
        )

        auditor_queryset = Building.objects.visible_for_user(self.auditor)
        self.assertIn(self.building, auditor_queryset)
        self.assertIn(approved_building, auditor_queryset)
        self.assertNotIn(invisible_building, auditor_queryset)

        other_queryset = Building.objects.visible_for_user(self.other_auditor)
        self.assertIn(approved_building, other_queryset)
        self.assertIn(invisible_building, other_queryset)  # Creator sees own pending entry.
        self.assertNotIn(self.building, other_queryset)

        admin_queryset = Building.objects.visible_for_user(self.admin)
        self.assertIn(self.building, admin_queryset)
        self.assertIn(self.other_building, admin_queryset)
        self.assertIn(invisible_building, admin_queryset)

        anonymous_queryset = Building.objects.visible_for_user(AnonymousUser())
        self.assertIn(approved_building, anonymous_queryset)
        self.assertNotIn(self.building, anonymous_queryset)

    def test_moderation_queue_orders_by_creation(self) -> None:
        """Queue for moderation returns pending entries in chronological order."""

        Building.objects.create(address="Кирова, 3", created_by=self.auditor)
        queued = list(Building.objects.for_moderation())
        self.assertEqual(queued, sorted(queued, key=lambda obj: obj.created_at))

    def test_elevator_moderation_helpers(self) -> None:
        """Elevators share the same moderation behaviour as buildings."""

        reference_building = Building.objects.create(address="Гагарина, 7", created_by=self.admin)
        reference_building.approve(self.admin)

        elevator = Elevator.objects.create(
            building=reference_building,
            identifier="EL-001",
            created_by=self.auditor,
        )

        self.assertEqual(elevator.review_status, ReviewStatus.PENDING)
        Elevator.objects.visible_for_user(self.admin)  # Should not raise.

        elevator.approve(self.admin)
        elevator.refresh_from_db()
        self.assertEqual(elevator.review_status, ReviewStatus.APPROVED)

        elevator.send_to_review()
        elevator.refresh_from_db()
        self.assertEqual(elevator.review_status, ReviewStatus.PENDING)


class CatalogViewsTests(TestCase):
    """Covers user interface interactions for catalog views."""

    def setUp(self) -> None:
        self.UserModel = get_user_model()

        self.admin = self.UserModel.objects.create_user(username="admin", password="StrongPass123")
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        self.auditor = self.UserModel.objects.create_user(username="auditor", password="StrongPass123")
        self.auditor.profile.mark_password_changed()
        self.other_auditor = self.UserModel.objects.create_user(username="other", password="StrongPass123")
        self.other_auditor.profile.mark_password_changed()

    def test_auditor_can_create_building(self) -> None:
        self.client.force_login(self.auditor)
        response = self.client.post(
            reverse("catalog:building-create"),
            data={"address": "Советская, 5", "entrance": "2", "notes": "Тестовая запись"},
        )
        self.assertRedirects(response, reverse("catalog:building-list"))
        building = Building.objects.get(address="Советская, 5")
        self.assertEqual(building.created_by, self.auditor)
        self.assertEqual(building.review_status, ReviewStatus.PENDING)

    def test_admin_can_approve_building_from_list(self) -> None:
        target = Building.objects.create(address="Ленина, 8", created_by=self.auditor)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("catalog:building-moderate", args=[target.pk]),
            data={"action": "approve", "next": reverse("catalog:building-list")},
        )
        self.assertRedirects(response, reverse("catalog:building-list"))
        target.refresh_from_db()
        self.assertEqual(target.review_status, ReviewStatus.APPROVED)
        self.assertEqual(target.verified_by, self.admin)

    def test_status_filter_returns_pending_records(self) -> None:
        approved = Building.objects.create(address="Кирова, 3", created_by=self.admin)
        approved.approve(self.admin)
        pending = Building.objects.create(address="Томская, 4", created_by=self.auditor)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("catalog:building-list"), data={"status": ReviewStatus.PENDING})
        self.assertEqual(response.status_code, 200)
        object_list = list(response.context["object_list"])
        self.assertIn(pending, object_list)
        self.assertNotIn(approved, object_list)

    def test_auditor_cannot_edit_foreign_building(self) -> None:
        foreign_building = Building.objects.create(address="Университетская, 12", created_by=self.other_auditor)
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("catalog:building-update", args=[foreign_building.pk]))
        self.assertEqual(response.status_code, 403)

    def test_auditor_can_create_elevator_for_approved_building(self) -> None:
        approved_building = Building.objects.create(address="Гагарина, 7", created_by=self.admin)
        approved_building.approve(self.admin)

        self.client.force_login(self.auditor)
        response = self.client.post(
            reverse("catalog:elevator-create"),
            data={
                "building": approved_building.pk,
                "identifier": "EL-101",
                "status": Elevator.Status.IN_SERVICE,
                "description": "Пассажирский лифт",
            },
        )
        self.assertRedirects(response, reverse("catalog:elevator-list"))
        elevator = Elevator.objects.get(identifier="EL-101")
        self.assertEqual(elevator.created_by, self.auditor)
        self.assertEqual(elevator.review_status, ReviewStatus.PENDING)
