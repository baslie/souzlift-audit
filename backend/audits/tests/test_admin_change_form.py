"""Tests covering the Django admin change form for audits."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from audits.models import Audit, AuditAttachment, AuditResponse
from catalog.models import (
    Building,
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    Elevator,
    ObjectInfoField,
)

from .test_attachment_access import ProtectedMediaTestCase, SMALL_GIF


class AuditAdminChangeFormTests(ProtectedMediaTestCase):
    """Ensure the change form presents object info, checklist and attachments."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.admin = UserModel.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="StrongPass123",
        )
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        self.client.force_login(self.admin)

        self.building = Building.objects.create(address="Ленина, 5", created_by=self.admin)
        self.elevator = Elevator.objects.create(
            building=self.building,
            identifier="EL-100",
            created_by=self.admin,
        )

        ObjectInfoField.objects.create(
            code="manager",
            label="Ответственный",
            field_type=ObjectInfoField.FieldType.TEXT,
            order=1,
        )
        ObjectInfoField.objects.create(
            code="capacity",
            label="Вместимость",
            field_type=ObjectInfoField.FieldType.NUMBER,
            order=2,
        )

        category = ChecklistCategory.objects.create(code="safety", name="Безопасность", order=1)
        section = ChecklistSection.objects.create(category=category, title="Общие вопросы", order=1)
        self.score_question = ChecklistQuestion.objects.create(
            section=section,
            text="Состояние дверей",
            max_score=5,
            order=1,
        )
        self.boolean_question = ChecklistQuestion.objects.create(
            section=section,
            text="Система связи работает",
            type=ChecklistQuestion.QuestionType.BOOLEAN,
            order=2,
        )
        self.text_question = ChecklistQuestion.objects.create(
            section=section,
            text="Дополнительные замечания",
            type=ChecklistQuestion.QuestionType.TEXT,
            order=3,
        )

        today = timezone.localdate()
        self.audit = Audit.objects.create(
            elevator=self.elevator,
            created_by=self.admin,
            planned_date=today,
            object_info={
                "manager": "Иван Иванов",
                "capacity": 8,
                "extra_note": "Внешняя заметка",
            },
        )
        self.audit.start(actor=self.admin)
        self.audit.submit(actor=self.admin)

        self.score_response = AuditResponse.objects.create(
            audit=self.audit,
            question=self.score_question,
            score=4,
            comment="Необходимо отрегулировать двери.",
        )
        self.boolean_response = AuditResponse.objects.create(
            audit=self.audit,
            question=self.boolean_question,
            score=1,
            is_flagged=True,
            is_offline_cached=True,
        )
        self.text_response = AuditResponse.objects.create(
            audit=self.audit,
            question=self.text_question,
            comment="Описание состояния площадки",
        )

        AuditAttachment.objects.create(
            response=self.score_response,
            file=SimpleUploadedFile("door.gif", SMALL_GIF, content_type="image/gif"),
            caption="Фото двери",
        )

    def test_change_form_context_contains_checklist_and_object_info(self) -> None:
        """The change form should expose detailed context for rendering the audit."""

        url = reverse("admin:audits_audit_change", args=[self.audit.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        object_info = response.context["audit_object_info"]
        self.assertTrue(response.context["audit_object_info_has_values"])
        self.assertEqual([item["code"] for item in object_info[:2]], ["manager", "capacity"])
        extra_item = next(item for item in object_info if item["code"] == "extra_note")
        self.assertTrue(extra_item["is_extra"])
        self.assertEqual(extra_item["value"], "Внешняя заметка")

        summary = response.context["audit_summary"]
        self.assertEqual(summary["total_questions"], 3)
        self.assertEqual(summary["answered_questions"], 3)
        self.assertEqual(summary["attachments_total"], 1)
        self.assertEqual(summary["comments_total"], 2)
        self.assertEqual(summary["flagged_total"], 1)
        self.assertEqual(summary["unanswered_questions"], 0)

        allowed = response.context["audit_allowed_fields"]
        self.assertIn("status", [entry["name"] for entry in allowed])

        checklist = response.context["audit_checklist"]
        self.assertEqual(len(checklist), 1)
        section = checklist[0]["sections"][0]
        questions = {entry["id"]: entry for entry in section["questions"]}

        score_entry = questions[self.score_question.id]
        self.assertEqual(score_entry["value_display"], "4 из 5")
        self.assertTrue(score_entry["has_comment"])
        self.assertEqual(len(score_entry["attachments"]), 1)

        boolean_entry = questions[self.boolean_question.id]
        self.assertEqual(boolean_entry["value_display"], "Да")
        self.assertTrue(boolean_entry["is_flagged"])
        self.assertTrue(boolean_entry["is_offline"])

        text_entry = questions[self.text_question.id]
        self.assertEqual(text_entry["answer_display"], "Описание состояния площадки")
        self.assertEqual(text_entry["value_display"], "Описание состояния площадки")

        self.assertTrue(response.context["audit_responses_present"])
