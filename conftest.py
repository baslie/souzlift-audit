from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest
from pytest_factoryboy import register

os.environ.setdefault("DJANGO_ENV", "test")

from tests import factories as test_factories

register(test_factories.UserFactory)
register(test_factories.AuditorUserFactory, _name="auditor_user")
register(test_factories.AdminUserFactory, _name="admin_user")
register(test_factories.BuildingFactory)
register(test_factories.ElevatorFactory)
register(test_factories.ChecklistTemplateFactory)
register(test_factories.ChecklistItemFactory)
register(test_factories.AuditFactory)
register(test_factories.AuditResponseFactory)
register(test_factories.AuditAttachmentFactory)


@pytest.fixture
def user_password() -> str:
    return test_factories.DEFAULT_USER_PASSWORD


@pytest.fixture(autouse=True)
def _configure_test_environment(settings, tmp_path: Path) -> Iterator[None]:
    media_root = tmp_path / "media"
    protected_root = tmp_path / "protected"
    media_root.mkdir(parents=True, exist_ok=True)
    protected_root.mkdir(parents=True, exist_ok=True)

    settings.MEDIA_ROOT = str(media_root)
    settings.PROTECTED_MEDIA_ROOT = str(protected_root)
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]

    yield


@pytest.fixture
def admin_client(admin_user, client):
    client.force_login(admin_user)
    return client


@pytest.fixture
def auditor_client(auditor_user, client):
    client.force_login(auditor_user)
    return client


@pytest.fixture
def audit_factory(auditor_user):
    def factory(**kwargs):
        kwargs.setdefault("assigned_to", auditor_user)
        return test_factories.AuditFactory(**kwargs)

    return factory
