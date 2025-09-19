from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ReviewStatus(models.TextChoices):
    """Common moderation statuses for catalog records."""

    PENDING = "pending", _("Ожидает проверки")
    APPROVED = "approved", _("Подтверждён")
    REJECTED = "rejected", _("Отклонён")


class ModeratedQuerySet(models.QuerySet):
    """QuerySet helpers for models moderated by administrators."""

    def approved(self) -> "ModeratedQuerySet":
        return self.filter(review_status=ReviewStatus.APPROVED)

    def pending(self) -> "ModeratedQuerySet":
        return self.filter(review_status=ReviewStatus.PENDING)

    def rejected(self) -> "ModeratedQuerySet":
        return self.filter(review_status=ReviewStatus.REJECTED)

    def visible_for_user(self, user: object) -> "ModeratedQuerySet":
        """Restrict queryset according to moderation rules."""

        if not getattr(user, "is_authenticated", False):
            return self.approved()

        profile = getattr(user, "profile", None)
        if profile is not None and getattr(profile, "is_admin", False):
            return self

        visibility_filter = models.Q(review_status=ReviewStatus.APPROVED)
        if profile is not None and getattr(profile, "is_auditor", False):
            visibility_filter |= models.Q(created_by=profile.user)
        elif getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            visibility_filter |= models.Q(created_by=user)

        return self.filter(visibility_filter)

    def for_moderation(self) -> "ModeratedQuerySet":
        """Return a queue ordered by creation time for administrator review."""

        return self.pending().order_by("created_at")


class ModeratedManager(models.Manager.from_queryset(ModeratedQuerySet)):
    """Default manager exposing moderation helpers."""

    pass


class ModerationMixin:
    """Behavior shared by moderated catalog models."""

    def _set_review_status(
        self,
        status: str,
        *,
        reviewer: object | None = None,
        commit: bool = True,
    ) -> None:
        """Internal helper that updates moderation state and metadata."""

        update_fields: set[str] = {"review_status"}
        self.review_status = status

        if status == ReviewStatus.PENDING:
            if self.verified_by_id is not None:  # type: ignore[attr-defined]
                self.verified_by = None  # type: ignore[assignment]
                update_fields.add("verified_by")
            if self.verified_at is not None:
                self.verified_at = None
                update_fields.add("verified_at")
        else:
            if reviewer is None:
                raise ValueError("Reviewer must be provided when approving or rejecting a record.")
            self.verified_by = reviewer  # type: ignore[assignment]
            self.verified_at = timezone.now()
            update_fields.update({"verified_by", "verified_at"})

        if commit:
            self.save(update_fields=sorted(update_fields))

    def approve(self, reviewer: object, *, commit: bool = True) -> None:
        """Mark the record as approved by administrator."""

        self._set_review_status(ReviewStatus.APPROVED, reviewer=reviewer, commit=commit)

    def reject(self, reviewer: object, *, commit: bool = True) -> None:
        """Mark the record as rejected by administrator."""

        self._set_review_status(ReviewStatus.REJECTED, reviewer=reviewer, commit=commit)

    def send_to_review(self, *, commit: bool = True) -> None:
        """Return the record to moderation queue (pending status)."""

        self._set_review_status(ReviewStatus.PENDING, reviewer=None, commit=commit)


