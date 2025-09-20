"""Helper functions for auditor-facing catalogue snapshots."""
from __future__ import annotations

from typing import Any

from django.db.models import Prefetch
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from catalog.models import (
    Building,
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    Elevator,
    ObjectInfoField,
    ScoreOption,
)

from accounts.permissions import is_admin
from audits.models import Audit


def _serialise_building(building: Building) -> dict[str, Any]:
    """Convert a building instance to a JSON-friendly structure."""

    return {
        "id": building.pk,
        "address": building.address,
        "entrance": building.entrance or "",
        "notes": building.notes or "",
        "label": str(building),
        "review_status": building.review_status,
    }


def _serialise_elevator(elevator: Elevator) -> dict[str, Any]:
    """Convert an elevator instance to a JSON-friendly structure."""

    return {
        "id": elevator.pk,
        "building_id": elevator.building_id,
        "identifier": elevator.identifier,
        "description": elevator.description or "",
        "status": elevator.status,
        "label": elevator.identifier,
        "building_label": str(elevator.building),
        "review_status": elevator.review_status,
    }


def _serialise_object_info_field(field: ObjectInfoField) -> dict[str, Any]:
    """Prepare object info field metadata for UI consumption."""

    choices = [value.strip() for value in field.choices.splitlines() if value.strip()]
    return {
        "code": field.code,
        "label": field.label,
        "field_type": field.field_type,
        "is_required": field.is_required,
        "order": field.order,
        "choices": choices,
    }


def build_catalog_snapshot_for_user(
    user: object,
    *,
    include_checklist: bool = False,
    include_filters: bool = False,
) -> dict[str, Any]:
    """Return catalogue data visible to the user for offline consumption."""

    buildings_qs = Building.objects.visible_for_user(user).select_related("created_by__profile")
    elevators_qs = Elevator.objects.visible_for_user(user).select_related("building")
    fields_qs = ObjectInfoField.objects.all().order_by("order", "label")

    snapshot: dict[str, Any] = {
        "generated_at": timezone.now().isoformat(),
        "buildings": [_serialise_building(item) for item in buildings_qs],
        "elevators": [_serialise_elevator(item) for item in elevators_qs],
        "object_fields": [_serialise_object_info_field(item) for item in fields_qs],
    }

    if include_checklist:
        snapshot["checklist"] = build_checklist_structure()

    if include_filters:
        snapshot["audit_filters"] = build_audit_filter_snapshot(user)

    return snapshot


def _serialise_score_option(option: ScoreOption) -> dict[str, Any]:
    """Prepare a checklist score option for JSON consumption."""

    return {
        "id": option.pk,
        "score": option.score,
        "description": option.description,
        "order": option.order,
    }


def _serialise_question(
    question: ChecklistQuestion,
    *,
    section: ChecklistSection | None = None,
    category: ChecklistCategory | None = None,
) -> dict[str, Any]:
    """Serialise a checklist question along with its available options."""

    score_options = []
    requires_comment_on_reduced_score = False
    if question.type == ChecklistQuestion.QuestionType.SCORE:
        options = list(question.score_options.all())
        score_options = [_serialise_score_option(option) for option in options]
        if question.max_score > 0 and options:
            for option in options:
                if option.score < question.max_score and question.requires_comment_for_score(option.score):
                    requires_comment_on_reduced_score = True
                    break

    data = {
        "id": question.pk,
        "text": question.text,
        "type": question.type,
        "max_score": question.max_score,
        "guideline": question.guideline,
        "requires_comment": question.requires_comment,
        "requires_comment_on_reduced_score": requires_comment_on_reduced_score,
        "score_options": score_options,
    }

    if section is not None:
        data["section_id"] = section.pk
        data["section_title"] = section.title

    if category is not None:
        data["category_id"] = category.pk
        data["category_code"] = category.code
        data["category_name"] = category.name

    return data


def _serialise_section(
    section: ChecklistSection,
    *,
    category: ChecklistCategory | None = None,
) -> dict[str, Any]:
    """Serialise a checklist section with ordered questions."""

    questions = [
        _serialise_question(question, section=section, category=category)
        for question in section.questions.all()
    ]
    data = {
        "id": section.pk,
        "title": section.title,
        "description": section.description,
        "order": section.order,
        "questions": questions,
    }

    if category is not None:
        data["category_id"] = category.pk

    return data


def _serialise_category(category: ChecklistCategory) -> dict[str, Any]:
    """Serialise checklist category with nested sections."""

    sections = [
        _serialise_section(section, category=category)
        for section in category.sections.all()
    ]
    return {
        "id": category.pk,
        "code": category.code,
        "name": category.name,
        "order": category.order,
        "sections": sections,
    }


def build_checklist_structure() -> dict[str, Any]:
    """Return checklist categories, sections and questions ready for UI rendering."""

    question_qs = (
        ChecklistQuestion.objects.all()
        .order_by("order", "id")
        .prefetch_related("score_options")
    )
    section_qs = (
        ChecklistSection.objects.all()
        .order_by("order", "id")
        .prefetch_related(Prefetch("questions", queryset=question_qs))
    )
    category_qs = ChecklistCategory.objects.all().order_by("order", "name").prefetch_related(
        Prefetch("sections", queryset=section_qs)
    )

    categories = [_serialise_category(category) for category in category_qs]
    total_sections = sum(len(category["sections"]) for category in categories)
    total_questions = sum(
        len(section["questions"]) for category in categories for section in category["sections"]
    )

    return {
        "categories": categories,
        "total_sections": total_sections,
        "total_questions": total_questions,
        "generated_at": timezone.now().isoformat(),
    }


def build_audit_filter_snapshot(user: object | None = None) -> dict[str, Any]:
    """Return available audit filter options tailored for the given user."""

    status_filters = [("", _("Все статусы"))] + list(Audit.Status.choices)
    period_filters = [
        ("", _("За всё время")),
        ("7", _("За последние 7 дней")),
        ("30", _("За последние 30 дней")),
        ("90", _("За последние 90 дней")),
    ]

    filters: dict[str, list[dict[str, str]]] = {
        "status": [
            {"value": value, "label": str(label)} for value, label in status_filters
        ],
        "period": [
            {"value": value, "label": str(label)} for value, label in period_filters
        ],
    }

    if user is not None and is_admin(user):
        review_filters = [
            ("", _("Все аудиты")),
            ("pending", _("Ожидают проверки")),
            ("active", _("В работе")),
            ("reviewed", _("Просмотренные")),
        ]
        filters["review"] = [
            {"value": value, "label": str(label)} for value, label in review_filters
        ]

    return filters

