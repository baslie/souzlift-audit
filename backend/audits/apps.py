from __future__ import annotations

from django.apps import AppConfig


class AuditsConfig(AppConfig):
    """Application configuration for audit-related models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "audits"
    verbose_name = "Аудиты"

    def ready(self) -> None:  # pragma: no cover - import side effects
        from . import signals  # noqa: F401