class Building(ModerationMixin, models.Model):
    """Справочник зданий, доступных аудиторам."""

    address = models.CharField(
        _("Адрес"),
        max_length=255,
        help_text=_("Улица и номер дома."),
    )
    entrance = models.CharField(
        _("Подъезд"),
        max_length=50,
        blank=True,
        help_text=_("Дополнительные указания: номер подъезда, корпус и т.п."),
    )
    notes = models.TextField(
        _("Примечания"),
        blank=True,
        help_text=_("Особенности объекта или дополнительные комментарии."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="buildings_created",
        verbose_name=_("Автор"),
        help_text=_("Пользователь, добавивший запись."),
    )
    created_at = models.DateTimeField(
        _("Дата создания"),
        auto_now_add=True,
        help_text=_("Когда запись была создана."),
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="buildings_verified",
        verbose_name=_("Подтвердил"),
        help_text=_("Администратор, утвердивший запись."),
    )
    verified_at = models.DateTimeField(
        _("Дата подтверждения"),
        null=True,
        blank=True,
        help_text=_("Когда администратор проверил запись."),
    )
    review_status = models.CharField(
        _("Статус модерации"),
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        help_text=_("Определяет доступность записи для других пользователей."),
    )

    objects = ModeratedManager()

    class Meta:
        verbose_name = _("Здание")
        verbose_name_plural = _("Здания")
        ordering = ["address", "entrance"]
        constraints = [
            models.UniqueConstraint(
                fields=["address", "entrance"],
                condition=models.Q(review_status=ReviewStatus.APPROVED),
                name="unique_approved_building_address",
            )
        ]

    def __str__(self) -> str:
        if self.entrance:
            return f"{self.address}, подъезд {self.entrance}"
        return self.address


class Elevator(ModerationMixin, models.Model):
    """Справочник лифтов, привязанных к зданиям."""

    class Status(models.TextChoices):
        IN_SERVICE = "in_service", _("В эксплуатации")
        OUT_OF_SERVICE = "out_of_service", _("Не работает")
        UNDER_MAINTENANCE = "under_maintenance", _("На обслуживании")
        DECOMMISSIONED = "decommissioned", _("Списан")

    building = models.ForeignKey(
        Building,
        on_delete=models.PROTECT,
        related_name="elevators",
        verbose_name=_("Здание"),
        help_text=_("Объект, в котором расположен лифт."),
    )
    identifier = models.CharField(
        _("Идентификатор"),
        max_length=64,
        help_text=_("Заводской номер или внутренний идентификатор."),
    )
    description = models.TextField(
        _("Описание"),
        blank=True,
        help_text=_("Дополнительная информация о лифте."),
    )
    status = models.CharField(
        _("Статус"),
        max_length=32,
        choices=Status.choices,
        default=Status.IN_SERVICE,
        help_text=_("Текущее состояние лифта."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="elevators_created",
        verbose_name=_("Автор"),
        help_text=_("Пользователь, добавивший запись."),
    )
    created_at = models.DateTimeField(
        _("Дата создания"),
        auto_now_add=True,
        help_text=_("Когда запись была создана."),
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="elevators_verified",
        verbose_name=_("Подтвердил"),
        help_text=_("Администратор, утвердивший запись."),
    )
    verified_at = models.DateTimeField(
        _("Дата подтверждения"),
        null=True,
        blank=True,
        help_text=_("Когда администратор проверил запись."),
    )
    review_status = models.CharField(
        _("Статус модерации"),
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        help_text=_("Определяет доступность записи для других пользователей."),
    )

    objects = ModeratedManager()

    class Meta:
        verbose_name = _("Лифт")
        verbose_name_plural = _("Лифты")
        ordering = ["building__address", "identifier"]
        constraints = [
            models.UniqueConstraint(
                fields=["building", "identifier"],
                condition=models.Q(review_status=ReviewStatus.APPROVED),
                name="unique_approved_elevator_identifier",
            )
        ]

    def __str__(self) -> str:
        return f"{self.identifier} ({self.building})"


class ChecklistCategory(models.Model):
    """Группа вопросов чек-листа с собственным порядком."""

    code = models.SlugField(
        _("Код"),
        max_length=50,
        unique=True,
        help_text=_("Уникальный идентификатор для ссылок и импорта."),
    )
    name = models.CharField(
        _("Название"),
        max_length=255,
        help_text=_("Отображаемое имя категории."),
    )
    order = models.PositiveIntegerField(
        _("Порядок"),
        default=0,
        help_text=_("Используется для сортировки категорий в интерфейсе."),
    )

    class Meta:
        verbose_name = _("Категория чек-листа")
        verbose_name_plural = _("Категории чек-листа")
        ordering = ["order", "name"]
        indexes = [models.Index(fields=["order"])]

    def __str__(self) -> str:
        return self.name


class ChecklistSection(models.Model):
    """Логический блок вопросов внутри категории."""

    category = models.ForeignKey(
        "catalog.ChecklistCategory",
        on_delete=models.CASCADE,
        related_name="sections",
        verbose_name=_("Категория"),
        help_text=_("Категория, к которой относится секция."),
    )
    title = models.CharField(
        _("Название"),
        max_length=255,
        help_text=_("Заголовок секции в чек-листе."),
    )
    description = models.TextField(
        _("Описание"),
        blank=True,
        help_text=_("Дополнительные инструкции для аудитора."),
    )
    order = models.PositiveIntegerField(
        _("Порядок"),
        default=0,
        help_text=_("Определяет расположение секции внутри категории."),
    )

    class Meta:
        verbose_name = _("Секция чек-листа")
        verbose_name_plural = _("Секции чек-листа")
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "order"],
                name="unique_section_order_per_category",
            )
        ]

    def __str__(self) -> str:
        return self.title


