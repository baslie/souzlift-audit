"""Context processors for the accounts application."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse


@dataclass(frozen=True)
class NavigationItem:
    """Descriptor for a navigation entry in the application header."""

    key: str
    label: str
    url: str


_ACTIVE_VIEW_MAP: dict[str, str] = {
    "audits:audit-list": "audits",
    "audits:audit-detail": "audits",
    "catalog:building-list": "buildings",
    "catalog:building-create": "buildings",
    "catalog:building-update": "buildings",
    "catalog:elevator-list": "elevators",
    "catalog:elevator-create": "elevators",
    "catalog:elevator-update": "elevators",
    "checklists:template-list": "checklists",
    "checklists:template-detail": "checklists",
}


def _build_navigation_items() -> Iterable[NavigationItem]:
    navigation_blueprint: tuple[tuple[str, str, str], ...] = (
        ("buildings", "Здания", "catalog:building-list"),
        ("elevators", "Лифты", "catalog:elevator-list"),
        ("checklists", "Чек-листы", "checklists:template-list"),
        ("audits", "Аудиты", "audits:audit-list"),
    )
    for key, label, view_name in navigation_blueprint:
        yield NavigationItem(key, label, reverse(view_name))


def primary_navigation(request: HttpRequest) -> dict[str, object]:
    """Expose the primary navigation structure for authenticated users."""

    items: list[NavigationItem] = []
    default_active = ""

    user = request.user
    if user.is_authenticated:
        profile = getattr(user, "profile", None)
        try:
            if profile and (getattr(profile, "is_admin", False) or getattr(profile, "is_auditor", False)):
                items = list(_build_navigation_items())
            elif user.is_staff or user.is_superuser:
                items = list(_build_navigation_items())
            else:
                items = []
        except NoReverseMatch:
            items = []

        if items:
            default_active = items[0].key

    resolver_match = getattr(request, "resolver_match", None)
    active_key = ""
    if resolver_match:
        active_key = _ACTIVE_VIEW_MAP.get(resolver_match.view_name, "")
        if not active_key and resolver_match.view_name == "accounts:dashboard":
            active_key = "dashboard"

    if not active_key:
        active_key = default_active

    if not items:
        active_key = ""

    return {
        "primary_navigation": {
            "items": items,
            "active": active_key,
            "show_admin_link": bool(user.is_authenticated and user.is_superuser),
        }
    }
