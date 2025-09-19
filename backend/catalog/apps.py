from django.apps import AppConfig


class CatalogConfig(AppConfig):
    """Config for the catalog application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "catalog"
    verbose_name = "Справочники объектов"
