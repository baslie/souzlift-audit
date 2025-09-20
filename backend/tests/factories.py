"""Factory Boy definitions for the core project models."""
from __future__ import annotations

import uuid
from typing import Any

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import UserProfile
from audits import models as audits_models
from catalog import models as catalog_models

DEFAULT_USER_PASSWORD = "Password123!"


class UserFactory(factory.django.DjangoModelFactory):
    """Базовый пользователь системы с автоматически созданным профилем."""

    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")
    first_name = factory.Sequence(lambda n: f"Name{n}")
    last_name = factory.Sequence(lambda n: f"Surname{n}")
    is_active = True
    password = factory.PostGenerationMethodCall("set_password", DEFAULT_USER_PASSWORD)

    @factory.post_generation
    def profile(self, create: bool, extracted: dict[str, Any] | None, **kwargs: Any) -> None:
        """Обновляет связанный профиль при необходимости."""

        if not create:
            return

        profile = self.profile
        updates: dict[str, Any] = {}
        if extracted:
            updates.update(extracted)
        if kwargs:
            updates.update(kwargs)

        if updates:
            for field, value in updates.items():
                setattr(profile, field, value)
            profile.save(update_fields=sorted(updates.keys()))


class AuditorUserFactory(UserFactory):
    """Пользователь-аудитор (роль по умолчанию)."""

    profile__role = UserProfile.Roles.AUDITOR


class AdminUserFactory(UserFactory):
    """Администратор с расширенными правами."""

    is_staff = True
    is_superuser = True
    profile__role = UserProfile.Roles.ADMIN


class BuildingFactory(factory.django.DjangoModelFactory):
    """Здание из справочника."""

    class Meta:
        model = catalog_models.Building

    address = factory.Sequence(lambda n: f"Тестовая улица, {n + 1}")
    entrance = factory.Sequence(lambda n: str((n % 3) + 1))
    notes = factory.Sequence(lambda n: f"Примечание {n}")
    created_by = factory.SubFactory(AdminUserFactory)
    verified_by = factory.SelfAttribute("created_by")
    verified_at = factory.LazyFunction(timezone.now)
    review_status = catalog_models.ReviewStatus.APPROVED


class ElevatorFactory(factory.django.DjangoModelFactory):
    """Лифт, связанный со зданием."""

    class Meta:
        model = catalog_models.Elevator

    building = factory.SubFactory(BuildingFactory)
    identifier = factory.Sequence(lambda n: f"EL-{n:03d}")
    description = factory.Sequence(lambda n: f"Описание лифта {n}")
    status = catalog_models.Elevator.Status.IN_SERVICE
    created_by = factory.LazyAttribute(lambda obj: obj.building.created_by)
    verified_by = factory.LazyAttribute(lambda obj: obj.building.verified_by)
    verified_at = factory.LazyFunction(timezone.now)
    review_status = catalog_models.ReviewStatus.APPROVED


class ChecklistCategoryFactory(factory.django.DjangoModelFactory):
    """Категория чек-листа."""

    class Meta:
        model = catalog_models.ChecklistCategory

    code = factory.Sequence(lambda n: f"category-{n}")
    name = factory.Sequence(lambda n: f"Категория {n}")
    order = factory.Sequence(lambda n: n)


class ChecklistSectionFactory(factory.django.DjangoModelFactory):
    """Секция внутри категории чек-листа."""

    class Meta:
        model = catalog_models.ChecklistSection

    category = factory.SubFactory(ChecklistCategoryFactory)
    title = factory.Sequence(lambda n: f"Секция {n}")
    description = ""
    order = factory.Sequence(lambda n: n)


class ChecklistQuestionFactory(factory.django.DjangoModelFactory):
    """Вопрос чек-листа."""

    class Meta:
        model = catalog_models.ChecklistQuestion

    section = factory.SubFactory(ChecklistSectionFactory)
    text = factory.Sequence(lambda n: f"Вопрос {n}")
    type = catalog_models.ChecklistQuestion.QuestionType.SCORE
    max_score = 5
    order = factory.Sequence(lambda n: n)
    guideline = ""
    requires_comment = False

    @factory.post_generation
    def default_score_options(self, create: bool, extracted: Any, **_: Any) -> None:
        """Создаёт базовые варианты оценок, если явно не переданы."""

        if not create:
            return

        if extracted is None:
            ScoreOptionFactory(question=self, score=self.max_score, order=1)
        elif isinstance(extracted, (list, tuple)):
            for index, option_score in enumerate(extracted, start=1):
                ScoreOptionFactory(
                    question=self,
                    score=int(option_score),
                    order=index,
                )


