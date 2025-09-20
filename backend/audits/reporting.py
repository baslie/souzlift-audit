"""Utilities for building structured audit reports for exports and admin views."""
from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from django.utils.translation import gettext_lazy as _

from catalog.models import ChecklistQuestion, ObjectInfoField

from .models import Audit


def _coerce_boolean(value: Any) -> bool:
    """Convert various value representations to a boolean."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "да"}
    return bool(value)


def format_object_info_value(field_type: str | None, value: Any) -> str:
    """Format stored object info values for presentation."""

    if value is None:
        return ""

    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return ""
    else:
        text_value = value

    if field_type == ObjectInfoField.FieldType.BOOLEAN:
        return str(_("Да") if _coerce_boolean(text_value) else _("Нет"))

    if isinstance(text_value, (list, tuple)):
        cleaned = [str(item).strip() for item in text_value if str(item).strip()]
        return ", ".join(cleaned)

    if isinstance(text_value, dict):
        return json.dumps(text_value, ensure_ascii=False, sort_keys=True, indent=2)

    if isinstance(text_value, (date, datetime)):
        return text_value.isoformat()

    return str(text_value)


def prepare_object_info_items(audit: Audit) -> list[dict[str, Any]]:
    """Build a list of object info items for the provided audit."""

    stored_info = audit.object_info or {}
    items: list[dict[str, Any]] = []
    known_codes: set[str] = set()

    fields = ObjectInfoField.objects.all().order_by("order", "label")
    for field in fields:
        raw_value = stored_info.get(field.code)
        value = format_object_info_value(field.field_type, raw_value)
        items.append(
            {
                "code": field.code,
                "label": field.label,
                "value": value,
                "raw_value": raw_value,
                "field_type": field.field_type,
                "is_empty": value == "",
                "is_extra": False,
                "is_multiline": "\n" in value if isinstance(value, str) else False,
            }
        )
        known_codes.add(field.code)

    for code, raw_value in stored_info.items():
        if code in known_codes:
            continue
        value = format_object_info_value(None, raw_value)
        items.append(
            {
                "code": code,
                "label": code,
                "value": value,
                "raw_value": raw_value,
                "field_type": None,
                "is_empty": value == "",
                "is_extra": True,
                "is_multiline": "\n" in value if isinstance(value, str) else False,
            }
        )

    return items


def _question_answer_display(question: dict[str, Any], response: Any) -> tuple[str, str, str, bool]:
    """Return tuple of value, answer, comment display and comment presence."""

    question_type = question.get("type")
    comment_text = ""
    score_display = ""
    answer_display = ""
    has_comment = False

    if response is not None:
        comment_text = (response.comment or "").strip()

        if question_type == ChecklistQuestion.QuestionType.TEXT:
            answer_display = comment_text
            score_display = comment_text or ""
            has_comment = bool(comment_text)
        elif question_type == ChecklistQuestion.QuestionType.BOOLEAN:
            if response.score is not None:
                answer_display = _("Да") if _coerce_boolean(response.score) else _("Нет")
                score_display = answer_display
            has_comment = bool(comment_text)
        else:
            if response.score is not None:
                max_score = question.get("max_score") or 0
                if max_score:
                    score_display = _("%(score)d из %(max)d") % {
                        "score": int(response.score),
                        "max": int(max_score),
                    }
                else:
                    score_display = str(response.score)
            has_comment = bool(comment_text)

    return score_display, answer_display, comment_text, has_comment


def build_question_entry(
    question: dict[str, Any],
    response: Any,
    attachments: list[Any],
) -> dict[str, Any]:
    """Create a structured representation of a checklist question result."""

    score_display, answer_display, comment_text, has_comment = _question_answer_display(
        question, response
    )

    if not score_display:
        score_display = "—"

    question_type = question.get("type")

    return {
        "id": question.get("id"),
        "text": question.get("text"),
        "type": question_type,
        "max_score": question.get("max_score"),
        "guideline": question.get("guideline"),
        "requires_comment": question.get("requires_comment"),
        "response": response,
        "attachments": attachments,
        "value_display": score_display,
        "answer_display": answer_display,
        "comment_display": comment_text,
        "has_response": response is not None,
        "has_comment": has_comment,
        "is_flagged": bool(getattr(response, "is_flagged", False)) if response else False,
        "is_offline": bool(getattr(response, "is_offline_cached", False)) if response else False,
        "score_raw": getattr(response, "score", None) if response else None,
    }


def prepare_checklist_context(
    audit: Audit, checklist_structure: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build hierarchical checklist data along with summary statistics."""

    responses = list(audit.responses.all())
    response_map = {response.question_id: response for response in responses}

    summary = {
        "total_questions": 0,
        "answered_questions": 0,
        "attachments_total": 0,
        "comments_total": 0,
        "flagged_total": 0,
    }

    checklist_context: list[dict[str, Any]] = []
    for category in checklist_structure.get("categories", []):
        section_context: list[dict[str, Any]] = []
        for section in category.get("sections", []):
            questions_context: list[dict[str, Any]] = []
            for question in section.get("questions", []):
                summary["total_questions"] += 1
                response = response_map.get(question.get("id"))
                attachments = list(response.attachments.all()) if response else []
                if response:
                    summary["answered_questions"] += 1
                    summary["attachments_total"] += len(attachments)
                    if (response.comment or "").strip():
                        summary["comments_total"] += 1
                    if response.is_flagged:
                        summary["flagged_total"] += 1
                question_entry = build_question_entry(question, response, attachments)
                questions_context.append(question_entry)
            section_context.append(
                {
                    "id": section.get("id"),
                    "title": section.get("title"),
                    "description": section.get("description"),
                    "questions": questions_context,
                }
            )
        checklist_context.append(
            {
                "id": category.get("id"),
                "name": category.get("name"),
                "code": category.get("code"),
                "sections": section_context,
            }
        )

    return checklist_context, summary


def build_audit_report(
    audit: Audit, *, checklist_structure: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return consolidated data describing an audit for reporting purposes."""

    if checklist_structure is None:
        from .services import build_checklist_structure

        checklist_structure = build_checklist_structure()

    object_info_items = prepare_object_info_items(audit)
    checklist_context, summary = prepare_checklist_context(audit, checklist_structure)
    summary["unanswered_questions"] = (
        summary["total_questions"] - summary["answered_questions"]
    )

    return {
        "object_info": object_info_items,
        "object_info_has_values": any(not item["is_empty"] for item in object_info_items),
        "object_info_has_extra": any(item["is_extra"] for item in object_info_items),
        "checklist": checklist_context,
        "summary": summary,
    }


__all__ = [
    "build_audit_report",
    "build_question_entry",
    "format_object_info_value",
    "prepare_checklist_context",
    "prepare_object_info_items",
]

