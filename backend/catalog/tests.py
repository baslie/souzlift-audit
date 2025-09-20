"""Tests for moderation workflow of catalog records."""
from __future__ import annotations

from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile

from .admin import ChecklistSectionAdmin
from .models import (
    Building,
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    Elevator,
    ReviewStatus,
    ScoreOption,
)


class CatalogModerationTests(TestCase):
    """Covers moderation queue behaviour for buildings and elevators."""

    def setUp(self) -> None:
        self.UserModel = get_user_model()

        self.admin = self.UserModel.objects.create_user(
            username="admin",
            password="StrongPass123",
        )
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])

        self.auditor = self.UserModel.objects.create_user(
            username="auditor",
            password="StrongPass123",
        )
        self.other_auditor = self.UserModel.objects.create_user(
            username="other",
            password="StrongPass123",
        )

        self.building = Building.objects.create(
            address="Ленина, 1",
            created_by=self.auditor,
        )
        self.other_building = Building.objects.create(
            address="Победы, 15",
            created_by=self.other_auditor,
        )

    def test_approve_and_reject_update_metadata(self) -> None:
        """Approving and rejecting records updates review metadata."""

        self.building.approve(self.admin)
        self.building.refresh_from_db()
        self.assertEqual(self.building.review_status, ReviewStatus.APPROVED)
        self.assertEqual(self.building.verified_by, self.admin)
        self.assertIsNotNone(self.building.verified_at)

        # Simulate a short delay to ensure timestamp refresh on rejection.
        self.building.verified_at = timezone.now() - timedelta(minutes=5)
        self.building.save(update_fields=["verified_at"])

        self.building.reject(self.admin)
        self.building.refresh_from_db()
        self.assertEqual(self.building.review_status, ReviewStatus.REJECTED)
        self.assertEqual(self.building.verified_by, self.admin)
        self.assertGreaterEqual(self.building.verified_at, timezone.now() - timedelta(minutes=1))

    def test_send_to_review_resets_verification(self) -> None:
        """Returning a record to moderation clears reviewer data."""

        self.building.approve(self.admin)
        self.building.refresh_from_db()
        self.assertIsNotNone(self.building.verified_by)

        self.building.send_to_review()
        self.building.refresh_from_db()
        self.assertEqual(self.building.review_status, ReviewStatus.PENDING)
        self.assertIsNone(self.building.verified_by)
        self.assertIsNone(self.building.verified_at)

    def test_visible_for_user_filters_records(self) -> None:
        """Only approved or own records are visible to non-admin users."""

        approved_building = Building.objects.create(
            address="Советская, 22",
            created_by=self.other_auditor,
        )
        approved_building.approve(self.admin)

        invisible_building = Building.objects.create(
            address="Томская, 9",
            created_by=self.other_auditor,
        )

        auditor_queryset = Building.objects.visible_for_user(self.auditor)
        self.assertIn(self.building, auditor_queryset)
        self.assertIn(approved_building, auditor_queryset)
        self.assertNotIn(invisible_building, auditor_queryset)

        other_queryset = Building.objects.visible_for_user(self.other_auditor)
        self.assertIn(approved_building, other_queryset)
        self.assertIn(invisible_building, other_queryset)  # Creator sees own pending entry.
        self.assertNotIn(self.building, other_queryset)

        admin_queryset = Building.objects.visible_for_user(self.admin)
        self.assertIn(self.building, admin_queryset)
        self.assertIn(self.other_building, admin_queryset)
        self.assertIn(invisible_building, admin_queryset)

        anonymous_queryset = Building.objects.visible_for_user(AnonymousUser())
        self.assertIn(approved_building, anonymous_queryset)
        self.assertNotIn(self.building, anonymous_queryset)

    def test_moderation_queue_orders_by_creation(self) -> None:
        """Queue for moderation returns pending entries in chronological order."""

        Building.objects.create(address="Кирова, 3", created_by=self.auditor)
        queued = list(Building.objects.for_moderation())
        self.assertEqual(queued, sorted(queued, key=lambda obj: obj.created_at))

    def test_elevator_moderation_helpers(self) -> None:
        """Elevators share the same moderation behaviour as buildings."""

        reference_building = Building.objects.create(address="Гагарина, 7", created_by=self.admin)
        reference_building.approve(self.admin)

        elevator = Elevator.objects.create(
            building=reference_building,
            identifier="EL-001",
            created_by=self.auditor,
        )

        self.assertEqual(elevator.review_status, ReviewStatus.PENDING)
        Elevator.objects.visible_for_user(self.admin)  # Should not raise.

        elevator.approve(self.admin)
        elevator.refresh_from_db()
        self.assertEqual(elevator.review_status, ReviewStatus.APPROVED)

        elevator.send_to_review()
        elevator.refresh_from_db()
        self.assertEqual(elevator.review_status, ReviewStatus.PENDING)