class ScoreOptionFactory(factory.django.DjangoModelFactory):
    """Вариант ответа для балльного вопроса."""

    class Meta:
        model = catalog_models.ScoreOption

    question = factory.SubFactory(ChecklistQuestionFactory)
    order = factory.Sequence(lambda n: n + 1)
    score = factory.Sequence(lambda n: n + 1)
    description = factory.LazyAttribute(lambda obj: f"Баллы {obj.score}")

    @factory.post_generation
    def sync_question_max_score(self, create: bool, extracted: Any, **_: Any) -> None:
        if not create:
            return
        question = self.question
        if question.max_score < self.score:
            question.max_score = self.score
            question.save(update_fields=["max_score"])


class ObjectInfoFieldFactory(factory.django.DjangoModelFactory):
    """Поле информационной карточки объекта."""

    class Meta:
        model = catalog_models.ObjectInfoField

    code = factory.Sequence(lambda n: f"field_{n}")
    label = factory.Sequence(lambda n: f"Поле {n}")
    field_type = catalog_models.ObjectInfoField.FieldType.TEXT
    is_required = False
    order = factory.Sequence(lambda n: n)
    choices = ""


class AuditFactory(factory.django.DjangoModelFactory):
    """Аудит, созданный аудитором."""

    class Meta:
        model = audits_models.Audit

    elevator = factory.SubFactory(ElevatorFactory)
    created_by = factory.SubFactory(AuditorUserFactory)
    planned_date = None
    started_at = None
    finished_at = None
    status = audits_models.Audit.Status.DRAFT
    total_score = 0

    @factory.post_generation
    def object_info(self, create: bool, extracted: dict[str, Any] | None, **_: Any) -> None:
        if not create or not extracted:
            return
        self.object_info = dict(extracted)
        self.save(update_fields=["object_info"])


class AuditResponseFactory(factory.django.DjangoModelFactory):
    """Ответ аудитора на вопрос чек-листа."""

    class Meta:
        model = audits_models.AuditResponse

    audit = factory.SubFactory(AuditFactory)
    question = factory.SubFactory(ChecklistQuestionFactory)
    score = factory.LazyAttribute(
        lambda obj: (
            obj.question.max_score
            if obj.question.type == catalog_models.ChecklistQuestion.QuestionType.SCORE
            else None
        )
    )
    comment = factory.LazyAttribute(
        lambda obj: (
            "Комментарий"
            if obj.question.requires_comment_for_score(obj.score)
            else ""
        )
    )
    is_flagged = False
    is_offline_cached = False

    @factory.post_generation
    def ensure_score_option(self, create: bool, extracted: Any, **_: Any) -> None:
        if not create:
            return
        if self.score is None:
            return
        question = self.question
        if question.type != catalog_models.ChecklistQuestion.QuestionType.SCORE:
            return
        if not question.score_options.filter(score=self.score).exists():
            ScoreOptionFactory(question=question, score=self.score)


class AuditAttachmentFactory(factory.django.DjangoModelFactory):
    """Вложение, прикреплённое к ответу."""

    class Meta:
        model = audits_models.AuditAttachment

    response = factory.SubFactory(AuditResponseFactory)
    caption = factory.Sequence(lambda n: f"Вложение {n}")
    file = factory.django.ImageField(
        filename="attachment.jpg",
        color="blue",
        width=1,
        height=1,
    )


class AuditSignatureFactory(factory.django.DjangoModelFactory):
    """Цифровая подпись завершённого аудита."""

    class Meta:
        model = audits_models.AuditSignature

    audit = factory.SubFactory(AuditFactory)
    signed_by = factory.Sequence(lambda n: f"Ответственный {n}")
    signature_image = factory.django.ImageField(
        filename="signature.png",
        color="green",
        width=2,
        height=1,
    )
    signed_at = factory.LazyFunction(timezone.now)


class AuditLogEntryFactory(factory.django.DjangoModelFactory):
    """Запись журнала действий."""

    class Meta:
        model = audits_models.AuditLogEntry

    user = factory.SubFactory(AdminUserFactory)
    action = audits_models.AuditLogEntry.Action.AUDIT_CREATED
    entity_type = factory.Sequence(lambda n: f"audits.audit#{n}")
    entity_id = factory.Sequence(lambda n: str(n + 1))
    payload = {}


class OfflineSyncBatchFactory(factory.django.DjangoModelFactory):
    """Пакет офлайн-синхронизации."""

    class Meta:
        model = audits_models.OfflineSyncBatch

    user = factory.SubFactory(AuditorUserFactory)
    device_id = factory.Sequence(lambda n: f"device-{n}")
    payload = factory.LazyFunction(lambda: {"kind": "test", "items": []})
    payload_hash = factory.LazyFunction(lambda: uuid.uuid4().hex)
    status = audits_models.OfflineSyncBatch.Status.PENDING
    error_details = factory.LazyFunction(dict)
    response_payload = factory.LazyFunction(dict)
    response_status = 0
