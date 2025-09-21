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
    "accounts:dashboard": "dashboard",
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


def _build_admin_navigation() -> Iterable[NavigationItem]:
    return (
        NavigationItem("dashboard", "Главная", reverse("accounts:dashboard")),
        NavigationItem("buildings", "Здания", reverse("catalog:building-list")),
        NavigationItem("elevators", "Лифты", reverse("catalog:elevator-list")),
        NavigationItem("checklists", "Чек-листы", reverse("checklists:template-list")),
        NavigationItem("audits", "Аудиты", reverse("audits:audit-list")),
    )


def _build_auditor_navigation() -> Iterable[NavigationItem]:
    return (
        NavigationItem("dashboard", "Главная", reverse("accounts:dashboard")),
        NavigationItem("audits", "Мои аудиты", reverse("audits:audit-list")),
        NavigationItem("buildings", "Здания", reverse("catalog:building-list")),
        NavigationItem("elevators", "Лифты", reverse("catalog:elevator-list")),
        NavigationItem("checklists", "Чек-листы", reverse("checklists:template-list")),
    )


def primary_navigation(request: HttpRequest) -> dict[str, object]:
    """Expose the primary navigation structure for authenticated users."""

    items: list[NavigationItem] = []
    default_active = ""

    user = request.user
    if user.is_authenticated:
        profile = getattr(user, "profile", None)
        try:
            if profile and getattr(profile, "is_admin", False):
                items = list(_build_admin_navigation())
            elif profile and getattr(profile, "is_auditor", False):
                items = list(_build_auditor_navigation())
            else:
                items = [NavigationItem("dashboard", "Личный кабинет", reverse("accounts:dashboard"))]
        except NoReverseMatch:
            # During misconfiguration we prefer to fail silently to avoid
            # breaking the entire page rendering.
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

    return {
        "primary_navigation": {
            "items": items,
            "active": active_key,
            "show_admin_link": bool(user.is_authenticated and user.is_superuser),
        }
    }
