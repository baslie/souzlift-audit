from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.utils import override_settings

from audits.models import AuditAttachment
from tests.factories import AuditAttachmentFactory, AuditFactory, AuditResponseFactory


@pytest.mark.django_db
def test_attachment_rejects_large_file(audit_factory) -> None:
    audit = audit_factory()
    response = AuditResponseFactory(audit=audit)
    large_file = SimpleUploadedFile("large.bin", b"x" * 2049)

    with override_settings(
        AUDIT_ATTACHMENT_LIMITS={
            "max_size_bytes": 2048,
            "max_per_response": 5,
            "max_per_audit": 5,
        }
    ):
        attachment = AuditAttachment(
            audit=audit,
            response=response,
            file=large_file,
        )

        with pytest.raises(ValidationError) as exc:
            attachment.full_clean()

    assert "Размер файла" in str(exc.value)


@pytest.mark.django_db
def test_attachment_enforces_per_response_limit(audit_factory) -> None:
    audit = audit_factory()
    response = AuditResponseFactory(audit=audit)

    with override_settings(
        AUDIT_ATTACHMENT_LIMITS={
            "max_size_bytes": 1024 * 1024,
            "max_per_response": 1,
            "max_per_audit": 5,
        }
    ):
        AuditAttachmentFactory(audit=audit, response=response)

        extra_file = SimpleUploadedFile("extra.txt", b"data")
        extra = AuditAttachment(audit=audit, response=response, file=extra_file)

        with pytest.raises(ValidationError) as exc:
            extra.full_clean()

    assert "ответа" in str(exc.value)


@pytest.mark.django_db
def test_attachment_enforces_per_audit_limit(audit_factory) -> None:
    audit = audit_factory()
    response_one = AuditResponseFactory(audit=audit)
    response_two = AuditResponseFactory(audit=audit)

    with override_settings(
        AUDIT_ATTACHMENT_LIMITS={
            "max_size_bytes": 1024 * 1024,
            "max_per_response": 5,
            "max_per_audit": 2,
        }
    ):
        AuditAttachmentFactory(audit=audit, response=response_one)
        AuditAttachmentFactory(audit=audit, response=response_two)

        another_response = AuditResponseFactory(audit=audit)
        new_file = SimpleUploadedFile("another.txt", b"data")
        extra = AuditAttachment(audit=audit, response=another_response, file=new_file)

        with pytest.raises(ValidationError) as exc:
            extra.full_clean()

    assert "аудита" in str(exc.value)


@pytest.mark.django_db
def test_attachment_allows_audit_level_files_without_response() -> None:
    audit = AuditFactory()
    file_obj = SimpleUploadedFile("note.txt", b"data")

    with override_settings(
        AUDIT_ATTACHMENT_LIMITS={
            "max_size_bytes": 1024 * 1024,
            "max_per_response": 1,
            "max_per_audit": 2,
        }
    ):
        attachment = AuditAttachment(audit=audit, response=None, file=file_obj)
        attachment.full_clean()


@pytest.mark.django_db
def test_attachment_rejects_response_from_another_audit(audit_factory) -> None:
    primary_audit = audit_factory()
    other_audit = audit_factory()
    foreign_response = AuditResponseFactory(audit=other_audit)
    file_obj = SimpleUploadedFile("foreign.txt", b"data")

    with override_settings(
        AUDIT_ATTACHMENT_LIMITS={
            "max_size_bytes": 1024 * 1024,
            "max_per_response": 5,
            "max_per_audit": 5,
        }
    ):
        attachment = AuditAttachment(
            audit=primary_audit,
            response=foreign_response,
            file=file_obj,
        )

        with pytest.raises(ValidationError) as exc:
            attachment.full_clean()

    assert "ответу текущего аудита" in str(exc.value)

