from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from audits.models import Audit, OfflineSyncBatch
from catalog.models import Building, Elevator


class AuditEmailNotificationsTests(TestCase):
    def setUp(self) -> None:
        self.UserModel = get_user_model()
        mail.outbox.clear()

        self.admin = self.UserModel.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="StrongPass123!",
        )
        self.admin.profile.role = self.admin.profile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])

        self.auditor = self.UserModel.objects.create_user(
            username="auditor",
            email="auditor@example.com",
            password="StrongPass123!",
        )

        mail.outbox.clear()

        self.building = Building.objects.create(address="Ленина, 1", created_by=self.admin)
        self.elevator = Elevator.objects.create(
            building=self.building,
            identifier="EL-001",
            created_by=self.admin,
        )

        self.audit = Audit.objects.create(elevator=self.elevator, created_by=self.auditor)

    def test_admin_notified_when_audit_submitted(self) -> None:
        mail.outbox.clear()

        self.audit.start(actor=self.auditor)
        self.audit.submit(actor=self.auditor)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("аудит отправлен", message.subject.lower())
        self.assertEqual(message.recipients(), ["admin@example.com"])

    def test_auditor_notified_when_audit_reviewed(self) -> None:
        self.audit.start(actor=self.auditor)
        self.audit.submit(actor=self.auditor)
        mail.outbox.clear()

        self.audit.mark_reviewed(actor=self.admin)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("аудит просмотрен", message.subject.lower())
        self.assertEqual(message.recipients(), ["auditor@example.com"])

    def test_auditor_notified_when_changes_requested(self) -> None:
        self.audit.start(actor=self.auditor)
        self.audit.submit(actor=self.auditor)
        mail.outbox.clear()

        self.audit.request_changes(
            actor=self.admin,
            message="Добавьте фотографии для раздела безопасности.",
        )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("правк", message.subject.lower())
        self.assertIn("фотографии", message.body)
        self.assertEqual(message.recipients(), ["auditor@example.com"])

    def test_offline_sync_error_notifies_admins(self) -> None:
        batch = OfflineSyncBatch.objects.create(
            user=self.auditor,
            device_id="device-1",
            payload={"kind": "data"},
        )

        mail.outbox.clear()

        batch.mark_error({"detail": "Размер вложения превышен"}, status=400)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("ошибка офлайн-синхронизации", message.subject.lower())
        self.assertEqual(message.recipients(), ["admin@example.com"])
        self.assertIn("Размер вложения", message.body)
