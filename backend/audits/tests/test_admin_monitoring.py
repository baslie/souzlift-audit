from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from audits.models import Audit, AuditLogEntry, OfflineSyncBatch
from backend.tests import factories as test_factories


class AdminMonitoringViewsTests(TestCase):
    """Проверки пользовательских страниц мониторинга для администратора."""

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

        self.log_url = reverse("audits:audit-log-list")
        self.batches_url = reverse("audits:offline-batch-list")

    def test_log_view_filters_and_export(self) -> None:
        """Администратор может фильтровать журнал и экспортировать CSV."""

        audit = test_factories.AuditFactory(created_by=self.auditor)
        other_audit = test_factories.AuditFactory(created_by=self.auditor)

        AuditLogEntry.objects.all().delete()

        entry_recent = AuditLogEntry.objects.create(
            user=self.auditor,
            action=AuditLogEntry.Action.AUDIT_CREATED,
            entity_type="audits.audit",
            entity_id=str(audit.pk),
            payload={"status": Audit.Status.DRAFT},
        )
        entry_old = AuditLogEntry.objects.create(
            user=self.auditor,
            action=AuditLogEntry.Action.AUDIT_CREATED,
            entity_type="audits.audit",
            entity_id=str(other_audit.pk),
            payload={"status": Audit.Status.DRAFT},
        )
        AuditLogEntry.objects.filter(pk=entry_old.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )

        self.client.force_login(self.admin)
        response = self.client.get(
            self.log_url,
            {"start": timezone.localdate() - timedelta(days=1), "audit": audit.pk},
        )
        self.assertEqual(response.status_code, 200)
        page = response.context["page_obj"]
        self.assertEqual(page.paginator.count, 1)
        self.assertEqual(page.object_list[0].pk, entry_recent.pk)

        export = self.client.get(
            self.log_url,
            {"export": "csv", "audit": audit.pk},
        )
        self.assertEqual(export.status_code, 200)
        self.assertIn("text/csv", export["Content-Type"])
        self.assertIn(str(audit.pk), export.content.decode("utf-8"))

    def test_log_view_denied_for_auditor(self) -> None:
        """Аудитор не имеет доступа к журналу мониторинга."""

        self.client.force_login(self.auditor)
        response = self.client.get(self.log_url)
        self.assertEqual(response.status_code, 403)

    def test_offline_batches_view_filters_and_export(self) -> None:
        """Страница офлайн-пакетов поддерживает фильтрацию и экспорт."""

        batch_pending = test_factories.OfflineSyncBatchFactory(
            user=self.auditor,
            device_id="device-1",
        )
        batch_error = test_factories.OfflineSyncBatchFactory(
            user=self.auditor,
            device_id="special-device",
        )
        batch_error.mark_error({"detail": "Validation"}, status=400)
        OfflineSyncBatch.objects.filter(pk=batch_pending.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )

        self.client.force_login(self.admin)
        response = self.client.get(
            self.batches_url,
            {"device": "special", "status": OfflineSyncBatch.Status.ERROR},
        )
        self.assertEqual(response.status_code, 200)
        page = response.context["page_obj"]
        self.assertEqual(page.paginator.count, 1)
        self.assertEqual(page.object_list[0].pk, batch_error.pk)

        export = self.client.get(
            self.batches_url,
            {"export": "csv", "status": OfflineSyncBatch.Status.ERROR},
        )
        self.assertEqual(export.status_code, 200)
        self.assertIn("text/csv", export["Content-Type"])
        self.assertIn("special-device", export.content.decode("utf-8"))

    def test_offline_batches_denied_for_auditor(self) -> None:
        """Аудитор не может открыть страницу офлайн-пакетов."""

        self.client.force_login(self.auditor)
        response = self.client.get(self.batches_url)
        self.assertEqual(response.status_code, 403)
