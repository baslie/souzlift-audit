"""Tests for audit trail entries covering key operations."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import UserProfile
from audits.models import (
    Audit,
    AuditAttachment,
    AuditLogEntry,
    AuditResponse,
    AuditSignature,
    OfflineSyncBatch,
)
from catalog.models import (
    Building,
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    Elevator,
)

from .test_attachment_access import ProtectedMediaTestCase, SMALL_GIF


class AuditLogEntryTests(ProtectedMediaTestCase):
    """Cover creation and mutations of audit entities."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.admin = UserModel.objects.create_user(username="admin", password="Pass12345")
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        self.auditor = UserModel.objects.create_user(username="auditor", password="Pass12345")
        self.auditor.profile.mark_password_changed()

        self.category = ChecklistCategory.objects.create(code="safety", name="Безопасность", order=1)
        self.section = ChecklistSection.objects.create(category=self.category, title="Базовый", order=1)
        self.question = ChecklistQuestion.objects.create(section=self.section, text="Исправность", order=1)

        self.building = Building.objects.create(address="Ленина, 5", created_by=self.admin)
        self.elevator = Elevator.objects.create(building=self.building, identifier="EL-1", created_by=self.admin)

    def _create_audit(self) -> Audit:
        return Audit.objects.create(elevator=self.elevator, created_by=self.auditor)

    def test_audit_creation_is_logged(self) -> None:
        audit = self._create_audit()
        entry = AuditLogEntry.objects.filter(
            action=AuditLogEntry.Action.AUDIT_CREATED,
            entity_id=str(audit.pk),
        ).first()
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.user, self.auditor)
        self.assertEqual(entry.payload.get("status"), Audit.Status.DRAFT)

    def test_status_transition_is_logged_with_actor(self) -> None:
        audit = self._create_audit()
        audit.start(actor=self.admin)

        entry = (
            AuditLogEntry.objects.filter(
                action=AuditLogEntry.Action.AUDIT_STATUS_CHANGED,
                entity_id=str(audit.pk),
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.user, self.admin)
        self.assertEqual(entry.payload.get("from"), Audit.Status.DRAFT)
        self.assertEqual(entry.payload.get("to"), Audit.Status.IN_PROGRESS)

    def test_request_changes_is_logged(self) -> None:
        audit = self._create_audit()
        audit.start(actor=self.auditor)
        audit.submit(actor=self.auditor)

        audit.request_changes(actor=self.admin, message="Добавьте фотографии лифта.")

        entry = AuditLogEntry.objects.filter(
            action=AuditLogEntry.Action.AUDIT_CHANGES_REQUESTED,
            entity_id=str(audit.pk),
        ).first()
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.user, self.admin)
        self.assertEqual(entry.payload.get("status"), Audit.Status.SUBMITTED)
        self.assertIn("фотографии", entry.payload.get("message", ""))

    def test_response_lifecycle_is_logged(self) -> None:
        audit = self._create_audit()
        response = AuditResponse.objects.create(audit=audit, question=self.question, score=5)

        creation_entry = AuditLogEntry.objects.filter(
            action=AuditLogEntry.Action.RESPONSE_CREATED,
            entity_id=str(response.pk),
        ).first()
        self.assertIsNotNone(creation_entry)
        assert creation_entry is not None
        self.assertEqual(creation_entry.user, self.auditor)
        self.assertEqual(creation_entry.payload.get("score"), 5)

        response.score = 3
        response.comment = "Нарушение"
        response._log_actor = self.admin
        response.save(update_fields=["score", "comment"])

        update_entry = (
            AuditLogEntry.objects.filter(
                action=AuditLogEntry.Action.RESPONSE_UPDATED,
                entity_id=str(response.pk),
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(update_entry)
        assert update_entry is not None
        changes = update_entry.payload.get("changes", {})
        self.assertEqual(update_entry.user, self.admin)
        self.assertEqual(changes.get("score", {}).get("to"), 3)
        self.assertEqual(changes.get("comment", {}).get("to"), "Нарушение")

        response_id = response.pk
        response._log_actor = self.admin
        response.delete()

        delete_entry = (
            AuditLogEntry.objects.filter(
                action=AuditLogEntry.Action.RESPONSE_DELETED,
                entity_id=str(response_id),
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(delete_entry)
        assert delete_entry is not None
        self.assertEqual(delete_entry.user, self.admin)
        self.assertEqual(delete_entry.payload.get("score"), 3)

    def test_signature_is_logged(self) -> None:
        audit = self._create_audit()
        signature = AuditSignature.objects.create(
            audit=audit,
            signed_by="Инженер",
            signature_image=SimpleUploadedFile("sign.gif", SMALL_GIF, content_type="image/gif"),
        )

        creation_entry = AuditLogEntry.objects.filter(
            action=AuditLogEntry.Action.SIGNATURE_CREATED,
            entity_id=str(signature.pk),
        ).first()
        self.assertIsNotNone(creation_entry)
        assert creation_entry is not None
        self.assertEqual(creation_entry.user, self.auditor)
        self.assertEqual(creation_entry.payload.get("signed_by"), "Инженер")

        signature.signed_by = "Главный инженер"
        signature._log_actor = self.admin
        signature.save(update_fields=["signed_by"])

        update_entry = (
            AuditLogEntry.objects.filter(
                action=AuditLogEntry.Action.SIGNATURE_UPDATED,
                entity_id=str(signature.pk),
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(update_entry)
        assert update_entry is not None
        self.assertEqual(update_entry.user, self.admin)
        self.assertEqual(
            update_entry.payload.get("changes", {}).get("signed_by", {}).get("to"),
            "Главный инженер",
        )

        signature_id = signature.pk
        signature._log_actor = self.admin
        signature.delete()

        delete_entry = (
            AuditLogEntry.objects.filter(
                action=AuditLogEntry.Action.SIGNATURE_DELETED,
                entity_id=str(signature_id),
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(delete_entry)
        assert delete_entry is not None
        self.assertEqual(delete_entry.user, self.admin)
        self.assertEqual(delete_entry.payload.get("signed_by"), "Главный инженер")

    def test_mark_reviewed_is_logged(self) -> None:
        audit = self._create_audit()
        audit.start(actor=self.auditor)
        audit.submit(actor=self.auditor)

        audit.mark_reviewed(actor=self.admin)

        entry = AuditLogEntry.objects.filter(
            action=AuditLogEntry.Action.AUDIT_REVIEWED,
            entity_id=str(audit.pk),
        ).first()

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.user, self.admin)
        self.assertEqual(entry.payload.get("status"), Audit.Status.REVIEWED)
        self.assertIn("reviewed_at", entry.payload)


class AuditLogAttachmentTests(ProtectedMediaTestCase):
    """Ensure attachments produce log entries for lifecycle events."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.admin = UserModel.objects.create_user(username="admin2", password="Pass12345")
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        self.auditor = UserModel.objects.create_user(username="auditor2", password="Pass12345")
        self.auditor.profile.mark_password_changed()

        category = ChecklistCategory.objects.create(code="tech", name="Техника", order=1)
        section = ChecklistSection.objects.create(category=category, title="Раздел", order=1)
        self.question = ChecklistQuestion.objects.create(section=section, text="Проверка", order=1)

        building = Building.objects.create(address="Гагарина, 10", created_by=self.admin)
        self.elevator = Elevator.objects.create(building=building, identifier="EL-2", created_by=self.admin)

    def test_attachment_lifecycle_logged(self) -> None:
        audit = Audit.objects.create(elevator=self.elevator, created_by=self.auditor)
        response = AuditResponse.objects.create(audit=audit, question=self.question, score=4)

        attachment = AuditAttachment.objects.create(
            response=response,
            file=SimpleUploadedFile("photo.gif", SMALL_GIF, content_type="image/gif"),
            caption="Первое фото",
        )

        creation_entry = AuditLogEntry.objects.filter(
            action=AuditLogEntry.Action.ATTACHMENT_CREATED,
            entity_id=str(attachment.pk),
        ).first()
        self.assertIsNotNone(creation_entry)
        assert creation_entry is not None
        self.assertEqual(creation_entry.user, self.auditor)
        self.assertEqual(creation_entry.payload.get("response_id"), response.pk)

        attachment.caption = "Обновлено"
        attachment._log_actor = self.admin
        attachment.save(update_fields=["caption"])

        update_entry = (
            AuditLogEntry.objects.filter(
                action=AuditLogEntry.Action.ATTACHMENT_UPDATED,
                entity_id=str(attachment.pk),
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(update_entry)
        assert update_entry is not None
        self.assertEqual(update_entry.user, self.admin)
        self.assertEqual(
            update_entry.payload.get("changes", {}).get("caption", {}).get("to"),
            "Обновлено",
        )

        attachment_id = attachment.pk
        attachment._log_actor = self.admin
        attachment.delete()

        delete_entry = (
            AuditLogEntry.objects.filter(
                action=AuditLogEntry.Action.ATTACHMENT_DELETED,
                entity_id=str(attachment_id),
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(delete_entry)
        assert delete_entry is not None
        self.assertEqual(delete_entry.user, self.admin)
        self.assertEqual(delete_entry.payload.get("response_id"), response.pk)


class OfflineSyncBatchLogTests(ProtectedMediaTestCase):
    """Ensure offline synchronisation batches produce audit trail records."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.admin = UserModel.objects.create_user(username="admin3", password="Pass12345")
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        self.auditor = UserModel.objects.create_user(username="auditor3", password="Pass12345")
        self.auditor.profile.mark_password_changed()

    def test_offline_batch_lifecycle_logged(self) -> None:
        batch = OfflineSyncBatch.objects.create(
            user=self.auditor,
            device_id="device-001",
            payload={"kind": "data", "note": "create"},
            payload_hash="hash-1",
        )

        creation_entry = AuditLogEntry.objects.filter(
            action=AuditLogEntry.Action.OFFLINE_BATCH_CREATED,
            entity_id=str(batch.pk),
        ).first()
        self.assertIsNotNone(creation_entry)
        assert creation_entry is not None
        self.assertEqual(creation_entry.user, self.auditor)
        self.assertEqual(creation_entry.payload.get("status"), OfflineSyncBatch.Status.PENDING)
        self.assertEqual(creation_entry.payload.get("kind"), "data")

        batch.mark_applied({"status": "ok"}, status=200)

        applied_entry = AuditLogEntry.objects.filter(
            action=AuditLogEntry.Action.OFFLINE_BATCH_APPLIED,
            entity_id=str(batch.pk),
        ).first()
        self.assertIsNotNone(applied_entry)
        assert applied_entry is not None
        self.assertEqual(applied_entry.user, self.auditor)
        self.assertEqual(applied_entry.payload.get("status"), OfflineSyncBatch.Status.APPLIED)
        self.assertEqual(applied_entry.payload.get("response_status"), 200)
        self.assertEqual(applied_entry.payload.get("kind"), "data")

        error_batch = OfflineSyncBatch.objects.create(
            user=self.auditor,
            device_id="device-002",
            payload={"kind": "attachment"},
            payload_hash="hash-2",
        )

        error_batch.mark_error({"detail": "Checksum mismatch"}, status=400)

        error_entry = AuditLogEntry.objects.filter(
            action=AuditLogEntry.Action.OFFLINE_BATCH_ERROR,
            entity_id=str(error_batch.pk),
        ).first()
        self.assertIsNotNone(error_entry)
        assert error_entry is not None
        self.assertEqual(error_entry.user, self.auditor)
        self.assertEqual(error_entry.payload.get("status"), OfflineSyncBatch.Status.ERROR)
        self.assertEqual(error_entry.payload.get("response_status"), 400)
        self.assertEqual(error_entry.payload.get("kind"), "attachment")
        self.assertEqual(error_entry.payload.get("details", {}).get("detail"), "Checksum mismatch")
