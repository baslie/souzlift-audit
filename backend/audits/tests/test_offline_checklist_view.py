from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from audits.models import AttachmentLimits
from catalog.models import (
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    ScoreOption,
)


class OfflineChecklistViewTests(TestCase):
    """Integration tests for the offline checklist view."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.auditor = UserModel.objects.create_user(username="auditor", password="Secret123!")
        self.auditor.profile.mark_password_changed()

        self.other_user = UserModel.objects.create_user(username="other", password="Secret123!")
        self.other_user.profile.role = "MANAGER"
        self.other_user.profile.mark_password_changed()
        self.other_user.profile.save(update_fields=["role", "password_changed_at"])

        self.url = reverse("audits:offline-checklist")

        self.category = ChecklistCategory.objects.create(code="safety", name="Безопасность", order=1)
        self.section = ChecklistSection.objects.create(
            category=self.category,
            title="Общие требования",
            description="Проверка основных показателей безопасности.",
            order=1,
        )

        self.score_question = ChecklistQuestion.objects.create(
            section=self.section,
            text="Состояние машинного помещения",
            type=ChecklistQuestion.QuestionType.SCORE,
            max_score=5,
            order=1,
            requires_comment=False,
        )
        ScoreOption.objects.create(question=self.score_question, score=5, description="Соответствует нормативам", order=1)
        ScoreOption.objects.create(question=self.score_question, score=3, description="Есть замечания", order=2)

        self.text_question = ChecklistQuestion.objects.create(
            section=self.section,
            text="Дополнительные комментарии",
            type=ChecklistQuestion.QuestionType.TEXT,
            max_score=0,
            order=2,
            requires_comment=True,
        )

    def test_requires_authentication(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.headers.get("Location", ""))

    def test_denies_user_without_allowed_role(self) -> None:
        self.client.force_login(self.other_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_renders_checklist_structure_for_auditor(self) -> None:
        self.client.force_login(self.auditor)
        response = self.client.get(self.url, {"client_id": "draft-42"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "audits/offline_checklist.html")

        context = response.context
        self.assertEqual(context["client_id"], "draft-42")

        attachment_limits = context["attachment_limits"]
        self.assertIsInstance(attachment_limits, AttachmentLimits)
        self.assertGreater(attachment_limits.max_per_audit, 0)

        max_size_mb = context["max_attachment_size_mb"]
        expected_mb = attachment_limits.max_size_bytes / (1024 * 1024)
        self.assertAlmostEqual(max_size_mb, expected_mb)

        checklist = context["checklist"]
        self.assertEqual(checklist["total_sections"], 1)
        self.assertEqual(checklist["total_questions"], 2)
        self.assertIn("generated_at", checklist)

        categories = checklist["categories"]
        self.assertEqual(len(categories), 1)
        first_category = categories[0]
        self.assertEqual(first_category["code"], "safety")
        self.assertEqual(len(first_category["sections"]), 1)

        first_section = first_category["sections"][0]
        self.assertEqual(first_section["title"], "Общие требования")
        self.assertEqual(len(first_section["questions"]), 2)

        serialized_score_question = first_section["questions"][0]
        self.assertEqual(serialized_score_question["type"], ChecklistQuestion.QuestionType.SCORE)
        self.assertTrue(serialized_score_question["requires_comment_on_reduced_score"])
        self.assertEqual(len(serialized_score_question["score_options"]), 2)

        serialized_text_question = first_section["questions"][1]
        self.assertEqual(serialized_text_question["type"], ChecklistQuestion.QuestionType.TEXT)
        self.assertTrue(serialized_text_question["requires_comment"])
