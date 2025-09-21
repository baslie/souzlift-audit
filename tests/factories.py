"""Factory Boy fixtures for simplified architecture."""
from __future__ import annotations

from datetime import date

import factory
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.utils import timezone

from accounts.models import UserProfile
from audits.models import Audit, AuditAttachment, AuditResponse
from catalog.models import Building, Elevator, ReviewStatus
from checklists.models import ChecklistItem, ChecklistTemplate

DEFAULT_USER_PASSWORD = "test-password"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)
        skip_postgeneration_save = True

    class Params:
        raw_password = DEFAULT_USER_PASSWORD

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")
    password = factory.LazyAttribute(lambda obj: make_password(obj.raw_password))
    is_staff = False
    is_superuser = False

    @factory.post_generation
    def ensure_profile(self, create, extracted, **kwargs):  # pragma: no cover - side effect
        if not create:
            return
        # Signals create the profile automatically; ensure default role is applied.
        profile = self.profile
        updates: list[str] = []
        if not profile.full_name:
            profile.full_name = f"{self.username.title()}"  # type: ignore[assignment]
            updates.append("full_name")
        if profile.password_changed_at is None:
            profile.password_changed_at = timezone.now()
            updates.append("password_changed_at")
        if updates:
            profile.save(update_fields=updates)


class AuditorUserFactory(UserFactory):
    class Meta:
        model = get_user_model()
        skip_postgeneration_save = True

    @factory.post_generation
    def make_auditor(self, create, extracted, **kwargs):  # pragma: no cover - side effect
        if not create:
            return
        profile = self.profile
        profile.role = UserProfile.Roles.AUDITOR
        profile.save(update_fields=["role"])


class AdminUserFactory(UserFactory):
    class Meta:
        model = get_user_model()
        skip_postgeneration_save = True

    is_staff = True
    is_superuser = True

    @factory.post_generation
    def make_admin(self, create, extracted, **kwargs):  # pragma: no cover - side effect
        if not create:
            return
        profile = self.profile
        profile.role = UserProfile.Roles.ADMIN
        profile.save(update_fields=["role"])


class BuildingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Building

    address = factory.Sequence(lambda n: f"Ленина, {n}")
    entrance = "1"
    notes = ""
    created_by = factory.SubFactory(AdminUserFactory)
    review_status = ReviewStatus.APPROVED


class ElevatorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Elevator

    building = factory.SubFactory(BuildingFactory)
    identifier = factory.Sequence(lambda n: f"EL-{n:03d}")
    status = Elevator.Status.IN_SERVICE
    description = ""
    created_by = factory.SelfAttribute("building.created_by")
    review_status = ReviewStatus.APPROVED


class ChecklistTemplateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChecklistTemplate
        skip_postgeneration_save = True

    name = factory.Sequence(lambda n: f"Стандартный чек-лист {n}")
    description = "Проверка технического состояния."
    is_active = True

    @factory.post_generation
    def published(self, create, extracted, **kwargs):  # pragma: no cover - side effect
        if not create:
            return
        if extracted:
            self.publish(commit=True)


class ChecklistItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChecklistItem
        skip_postgeneration_save = True

    template = factory.SubFactory(ChecklistTemplateFactory)
    area = "Техническая"
    category = "Безопасность"
    question = factory.Sequence(lambda n: f"Проверка элемента №{n}")
    help_text = ""
    score_type = ChecklistItem.ScoreType.NUMERIC
    min_score = 0
    max_score = 5
    step = 1
    requires_comment = False
    weight = 1

    @factory.lazy_attribute
    def order(self) -> int:
        template = self.template
        if template.pk:
            last_order = (
                template.items.order_by("-order").values_list("order", flat=True).first()
            )
            return int(last_order or 0) + 1
        return 1

    @classmethod
    def _build(cls, model_class, *args, **kwargs):
        template = kwargs.get("template")
        if template is None:
            template = ChecklistTemplateFactory()
            kwargs["template"] = template
        elif template.pk is None:
            template.save()
        return super()._build(model_class, *args, **kwargs)


class AuditFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Audit

    building = factory.SubFactory(BuildingFactory)
    elevator = factory.SubFactory(ElevatorFactory, building=factory.SelfAttribute("..building"))
    template = factory.SubFactory(ChecklistTemplateFactory)
    assigned_to = factory.SubFactory(AuditorUserFactory)
    status = Audit.Status.DRAFT
    deadline = factory.LazyFunction(lambda: date.today())


class AuditResponseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditResponse

    audit = factory.SubFactory(AuditFactory)
    item = factory.SubFactory(ChecklistItemFactory, template=factory.SelfAttribute("..audit.template"))
    numeric_answer = 3
    comment = ""


class AuditAttachmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditAttachment

    audit = factory.SubFactory(AuditFactory)
    response = factory.SubFactory(
        AuditResponseFactory,
        audit=factory.SelfAttribute("..audit"),
    )
    uploaded_by = factory.SelfAttribute("audit.assigned_to")
    file = factory.LazyAttribute(
        lambda _: ContentFile(b"test", name=f"attachment-{timezone.now().timestamp():.0f}.txt")
    )
    caption = "Примечание"