class CatalogViewsTests(TestCase):
    """Covers user interface interactions for catalog views."""

    def setUp(self) -> None:
        self.UserModel = get_user_model()

        self.admin = self.UserModel.objects.create_user(username="admin", password="StrongPass123")
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])
        self.admin.profile.mark_password_changed()

        self.auditor = self.UserModel.objects.create_user(username="auditor", password="StrongPass123")
        self.auditor.profile.mark_password_changed()
        self.other_auditor = self.UserModel.objects.create_user(username="other", password="StrongPass123")
        self.other_auditor.profile.mark_password_changed()

    def test_auditor_can_create_building(self) -> None:
        self.client.force_login(self.auditor)
        response = self.client.post(
            reverse("catalog:building-create"),
            data={"address": "Советская, 5", "entrance": "2", "notes": "Тестовая запись"},
        )
        self.assertRedirects(response, reverse("catalog:building-list"))
        building = Building.objects.get(address="Советская, 5")
        self.assertEqual(building.created_by, self.auditor)
        self.assertEqual(building.review_status, ReviewStatus.PENDING)

    def test_admin_can_approve_building_from_list(self) -> None:
        target = Building.objects.create(address="Ленина, 8", created_by=self.auditor)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("catalog:building-moderate", args=[target.pk]),
            data={"action": "approve", "next": reverse("catalog:building-list")},
        )
        self.assertRedirects(response, reverse("catalog:building-list"))
        target.refresh_from_db()
        self.assertEqual(target.review_status, ReviewStatus.APPROVED)
        self.assertEqual(target.verified_by, self.admin)

    def test_status_filter_returns_pending_records(self) -> None:
        approved = Building.objects.create(address="Кирова, 3", created_by=self.admin)
        approved.approve(self.admin)
        pending = Building.objects.create(address="Томская, 4", created_by=self.auditor)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("catalog:building-list"), data={"status": ReviewStatus.PENDING})
        self.assertEqual(response.status_code, 200)
        object_list = list(response.context["object_list"])
        self.assertIn(pending, object_list)
        self.assertNotIn(approved, object_list)

    def test_auditor_cannot_edit_foreign_building(self) -> None:
        foreign_building = Building.objects.create(address="Университетская, 12", created_by=self.other_auditor)
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("catalog:building-update", args=[foreign_building.pk]))
        self.assertEqual(response.status_code, 403)

    def test_auditor_can_create_elevator_for_approved_building(self) -> None:
        approved_building = Building.objects.create(address="Гагарина, 7", created_by=self.admin)
        approved_building.approve(self.admin)

        self.client.force_login(self.auditor)
        response = self.client.post(
            reverse("catalog:elevator-create"),
            data={
                "building": approved_building.pk,
                "identifier": "EL-101",
                "status": Elevator.Status.IN_SERVICE,
                "description": "Пассажирский лифт",
            },
        )
        self.assertRedirects(response, reverse("catalog:elevator-list"))
        elevator = Elevator.objects.get(identifier="EL-101")
        self.assertEqual(elevator.created_by, self.auditor)
        self.assertEqual(elevator.review_status, ReviewStatus.PENDING)


