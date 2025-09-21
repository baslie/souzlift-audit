from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from checklists.models import ChecklistItem


@pytest.mark.django_db
def test_numeric_item_requires_range(checklist_item_factory):
    item = checklist_item_factory.build(min_score=None, max_score=None, step=None)
    with pytest.raises(ValidationError) as exc:
        item.full_clean()
    assert "Минимальный балл" in str(exc.value)


@pytest.mark.django_db
def test_option_item_requires_choices(checklist_item_factory):
    item = checklist_item_factory.build(score_type=ChecklistItem.ScoreType.OPTION, options=[])
    with pytest.raises(ValidationError) as exc:
        item.full_clean()
    assert "вариант" in str(exc.value)


@pytest.mark.django_db
def test_clone_copies_items(checklist_template_factory, checklist_item_factory):
    template = checklist_template_factory()
    checklist_item_factory(template=template, question="Первый")
    checklist_item_factory(template=template, question="Второй", order=2)

    copy = template.clone(name="Новая версия")
    assert copy.name == "Новая версия"
    assert copy.items.count() == 2
    assert list(copy.items.values_list("question", flat=True)) == ["Первый", "Второй"]
