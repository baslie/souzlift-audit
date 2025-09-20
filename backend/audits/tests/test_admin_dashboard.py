"""Tests covering the Django admin dashboard for audits."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from audits.models import Audit, OfflineSyncBatch
from catalog.models import Building, Elevator


class AuditAdminDashboardTests(TestCase):
    """Ensure the admin changelist provides dashboard metrics and filters."""

    def setUp(self) -> None:
        UserModel = get_user_model()
        self.admin = UserModel.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="Pass12345",
        )
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        self.auditor = UserModel.objects.create_user(
            username="auditor",
            password="Pass12345",
            is_staff=False,
        )
        self.auditor.profile.mark_password_changed()

        self.client.force_login(self.admin)

        self.building = Building.objects.create(address="Ленина, 12", created_by=self.admin)
        self.elevator = Elevator.objects.create(
            building=self.building,
            identifier="EL-001",
            created_by=self.admin,
        )

        today = timezone.localdate()

        self.draft = Audit.objects.create(elevator=self.elevator, created_by=self.auditor)
        self.in_progress = Audit.objects.create(
            elevator=self.elevator,
            created_by=self.auditor,
            planned_date=today + timedelta(days=1),
        )
        self.in_progress.start(actor=self.auditor)

        self.submitted = Audit.objects.create(
            elevator=self.elevator,
            created_by=self.auditor,
            planned_date=today - timedelta(days=1),
            total_score=70,
        )
        self.submitted.start(actor=self.auditor)
        self.submitted.submit(actor=self.auditor)

        self.reviewed = Audit.objects.create(
            elevator=self.elevator,
            created_by=self.auditor,
            planned_date=today - timedelta(days=3),
            total_score=90,
        )
        self.reviewed.start(actor=self.auditor)
        self.reviewed.submit(actor=self.auditor)
        self.reviewed.mark_reviewed(actor=self.admin)

        self.pending_batch = OfflineSyncBatch.objects.create(
            user=self.auditor,
            device_id="device-pending",
            payload={"kind": "data"},
        )
        self.applied_batch = OfflineSyncBatch.objects.create(
            user=self.auditor,
            device_id="device-applied",
            payload={"kind": "data"},
        )
        self.applied_batch.mark_applied({"status": "ok"}, status=200)
        self.error_batch = OfflineSyncBatch.objects.create(
            user=self.auditor,
            device_id="device-error",
            payload={"kind": "attachment"},
        )
        self.error_batch.mark_error({"detail": "Timeout"}, status=400)

    def test_dashboard_context_contains_expected_metrics(self) -> None:
        """The changelist view should provide aggregated metrics for display."""

        response = self.client.get(reverse("admin:audits_audit_changelist"))
        self.assertEqual(response.status_code, 200)

        dashboard = response.context.get("audit_dashboard")
        self.assertIsNotNone(dashboard)
        assert dashboard is not None

        overall = dashboard["overall_summary"]
        filtered = dashboard["filtered_summary"]

        self.assertEqual(overall["total"], 4)
        self.assertEqual(overall["reviewed"], 1)
        self.assertEqual(overall["in_progress"], 1)
        self.assertEqual(filtered["submitted"], 1)
        self.assertEqual(filtered["overdue"], 1)

        self.assertIn("status_breakdown", dashboard)
        pending_entry = next(
            (item for item in dashboard["status_breakdown"] if item["value"] == Audit.Status.SUBMITTED),
            None,
        )
        self.assertIsNotNone(pending_entry)
        assert pending_entry is not None
        self.assertEqual(pending_entry["filtered"], 1)
        self.assertEqual(pending_entry["overall"], 1)

        overall_avg = overall["avg_score"]
        self.assertIsNotNone(overall_avg)
        assert overall_avg is not None
        self.assertAlmostEqual(float(overall_avg), 40.0)

        offline = dashboard["offline_summary"]
        self.assertEqual(offline["total"], 3)
        self.assertEqual(offline["applied"], 1)
        self.assertEqual(offline["pending"], 1)
        self.assertEqual(offline["errors"], 1)
        self.assertEqual(offline["errors_last_24h"], 1)
        self.assertEqual(offline["errors_last_7_days"], 1)
        self.assertEqual(offline["applied_last_7_days"], 1)
        self.assertEqual(offline["pending_stale"], 0)
        self.assertIsNotNone(offline["last_error"])
        assert offline["last_error"] is not None
        self.assertEqual(offline["last_error"]["device_id"], "device-error")

    def test_review_state_quick_filter(self) -> None:
        """Quick filters should reduce queryset according to review workflow."""

        url = reverse("admin:audits_audit_changelist")
        response = self.client.get(url, {"review_state": "pending"})
        self.assertEqual(response.status_code, 200)
        pending_statuses = list(response.context["cl"].queryset.values_list("status", flat=True))
        self.assertEqual(pending_statuses, [Audit.Status.SUBMITTED])

        response = self.client.get(url, {"review_state": "active"})
        self.assertEqual(response.status_code, 200)
        active_statuses = set(response.context["cl"].queryset.values_list("status", flat=True))
        self.assertSetEqual(active_statuses, {Audit.Status.DRAFT, Audit.Status.IN_PROGRESS})

        response = self.client.get(url, {"review_state": "reviewed"})
        self.assertEqual(response.status_code, 200)
        reviewed_statuses = list(response.context["cl"].queryset.values_list("status", flat=True))
        self.assertEqual(reviewed_statuses, [Audit.Status.REVIEWED])

    def test_due_quick_filter_overdue_excludes_reviewed(self) -> None:
        """The overdue quick filter should exclude already reviewed audits."""

        url = reverse("admin:audits_audit_changelist")
        response = self.client.get(url, {"due": "overdue"})
        self.assertEqual(response.status_code, 200)
        queryset = response.context["cl"].queryset
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first(), self.submitted)

        response = self.client.get(url, {"due": "without_plan"})
        self.assertEqual(response.status_code, 200)
        without_plan = list(response.context["cl"].queryset)
        self.assertEqual(without_plan, [self.draft])

        response = self.client.get(url, {"due": "today"})
        self.assertEqual(response.status_code, 200)
        today_results = list(response.context["cl"].queryset)
        self.assertEqual(today_results, [])

        response = self.client.get(url, {"due": "week"})
        self.assertEqual(response.status_code, 200)
        week_results = list(response.context["cl"].queryset)
        self.assertEqual(week_results, [self.in_progress])
