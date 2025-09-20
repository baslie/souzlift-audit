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
    "audits:audit-export-print": "audits",
    "audits:audit-export-csv": "audits",
    "audits:audit-export-excel": "audits",
    "audits:audit-mark-reviewed": "audits",
    "audits:audit-log-list": "monitoring",
    "audits:offline-batch-list": "monitoring",
    "audits:offline-object-info": "audits",
    "audits:offline-checklist": "audits",
    "catalog:building-list": "buildings",
    "catalog:building-create": "buildings",
    "catalog:building-update": "buildings",
    "catalog:building-moderate": "buildings",
    "catalog:elevator-list": "elevators",
    "catalog:elevator-create": "elevators",
    "catalog:elevator-update": "elevators",
    "catalog:elevator-moderate": "elevators",
    "catalog:checklist-overview": "checklist",
    "catalog:checklist-category-create": "checklist",
    "catalog:checklist-category-update": "checklist",
    "catalog:checklist-category-delete": "checklist",
    "catalog:checklist-category-move": "checklist",
    "catalog:checklist-section-create": "checklist",
    "catalog:checklist-section-update": "checklist",
    "catalog:checklist-section-delete": "checklist",
    "catalog:checklist-section-move": "checklist",
    "catalog:checklist-question-create": "checklist",
    "catalog:checklist-question-update": "checklist",
    "catalog:checklist-question-delete": "checklist",
    "catalog:checklist-question-move": "checklist",
    "catalog:checklist-option-create": "checklist",
    "catalog:checklist-option-update": "checklist",
    "catalog:checklist-option-delete": "checklist",
    "catalog:checklist-option-move": "checklist",
    "catalog:object-field-list": "settings",
    "catalog:object-field-create": "settings",
    "catalog:object-field-update": "settings",
    "catalog:object-field-delete": "settings",
    "catalog:object-field-move": "settings",
}


def _build_admin_navigation() -> Iterable[NavigationItem]:
    return (
        NavigationItem("dashboard", "Кабинет администратора", reverse("accounts:dashboard")),
        NavigationItem("audits", "Аудиты", reverse("audits:audit-list")),
        NavigationItem("monitoring", "Мониторинг", reverse("audits:audit-log-list")),
        NavigationItem("buildings", "Здания", reverse("catalog:building-list")),
        NavigationItem("elevators", "Лифты", reverse("catalog:elevator-list")),
        NavigationItem("checklist", "Чек-лист", reverse("catalog:checklist-overview")),
        NavigationItem("settings", "Настройки", reverse("catalog:object-field-list")),
    )


def _build_auditor_navigation() -> Iterable[NavigationItem]:
    return (
        NavigationItem("dashboard", "Кабинет аудитора", reverse("accounts:dashboard")),
        NavigationItem("audits", "Мои аудиты", reverse("audits:audit-list")),
        NavigationItem("buildings", "Здания", reverse("catalog:building-list")),
        NavigationItem("elevators", "Лифты", reverse("catalog:elevator-list")),
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
