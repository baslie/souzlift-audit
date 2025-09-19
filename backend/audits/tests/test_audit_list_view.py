from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from audits.models import Audit
from catalog.models import Building, Elevator


class AuditListViewTests(TestCase):
    """Интеграционные проверки страницы портала аудитора."""

    def setUp(self) -> None:
        UserModel = get_user_model()
        self.auditor = UserModel.objects.create_user(username="auditor", password="SecretPass123")
        self.auditor.profile.mark_password_changed()

        self.other_auditor = UserModel.objects.create_user(username="other", password="SecretPass123")
        self.other_auditor.profile.mark_password_changed()

        self.admin = UserModel.objects.create_user(username="admin", password="SecretPass123")
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        self.url = reverse("audits:audit-list")

    def _create_audit(
        self,
        *,
        author,
        status: str = Audit.Status.DRAFT,
        address: str = "Советская, 1",
        identifier: str = "EL-1",
        days_ago: int | None = None,
    ) -> Audit:
        building = Building.objects.create(address=address, created_by=author)
        elevator = Elevator.objects.create(building=building, identifier=identifier, created_by=author)
        audit = Audit.objects.create(elevator=elevator, created_by=author, status=status)
        if days_ago is not None:
            created = timezone.now() - timedelta(days=days_ago)
            Audit.objects.filter(pk=audit.pk).update(created_at=created)
            audit.created_at = created
        return audit

    def test_requires_authentication(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.headers.get("Location", ""))

    def test_lists_only_own_audits(self) -> None:
        self._create_audit(author=self.auditor, status=Audit.Status.DRAFT, address="Мира, 10", identifier="A-1")
        self._create_audit(author=self.auditor, status=Audit.Status.SUBMITTED, address="Кирова, 5", identifier="B-2")
        self._create_audit(author=self.other_auditor, status=Audit.Status.DRAFT, address="Ленина, 7", identifier="C-3")

        self.client.force_login(self.auditor)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        page = response.context["page_obj"]
        self.assertEqual(page.paginator.count, 2)
        authors = {audit.created_by_id for audit in page.object_list}
        self.assertEqual(authors, {self.auditor.pk})

    def test_status_filter_applied(self) -> None:
        self._create_audit(author=self.auditor, status=Audit.Status.DRAFT, address="Мира, 1", identifier="EL-1")
        submitted = self._create_audit(author=self.auditor, status=Audit.Status.SUBMITTED, address="Мира, 2", identifier="EL-2")

        self.client.force_login(self.auditor)
        response = self.client.get(self.url, {"status": Audit.Status.SUBMITTED})
        page = response.context["page_obj"]
        self.assertEqual(page.paginator.count, 1)
        self.assertEqual(page.object_list[0].pk, submitted.pk)

    def test_period_filter_limits_results(self) -> None:
        recent = self._create_audit(author=self.auditor, status=Audit.Status.DRAFT, address="Свободы, 4", identifier="R-1", days_ago=2)
        self._create_audit(author=self.auditor, status=Audit.Status.DRAFT, address="Свободы, 6", identifier="R-2", days_ago=45)

        self.client.force_login(self.auditor)
        response = self.client.get(self.url, {"period": "7"})
        page = response.context["page_obj"]
        self.assertEqual(page.paginator.count, 1)
        self.assertEqual(page.object_list[0].pk, recent.pk)

    def test_search_by_address_and_identifier(self) -> None:
        self._create_audit(author=self.auditor, address="Тверская, 5", identifier="T-1")
        target = self._create_audit(author=self.auditor, address="Комсомольская, 8", identifier="KM-42")

        self.client.force_login(self.auditor)
        response = self.client.get(self.url, {"q": "KM-42"})
        page = response.context["page_obj"]
        self.assertEqual(page.paginator.count, 1)
        self.assertEqual(page.object_list[0].pk, target.pk)

    def test_status_summary_present_in_context(self) -> None:
        self._create_audit(author=self.auditor, status=Audit.Status.DRAFT)
        self._create_audit(author=self.auditor, status=Audit.Status.IN_PROGRESS)
        self._create_audit(author=self.auditor, status=Audit.Status.SUBMITTED)

        self.client.force_login(self.auditor)
        response = self.client.get(self.url)
        status_filters = response.context["status_filters"]
        summary = {item["value"]: item for item in status_filters}
        self.assertIn(Audit.Status.DRAFT, summary)
        self.assertEqual(summary[Audit.Status.DRAFT]["count"], 1)
        total_entry = summary.get("")
        self.assertIsNotNone(total_entry)
        if total_entry is not None:
            self.assertEqual(total_entry["count"], 3)

    def test_admin_sees_all_audits(self) -> None:
        self._create_audit(author=self.auditor, status=Audit.Status.DRAFT)
        self._create_audit(author=self.other_auditor, status=Audit.Status.SUBMITTED)

        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        page = response.context["page_obj"]
        self.assertEqual(page.paginator.count, 2)
        owners = {audit.created_by_id for audit in page.object_list}
        self.assertEqual(owners, {self.auditor.pk, self.other_auditor.pk})