class ChecklistValidationTests(TestCase):
    """Covers checklist validation rules and helpers."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.category = ChecklistCategory.objects.create(code="safety", name="Безопасность", order=1)
        cls.section = ChecklistSection.objects.create(
            category=cls.category,
            title="Общие требования",
            order=1,
        )

    def create_score_question(self, **overrides: object) -> ChecklistQuestion:
        defaults: dict[str, object] = {
            "section": self.section,
            "text": "Проверка состояния оборудования",
            "type": ChecklistQuestion.QuestionType.SCORE,
            "max_score": 5,
            "order": 1,
        }
        defaults.update(overrides)
        return ChecklistQuestion.objects.create(**defaults)

    def test_score_option_disallowed_for_non_score_question(self) -> None:
        question = ChecklistQuestion.objects.create(
            section=self.section,
            text="Нужен ли доступ к шахте?",
            type=ChecklistQuestion.QuestionType.BOOLEAN,
            max_score=0,
            order=2,
        )
        option = ScoreOption(question=question, score=1, description="Да", order=1)
        with self.assertRaises(ValidationError) as exc:
            option.full_clean()
        self.assertIn("question", exc.exception.error_dict)

    def test_score_option_cannot_exceed_max_score(self) -> None:
        question = self.create_score_question(max_score=4)
        option = ScoreOption(question=question, score=5, description="Отлично", order=1)
        with self.assertRaises(ValidationError) as exc:
            option.full_clean()
        self.assertIn("score", exc.exception.error_dict)

    def test_score_option_requires_positive_max_score(self) -> None:
        question = self.create_score_question(max_score=0)
        option = ScoreOption(question=question, score=1, description="Допуск", order=1)
        with self.assertRaises(ValidationError) as exc:
            option.full_clean()
        self.assertIn("score", exc.exception.error_dict)

    def test_score_option_validates_successfully(self) -> None:
        question = self.create_score_question(max_score=5)
        option = ScoreOption(question=question, score=5, description="Норматив выполнен", order=1)
        option.full_clean()  # Should not raise.

    def test_validate_answer_requires_known_score(self) -> None:
        question = self.create_score_question(max_score=3)
        ScoreOption.objects.create(question=question, score=3, description="Без замечаний", order=1)
        with self.assertRaises(ValidationError) as exc:
            question.validate_answer(score=2, comment="Требуется уточнение")
        self.assertIn("score", exc.exception.error_dict)

    def test_validate_answer_requires_comment_when_score_lower(self) -> None:
        question = self.create_score_question(max_score=5)
        ScoreOption.objects.create(question=question, score=5, description="Без замечаний", order=1)
        ScoreOption.objects.create(question=question, score=3, description="Есть замечания", order=2)
        with self.assertRaises(ValidationError) as exc:
            question.validate_answer(score=3, comment=" ")
        self.assertIn("comment", exc.exception.error_dict)
        question.validate_answer(score=3, comment="Обнаружены мелкие недочёты")

    def test_validate_answer_allows_max_score_without_comment(self) -> None:
        question = self.create_score_question(max_score=4)
        ScoreOption.objects.create(question=question, score=4, description="Отлично", order=1)
        question.validate_answer(score=4, comment="")

    def test_validate_answer_respects_requires_comment_flag(self) -> None:
        question = self.create_score_question(max_score=4, requires_comment=True)
        ScoreOption.objects.create(question=question, score=4, description="Отлично", order=1)
        with self.assertRaises(ValidationError) as exc:
            question.validate_answer(score=4, comment="")
        self.assertIn("comment", exc.exception.error_dict)
        question.validate_answer(score=4, comment="Комментарий добавлен")

    def test_validate_answer_for_non_score_question(self) -> None:
        question = ChecklistQuestion.objects.create(
            section=self.section,
            text="Опишите состояние машинного помещения",
            type=ChecklistQuestion.QuestionType.TEXT,
            max_score=0,
            order=3,
            requires_comment=True,
        )
        with self.assertRaises(ValidationError) as exc:
            question.validate_answer(score=None, comment=" ")
        self.assertIn("comment", exc.exception.error_dict)
        question.validate_answer(score=None, comment="Описание состояния")


class ChecklistAdminViewsTests(TestCase):
    """Покрывает пользовательский интерфейс конструктора чек-листа."""

    def setUp(self) -> None:
        self.UserModel = get_user_model()
        self.admin = self.UserModel.objects.create_user(username="admin", password="StrongPass123")
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.mark_password_changed()
        self.admin.profile.save(update_fields=["role", "password_changed_at"])

        self.auditor = self.UserModel.objects.create_user(username="auditor", password="StrongPass123")
        self.auditor.profile.mark_password_changed()
        self.auditor.profile.save(update_fields=["password_changed_at"])

    def test_overview_requires_admin_and_shows_preview(self) -> None:
        """Доступ ограничен ролью администратора, а предпросмотр содержит собранную структуру."""

        category = ChecklistCategory.objects.create(code="safety", name="Безопасность", order=0)
        section = ChecklistSection.objects.create(category=category, title="Общие требования", order=0)
        question = ChecklistQuestion.objects.create(
            section=section,
            text="Исправность оборудования",
            type=ChecklistQuestion.QuestionType.SCORE,
            max_score=5,
            order=0,
        )
        ScoreOption.objects.create(question=question, score=5, description="Норма", order=0)

        self.client.force_login(self.auditor)
        forbidden = self.client.get(reverse("catalog:checklist-overview"))
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("catalog:checklist-overview"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["category_count"], 1)
        self.assertEqual(response.context["section_count"], 1)
        self.assertEqual(response.context["question_count"], 1)
        preview = response.context["checklist_preview"]
        self.assertEqual(preview["total_questions"], 1)
        self.assertIn("generated_at", preview)
        self.assertIn("preview_generated_at", response.context)

    def test_overview_redirects_anonymous_user(self) -> None:
        """Неаутентифицированные пользователи перенаправляются на страницу входа."""

        response = self.client.get(reverse("catalog:checklist-overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.headers.get("Location", ""))

    def test_auditor_cannot_access_admin_forms(self) -> None:
        """Аудитор получает 403 при попытке открыть формы конструктора чек-листа."""

        self.client.force_login(self.auditor)

        create_url = reverse("catalog:checklist-category-create")
        response_get = self.client.get(create_url)
        self.assertEqual(response_get.status_code, 403)

        response_post = self.client.post(create_url, {"code": "ops", "name": "Операции", "order": 0})
        self.assertEqual(response_post.status_code, 403)
        self.assertEqual(ChecklistCategory.objects.count(), 0)

    def test_admin_can_create_nested_entities(self) -> None:
        """Через формы можно создать полный набор элементов чек-листа."""

        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("catalog:checklist-category-create"),
            data={"code": "main", "name": "Основная", "order": 0},
        )
        self.assertRedirects(response, reverse("catalog:checklist-overview"))
        category = ChecklistCategory.objects.get(code="main")
        self.assertEqual(category.order, 0)

        response = self.client.post(
            reverse("catalog:checklist-category-create"),
            data={"code": "safety", "name": "Безопасность", "order": 0},
        )
        self.assertRedirects(response, reverse("catalog:checklist-overview"))
        other_category = ChecklistCategory.objects.get(code="safety")
        self.assertGreater(other_category.order, category.order)

        response = self.client.post(
            reverse("catalog:checklist-section-create", args=[category.pk]),
            data={
                "category": category.pk,
                "title": "Инспекция",
                "description": "Базовые проверки",
                "order": 0,
            },
        )
        self.assertRedirects(response, reverse("catalog:checklist-overview"))
        section = category.sections.get(title="Инспекция")

        response = self.client.post(
            reverse("catalog:checklist-question-create", args=[section.pk]),
            data={
                "section": section.pk,
                "text": "Проверка механики",
                "type": ChecklistQuestion.QuestionType.SCORE,
                "max_score": 5,
                "guideline": "",
                "requires_comment": "",
                "order": 0,
            },
        )
        self.assertRedirects(response, reverse("catalog:checklist-overview"))
        question = section.questions.get(text="Проверка механики")

        response = self.client.post(
            reverse("catalog:checklist-option-create", args=[question.pk]),
            data={
                "question": question.pk,
                "score": 5,
                "description": "Соответствует требованиям",
                "order": 0,
            },
        )
        self.assertRedirects(response, reverse("catalog:checklist-overview"))
        option = question.score_options.get(score=5)
        self.assertEqual(option.description, "Соответствует требованиям")

    def test_reorder_questions_swaps_positions(self) -> None:
        """Перемещение вопросов обновляет порядок внутри секции."""

        category = ChecklistCategory.objects.create(code="main", name="Основная", order=0)
        section = ChecklistSection.objects.create(category=category, title="Секция", order=0)
        first = ChecklistQuestion.objects.create(
            section=section,
            text="Первый",
            type=ChecklistQuestion.QuestionType.SCORE,
            max_score=5,
            order=0,
        )
        second = ChecklistQuestion.objects.create(
            section=section,
            text="Второй",
            type=ChecklistQuestion.QuestionType.SCORE,
            max_score=5,
            order=1,
        )

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("catalog:checklist-question-move", args=[second.pk]),
            data={"direction": "up", "next": reverse("catalog:checklist-overview")},
        )
        self.assertRedirects(response, reverse("catalog:checklist-overview"))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.order, 1)
        self.assertEqual(second.order, 0)

class ChecklistAdminActionsTests(TestCase):
    """Covers helper actions in the checklist admin interface."""

    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.UserModel = get_user_model()

        self.admin_user = self.UserModel.objects.create_user(
            username="admin", password="StrongPass123"
        )
        self.admin_user.is_staff = True
        self.admin_user.is_superuser = True
        self.admin_user.save(update_fields=["is_staff", "is_superuser"])
        self.admin_user.profile.role = UserProfile.Roles.ADMIN
        self.admin_user.profile.mark_password_changed()
        self.admin_user.profile.save(update_fields=["role", "password_changed_at"])

        self.category_a = ChecklistCategory.objects.create(
            code="cat-a", name="Категория A", order=1
        )
        self.category_b = ChecklistCategory.objects.create(
            code="cat-b", name="Категория B", order=2
        )
        self.section_first = ChecklistSection.objects.create(
            category=self.category_a,
            title="Секция 1",
            order=1,
        )
        self.section_second = ChecklistSection.objects.create(
            category=self.category_a,
            title="Секция 2",
            order=2,
        )
        self.section_existing_target = ChecklistSection.objects.create(
            category=self.category_b,
            title="Секция в B",
            order=1,
        )

    def test_move_sections_action_appends_to_target_category(self) -> None:
        """Selected sections are appended to the destination keeping their order."""

        request = self.factory.post(
            "/admin/catalog/checklistsection/",
            data={"target_category": str(self.category_b.pk)},
        )
        request.user = self.admin_user

        admin_instance = ChecklistSectionAdmin(ChecklistSection, admin.site)
        admin_instance.message_user = lambda *args, **kwargs: None  # type: ignore[assignment]

        queryset = ChecklistSection.objects.filter(
            pk__in=[self.section_first.pk, self.section_second.pk]
        )
        admin_instance.move_to_category(request, queryset)

        self.section_first.refresh_from_db()
        self.section_second.refresh_from_db()
        self.section_existing_target.refresh_from_db()

        self.assertEqual(self.section_first.category, self.category_b)
        self.assertEqual(self.section_second.category, self.category_b)
        self.assertEqual(self.section_first.order, 2)
        self.assertEqual(self.section_second.order, 3)
        ordered_titles = list(
            self.category_b.sections.order_by("order").values_list("title", flat=True)
        )
        self.assertEqual(
            ordered_titles,
            [
                self.section_existing_target.title,
                self.section_first.title,
                self.section_second.title,
            ],
        )
