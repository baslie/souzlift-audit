from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command

from accounts.models import UserProfile
from audits.models import Audit, AuditAttachment, AuditResponse
from audits.tests.test_attachment_access import ProtectedMediaTestCase, SMALL_GIF
from catalog.models import (
    Building,
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    Elevator,
)


class CheckAttachmentsCommandTests(ProtectedMediaTestCase):
    """Проверки для management-команды контроля вложений."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.admin = UserModel.objects.create_user(username="admin", password="StrongPass123")
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        category = ChecklistCategory.objects.create(code="safety", name="Безопасность", order=1)
        section = ChecklistSection.objects.create(category=category, title="Общие вопросы", order=1)
        question = ChecklistQuestion.objects.create(section=section, text="Исправность", order=1)

        building = Building.objects.create(address="Советская, 1", created_by=self.admin)
        elevator = Elevator.objects.create(building=building, identifier="EL-1", created_by=self.admin)
        audit = Audit.objects.create(elevator=elevator, created_by=self.admin)
        self.response = AuditResponse.objects.create(audit=audit, question=question, score=5)

    def tearDown(self) -> None:
        root = Path(self._override.options["PROTECTED_MEDIA_ROOT"])
        if root.exists():
            for item in root.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        super().tearDown()

    def test_command_reports_success_without_issues(self) -> None:
        """Команда завершается успешно, если все файлы на месте."""

        AuditAttachment.objects.create(
            response=self.response,
            file=SimpleUploadedFile("photo.gif", SMALL_GIF, content_type="image/gif"),
        )

        stdout = StringIO()
        stderr = StringIO()
        call_command("check_attachments_integrity", stdout=stdout, stderr=stderr)

        self.assertIn("Все вложения соответствуют базе данных.", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_command_detects_problems_and_can_fix_sizes_and_orphans(self) -> None:
        """Команда сообщает об ошибках и может исправить размеры и удалить осиротевшие файлы."""

        attachment_ok = AuditAttachment.objects.create(
            response=self.response,
            file=SimpleUploadedFile("photo1.gif", SMALL_GIF, content_type="image/gif"),
        )
        attachment_missing = AuditAttachment.objects.create(
            response=self.response,
            file=SimpleUploadedFile("photo2.gif", SMALL_GIF, content_type="image/gif"),
        )
        attachment_mismatch = AuditAttachment.objects.create(
            response=self.response,
            file=SimpleUploadedFile("photo3.gif", SMALL_GIF, content_type="image/gif"),
        )

        # Удаляем файл, чтобы получить отсутствие на диске.
        Path(attachment_missing.file.path).unlink()

        # Искажаем размер напрямую через ORM, чтобы не задействовать clean/save.
        AuditAttachment.objects.filter(pk=attachment_mismatch.pk).update(stored_size=1)

        # Создаём осиротевший файл в защищённом каталоге.
        orphan_path = Path(self._override.options["PROTECTED_MEDIA_ROOT"]) / "audits" / "orphan.gif"
        orphan_path.parent.mkdir(parents=True, exist_ok=True)
        orphan_path.write_bytes(b"orphan")

        stdout = StringIO()
        stderr = StringIO()
        with self.assertRaises(CommandError):
            call_command("check_attachments_integrity", stdout=stdout, stderr=stderr)

        error_output = stderr.getvalue()
        self.assertIn("Отсутствует", error_output)
        self.assertIn("несоответствий размеров", error_output)
        self.assertIn("осиротевших файлов", error_output)

        stdout = StringIO()
        stderr = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "check_attachments_integrity",
                "--fix-sizes",
                "--delete-orphans",
                stdout=stdout,
                stderr=stderr,
            )

        attachment_mismatch.refresh_from_db()
        self.assertEqual(attachment_mismatch.stored_size, attachment_ok.stored_size)
        self.assertFalse(orphan_path.exists())
        self.assertIn("Исправлено записей", stdout.getvalue())
        self.assertIn("Удалено осиротевших файлов", stdout.getvalue())
