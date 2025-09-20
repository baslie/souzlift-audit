"""Pytest configuration and shared fixtures for the project."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest
from pytest_factoryboy import register

os.environ.setdefault("DJANGO_ENV", "test")

from audits.storages import reset_protected_media_storage
from tests import factories as test_factories

register(test_factories.UserFactory)
register(test_factories.AuditorUserFactory, name="auditor_user")
register(test_factories.AdminUserFactory, name="admin_user")
register(test_factories.BuildingFactory)
register(test_factories.ElevatorFactory)
register(test_factories.ChecklistCategoryFactory)
register(test_factories.ChecklistSectionFactory)
register(test_factories.ChecklistQuestionFactory)
register(test_factories.ScoreOptionFactory)
register(test_factories.ObjectInfoFieldFactory)
register(test_factories.AuditFactory)
register(test_factories.AuditResponseFactory)
register(test_factories.AuditAttachmentFactory)
register(test_factories.AuditSignatureFactory)
register(test_factories.AuditLogEntryFactory)
register(test_factories.OfflineSyncBatchFactory)


@pytest.fixture
def user_password() -> str:
    """Возвращает пароль, используемый фабриками пользователей."""

    return test_factories.DEFAULT_USER_PASSWORD


@pytest.fixture(autouse=True)
def _isolate_media_storage(settings, tmp_path: Path) -> Iterator[None]:
    """Изолирует каталоги хранения файлов для каждого теста."""

    base_dir = Path(getattr(settings, "BASE_DIR", tmp_path))
    media_root = tmp_path / "media"
    protected_root = tmp_path / "protected"

    def _should_override(path: Path) -> bool:
        try:
            return path.resolve().is_relative_to(base_dir.resolve())
        except AttributeError:  # pragma: no cover - Python <3.9 compatibility
            try:
                path.resolve().relative_to(base_dir.resolve())
                return True
            except ValueError:
                return False
        except ValueError:
            return False

    if _should_override(Path(settings.MEDIA_ROOT)):
        media_root.mkdir(parents=True, exist_ok=True)
        settings.MEDIA_ROOT = str(media_root)

    if _should_override(Path(settings.PROTECTED_MEDIA_ROOT)):
        protected_root.mkdir(parents=True, exist_ok=True)
        settings.PROTECTED_MEDIA_ROOT = str(protected_root)
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]

    reset_protected_media_storage()

    yield

    reset_protected_media_storage()


@pytest.fixture
def admin_client(admin_user, client):
    """Django test client, авторизованный под администратором."""

    client.force_login(admin_user)
    return client


@pytest.fixture
def auditor_client(auditor_user, client):
    """Django test client, авторизованный под аудитором."""

    client.force_login(auditor_user)
    return client
