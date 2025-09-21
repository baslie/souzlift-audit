from __future__ import annotations

from decimal import Decimal
from io import BytesIO, StringIO

import pandas as pd
import pytest

from checklists.models import ChecklistItem
from checklists.services import (
    export_checklist_to_dataframe,
    import_checklist_from_dataframe,
    import_checklist_from_file,
)


@pytest.mark.django_db
def test_import_from_dataframe_creates_items(checklist_template_factory):
    template = checklist_template_factory()
    dataframe = pd.DataFrame(
        [
            {
                "order": 1,
                "area": "Зона A",
                "category": "Категория 1",
                "question": "Первый вопрос",
                "help_text": "Комментарий",
                "score_type": "numeric",
                "min_score": "0",
                "max_score": "5",
                "step": "1",
                "requires_comment": "да",
                "weight": "1.5",
            },
            {
                "order": 2,
                "area": "Зона B",
                "category": "Категория 2",
                "question": "Второй вопрос",
                "score_type": "option",
                "options": "0 - Да; 1 - Нет",
                "requires_comment": "нет",
                "weight": "2",
            },
        ]
    )

    import_checklist_from_dataframe(template, dataframe, clear_existing=True)

    items = list(template.items.order_by("order"))
    assert len(items) == 2

    numeric_item, option_item = items
    assert numeric_item.requires_comment is True
    assert numeric_item.min_score == Decimal("0")
    assert numeric_item.max_score == Decimal("5")
    assert numeric_item.step == Decimal("1")
    assert numeric_item.weight == Decimal("1.5")

    assert option_item.score_type == ChecklistItem.ScoreType.OPTION
    assert option_item.options == [
        {"label": "Да", "value": "0"},
        {"label": "Нет", "value": "1"},
    ]
    assert option_item.requires_comment is False
    assert option_item.weight == Decimal("2")


@pytest.mark.django_db
def test_import_parses_options_from_help_text(checklist_template_factory):
    template = checklist_template_factory()
    dataframe = pd.DataFrame(
        [
            {
                "question": "Доступ",
                "help_text": "0 - затруднён · 1 - доступен",
                "score_type": "0-1",
            }
        ]
    )

    import_checklist_from_dataframe(template, dataframe)

    item = template.items.get()
    assert item.score_type == ChecklistItem.ScoreType.OPTION
    assert item.options == [
        {"label": "затруднён", "value": "0"},
        {"label": "доступен", "value": "1"},
    ]


@pytest.mark.django_db
def test_import_defaults_requires_comment(checklist_template_factory):
    template = checklist_template_factory()
    dataframe = pd.DataFrame(
        [
            {
                "question": "Отсутствует столбец",
                "score_type": "numeric",
                "min_score": "0",
                "max_score": "1",
                "step": "1",
            }
        ]
    )

    import_checklist_from_dataframe(template, dataframe)

    item = template.items.get()
    assert item.requires_comment is False


@pytest.mark.django_db
def test_export_roundtrip_via_csv(checklist_template_factory, checklist_item_factory):
    template = checklist_template_factory()
    checklist_item_factory(
        template=template,
        question="Экспортируемый",
        order=1,
        requires_comment=True,
    )
    checklist_item_factory(
        template=template,
        question="С вариантами",
        score_type=ChecklistItem.ScoreType.OPTION,
        options=["0 - Нет", "1 - Да"],
        requires_comment=False,
        order=2,
    )

    dataframe = export_checklist_to_dataframe(template)
    assert list(dataframe.columns) == [
        "order",
        "area",
        "category",
        "question",
        "help_text",
        "score_type",
        "min_score",
        "max_score",
        "step",
        "options",
        "requires_comment",
        "weight",
    ]

    buffer = StringIO()
    dataframe.to_csv(buffer, index=False)
    buffer.seek(0)

    new_template = checklist_template_factory()
    import_checklist_from_file(
        new_template,
        buffer,
        filename="checklist.csv",
        clear_existing=True,
    )

    assert new_template.items.count() == template.items.count()
    imported_options = (
        new_template.items.filter(score_type=ChecklistItem.ScoreType.OPTION)
        .first()
        .options
    )
    assert imported_options == [
        {"label": "Нет", "value": "0"},
        {"label": "Да", "value": "1"},
    ]


@pytest.mark.django_db
def test_import_from_excel_file(checklist_template_factory):
    template = checklist_template_factory()
    dataframe = pd.DataFrame(
        [
            {
                "area": "Зона",
                "category": "Категория",
                "question": "Вопрос из Excel",
                "score_type": "numeric",
                "min_score": "0",
                "max_score": "10",
                "step": "5",
                "requires_comment": False,
            }
        ]
    )
    buffer = BytesIO()
    dataframe.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)

    import_checklist_from_file(
        template,
        buffer,
        filename="import.xlsx",
        clear_existing=True,
    )

    item = template.items.get()
    assert item.question == "Вопрос из Excel"
    assert item.min_score == Decimal("0")
    assert item.max_score == Decimal("10")
    assert item.requires_comment is False

