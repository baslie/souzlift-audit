"""Template tags for catalog pages."""
from __future__ import annotations

from django import template

register = template.Library()


@register.filter
def dict_get(value: object, key: str) -> object:
    """Return dictionary item by key inside templates."""

    if isinstance(value, dict):
        return value.get(key, "")
    return ""


__all__ = ["dict_get"]