class ChecklistQuestion(models.Model):
    """Конкретный вопрос чек-листа с параметрами оценки."""

    class QuestionType(models.TextChoices):
        SCORE = "score", _("Балльный")
        BOOLEAN = "boolean", _("Да/Нет")
        TEXT = "text", _("Текстовый")

    section = models.ForeignKey(
        "catalog.ChecklistSection",
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name=_("Секция"),
        help_text=_("Секция, в которой отображается вопрос."),
    )
    text = models.TextField(
        _("Формулировка"),
        help_text=_("Текст вопроса, отображаемый аудитору."),
    )
    type = models.CharField(
        _("Тип вопроса"),
        max_length=20,
        choices=QuestionType.choices,
        default=QuestionType.SCORE,
        help_text=_("Определяет формат ответа."),
    )
    max_score = models.PositiveIntegerField(
        _("Максимальный балл"),
        default=0,
        help_text=_("Используется для балльных вопросов."),
    )
    order = models.PositiveIntegerField(
        _("Порядок"),
        default=0,
        help_text=_("Позиция вопроса внутри секции."),
    )
    guideline = models.TextField(
        _("Подсказка"),
        blank=True,
        help_text=_("Инструкции или критерии оценки."),
    )
    requires_comment = models.BooleanField(
        _("Комментарий обязателен"),
        default=False,
        help_text=_("Требовать комментарий независимо от выбранного балла."),
    )

    class Meta:
        verbose_name = _("Вопрос чек-листа")
        verbose_name_plural = _("Вопросы чек-листа")
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "order"],
                name="unique_question_order_per_section",
            )
        ]

    def __str__(self) -> str:
        return self.text

    def _get_cached_score_values(self) -> list[int]:
        """Return available score values for the question using cached relations."""

        cache_key = "score_options"
        if not hasattr(self, "_score_value_cache"):
            options = None
            if hasattr(self, "_prefetched_objects_cache"):
                options = self._prefetched_objects_cache.get(cache_key)

            if options is None:
                options = list(self.score_options.all())

            self._score_value_cache = [option.score for option in options]

        return list(self._score_value_cache)

    def is_score_valid(self, score: int | None) -> bool:
        """Check that provided score matches available options for the question."""

        if self.type != self.QuestionType.SCORE:
            return score is None
        if score is None:
            return False
        return score in self._get_cached_score_values()

    def requires_comment_for_score(self, score: int | None) -> bool:
        """Determine whether a comment is mandatory for a given score value."""

        if self.requires_comment:
            return True
        if self.type != self.QuestionType.SCORE:
            return False
        if score is None:
            return False
        if self.max_score <= 0:
            return False
        return score < self.max_score

    def validate_answer(self, *, score: int | None, comment: str | None) -> None:
        """Validate score/comment pair according to business rules."""

        errors: dict[str, list[str]] = {}

        if self.type == self.QuestionType.SCORE:
            if score is None:
                errors.setdefault("score", []).append(_("Необходимо выбрать балл."))
            elif not self.is_score_valid(score):
                errors.setdefault("score", []).append(
                    _("Выбранный балл недоступен для этого вопроса."),
                )
            if self.requires_comment_for_score(score):
                comment_text = (comment or "").strip()
                if not comment_text:
                    errors.setdefault("comment", []).append(
                        _("Комментарий обязателен при снижении балла."),
                    )
        else:
            if self.requires_comment:
                comment_text = (comment or "").strip()
                if not comment_text:
                    errors.setdefault("comment", []).append(
                        _("Комментарий обязателен для этого вопроса."),
                    )

        if errors:
            raise ValidationError(errors)


