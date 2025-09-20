from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from audits.models import Audit
from catalog.models import Building, Elevator


class AdminAuditPortalTests(TestCase):
    """Проверки пользовательского интерфейса аудитов для роли администратора."""

    def setUp(self) -> None:
        UserModel = get_user_model()

        self.admin = UserModel.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="StrongPass123",
        )
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        self.auditor = UserModel.objects.create_user(
            username="auditor",
            email="auditor@example.com",
            password="StrongPass123",
        )
        self.auditor.profile.role = UserProfile.Roles.AUDITOR
        self.auditor.profile.save(update_fields=["role"])
        self.auditor.profile.mark_password_changed()

        self.other_auditor = UserModel.objects.create_user(
            username="auditor2",
            email="auditor2@example.com",
            password="StrongPass123",
        )
        self.other_auditor.profile.role = UserProfile.Roles.AUDITOR
        self.other_auditor.profile.save(update_fields=["role"])
        self.other_auditor.profile.mark_password_changed()

        self.building = Building.objects.create(address="Ленина, 5", created_by=self.admin)
        self.elevator = Elevator.objects.create(
            building=self.building,
            identifier="EL-101",
            created_by=self.admin,
        )

        self.audit_draft = Audit.objects.create(
            elevator=self.elevator,
            created_by=self.auditor,
        )

        self.audit_in_progress = Audit.objects.create(
            elevator=self.elevator,
            created_by=self.auditor,
        )
        self.audit_in_progress.start(actor=self.auditor)

        self.audit_submitted = Audit.objects.create(
            elevator=self.elevator,
            created_by=self.auditor,
        )
        self.audit_submitted.start(actor=self.auditor)
        self.audit_submitted.submit(actor=self.auditor)

        self.audit_reviewed = Audit.objects.create(
            elevator=self.elevator,
            created_by=self.auditor,
        )
        self.audit_reviewed.start(actor=self.auditor)
        self.audit_reviewed.submit(actor=self.auditor)
        self.audit_reviewed.mark_reviewed(actor=self.admin)

        self.list_url = reverse("audits:audit-list")
        self.detail_url = reverse("audits:audit-detail", args=[self.audit_submitted.pk])

    def test_review_filter_for_admin(self) -> None:
        """Администратор может отфильтровать аудиты по признаку просмотра."""

        self.client.force_login(self.admin)

        response = self.client.get(self.list_url, {"review": "pending"})
        self.assertEqual(response.status_code, 200)
        page = response.context["page_obj"]
        self.assertEqual(page.paginator.count, 1)
        self.assertEqual(page.object_list[0].pk, self.audit_submitted.pk)

        response = self.client.get(self.list_url, {"review": "reviewed"})
        self.assertEqual(response.status_code, 200)
        page = response.context["page_obj"]
        self.assertEqual(page.paginator.count, 1)
        self.assertEqual(page.object_list[0].pk, self.audit_reviewed.pk)

        review_filters = response.context["review_filters"]
        self.assertTrue(any(item["selected"] for item in review_filters if item["value"] == "reviewed"))

    def test_review_filter_ignored_for_auditor(self) -> None:
        """Аудитор не видит фильтр проверки и получает все свои аудиты."""

        self.client.force_login(self.auditor)
        response = self.client.get(self.list_url, {"review": "pending"})
        self.assertEqual(response.status_code, 200)

        page = response.context["page_obj"]
        self.assertGreaterEqual(page.paginator.count, 2)
        self.assertEqual(response.context["review_filters"], [])

    def test_admin_can_open_detail_view(self) -> None:
        """Детальная страница аудита доступна администратору и показывает сводку."""

        self.client.force_login(self.admin)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Информационная карта")
        self.assertContains(response, "Ответы чек-листа")
        self.assertTrue(response.context["can_mark_reviewed"])

    def test_auditor_cannot_access_detail_view(self) -> None:
        """Аудитор не имеет доступа к детальной странице администратора."""

        self.client.force_login(self.auditor)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 403)

    def test_mark_reviewed_changes_status_and_notifies(self) -> None:
        """POST запрос администратора переводит аудит в статус «Просмотрен» и отправляет письмо."""

        mail.outbox.clear()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("audits:audit-mark-reviewed", args=[self.audit_submitted.pk]),
            {"next": self.list_url},
        )
        self.assertRedirects(response, self.list_url)

        self.audit_submitted.refresh_from_db()
        self.assertEqual(self.audit_submitted.status, Audit.Status.REVIEWED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("просмотр", mail.outbox[0].subject.lower())

