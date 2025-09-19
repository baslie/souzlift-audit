from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self) -> None:  # pragma: no cover - import side effect
        # Import signal handlers to automatically create/update user profiles.
        from . import signals  # noqa: F401
