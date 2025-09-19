from __future__ import annotations

import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.signing import BadSignature
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from accounts.models import UserProfile
from audits.models import Audit, AuditAttachment, AuditResponse
from audits.storages import protected_media_storage, reset_protected_media_storage
from audits.tokens import build_attachment_token, read_attachment_token
from catalog.models import (
    Building,
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    Elevator,
)

SMALL_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00"
    b"\x01\x00\x00\x02\x02D\x01\x00;"
)


class ProtectedMediaTestCase(TestCase):
    """Base test case that isolates protected media storage per test class."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._tempdir = tempfile.mkdtemp(prefix="protected-media-")
        cls._override = override_settings(PROTECTED_MEDIA_ROOT=cls._tempdir)
        cls._override.enable()
        reset_protected_media_storage()

    @classmethod
    def tearDownClass(cls) -> None:
        reset_protected_media_storage()
        cls._override.disable()
        shutil.rmtree(cls._tempdir, ignore_errors=True)
        super().tearDownClass()


class AttachmentTokenTests(TestCase):
    """Ensure attachment tokens are correctly signed and validated."""

    def test_token_roundtrip(self) -> None:
        token = build_attachment_token(42)
        self.assertEqual(read_attachment_token(token), 42)

    def test_modified_token_is_rejected(self) -> None:
        token = build_attachment_token(7)
        with self.assertRaises(BadSignature):
            read_attachment_token(token + "tamper")


class AttachmentStorageTests(ProtectedMediaTestCase):
    """Validate behaviour of the protected storage backend."""

    def test_storage_does_not_expose_public_url(self) -> None:
        with self.assertRaises(NotImplementedError):
            protected_media_storage.url("audits/sample.jpg")


class AttachmentDownloadViewTests(ProtectedMediaTestCase):
    """Integration tests for secure download of audit attachments."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.admin = UserModel.objects.create_user(username="admin", password="StrongPass123")
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        self.auditor = UserModel.objects.create_user(username="auditor", password="StrongPass123")
        self.auditor.profile.mark_password_changed()

        self.other_auditor = UserModel.objects.create_user(username="other", password="StrongPass123")
        self.other_auditor.profile.mark_password_changed()

        self.building = Building.objects.create(address="Советская, 1", created_by=self.admin)
        self.elevator = Elevator.objects.create(
            building=self.building,
            identifier="EL-1",
            created_by=self.admin,
        )

        category = ChecklistCategory.objects.create(code="safety", name="Безопасность", order=1)
        section = ChecklistSection.objects.create(category=category, title="Общие вопросы", order=1)
        question = ChecklistQuestion.objects.create(section=section, text="Исправность", order=1)

        self.audit = Audit.objects.create(elevator=self.elevator, created_by=self.auditor)
        self.response = AuditResponse.objects.create(audit=self.audit, question=question, score=5)
        self.attachment = AuditAttachment.objects.create(
            response=self.response,
            file=SimpleUploadedFile("photo.gif", SMALL_GIF, content_type="image/gif"),
            caption="Фото",
        )

    def test_auditor_downloads_own_attachment(self) -> None:
        self.client.force_login(self.auditor)
        url = self.attachment.get_download_url()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Type"), "image/gif")
        self.assertGreater(sum(len(chunk) for chunk in response.streaming_content), 0)

    def test_admin_can_download_any_attachment(self) -> None:
        self.client.force_login(self.admin)
        url = self.attachment.get_download_url()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_other_auditor_gets_not_found(self) -> None:
        self.client.force_login(self.other_auditor)
        url = self.attachment.get_download_url()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_anonymous_user_redirects_to_login(self) -> None:
        url = self.attachment.get_download_url()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.headers.get("Location", ""))

    def test_invalid_token_returns_not_found(self) -> None:
        self.client.force_login(self.admin)
        url = reverse("audits:attachment-download", kwargs={"token": "invalid"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