class ScoreOption(models.Model):
    """Доступный вариант ответа для балльного вопроса."""

    question = models.ForeignKey(
        "catalog.ChecklistQuestion",
        on_delete=models.CASCADE,
        related_name="score_options",
        verbose_name=_("Вопрос"),
        help_text=_("Вопрос, к которому относится вариант."),
    )
    score = models.PositiveIntegerField(
        _("Баллы"),
        help_text=_("Количество баллов за выбранный вариант."),
    )
    description = models.CharField(
        _("Описание"),
        max_length=255,
        help_text=_("Краткое описание условия получения баллов."),
    )
    order = models.PositiveIntegerField(
        _("Порядок"),
        default=0,
        help_text=_("Используется для сортировки вариантов."),
    )

    class Meta:
        verbose_name = _("Вариант оценки")
        verbose_name_plural = _("Варианты оценок")
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["question", "order"],
                name="unique_score_option_order_per_question",
            ),
            models.UniqueConstraint(
                fields=["question", "score"],
                name="unique_score_per_question",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.score} — {self.description}"

    def clean(self) -> None:
        """Ensure that option is consistent with the related question."""

        super().clean()
        if self.question_id is None and self.question is None:  # pragma: no cover - defensive
            return

        question = self.question
        if question.type != ChecklistQuestion.QuestionType.SCORE:
            raise ValidationError(
                {
                    "question": _("Варианты баллов допустимы только для балльных вопросов."),
                }
            )

        if self.score > question.max_score:
            raise ValidationError(
                {
                    "score": _(
                        "Значение баллов не может превышать максимальный балл вопроса (%(max)d)."
                    )
                    % {"max": question.max_score},
                }
            )

        if question.max_score <= 0 and self.score > 0:
            raise ValidationError(
                {
                    "score": _(
                        "Для добавления положительного балла увеличьте максимальный балл вопроса."
                    )
                }
            )


class ObjectInfoField(models.Model):
    """Настраиваемое поле информационной карточки объекта."""

    class FieldType(models.TextChoices):
        TEXT = "text", _("Текст")
        NUMBER = "number", _("Число")
        DATE = "date", _("Дата")
        BOOLEAN = "boolean", _("Да/Нет")
        CHOICE = "choice", _("Выбор из списка")

    code = models.SlugField(
        _("Код"),
        max_length=50,
        unique=True,
        help_text=_("Машинное имя поля для хранения значений."),
    )
    label = models.CharField(
        _("Название"),
        max_length=255,
        help_text=_("Как поле отображается в форме."),
    )
    field_type = models.CharField(
        _("Тип поля"),
        max_length=20,
        choices=FieldType.choices,
        default=FieldType.TEXT,
        help_text=_("Определяет формат значения."),
    )
    is_required = models.BooleanField(
        _("Обязательное"),
        default=False,
        help_text=_("Нужно ли обязательно заполнять поле."),
    )
    order = models.PositiveIntegerField(
        _("Порядок"),
        default=0,
        help_text=_("Используется для сортировки полей."),
    )
    choices = models.TextField(
        _("Варианты"),
        blank=True,
        help_text=_(
            "Список значений для выбора (по одному в строке). Используется для полей выбора."
        ),
    )

    class Meta:
        verbose_name = _("Поле информационной карточки")
        verbose_name_plural = _("Поля информационной карточки")
        ordering = ["order", "label"]
        indexes = [models.Index(fields=["order"])]

    def __str__(self) -> str:
        return self.label
