"""Utilities for issuing and validating signed URLs for attachments."""
from __future__ import annotations

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

_ATTACHMENT_SALT = "audits.AttachmentToken"


def _get_signer() -> TimestampSigner:
    return TimestampSigner(salt=_ATTACHMENT_SALT)


def build_attachment_token(attachment_id: int) -> str:
    """Return a signed token that encodes the attachment identifier."""

    signer = _get_signer()
    return signer.sign(str(attachment_id))


def read_attachment_token(token: str) -> int:
    """Validate a token and return the encoded attachment identifier."""

    signer = _get_signer()
    max_age = getattr(settings, "AUDIT_ATTACHMENT_URL_MAX_AGE", None)
    if isinstance(max_age, int) and max_age <= 0:
        max_age = None

    raw_value = signer.unsign(token, max_age=max_age)
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive branch
        raise BadSignature("Attachment token payload is invalid.") from exc


__all__ = ["BadSignature", "SignatureExpired", "build_attachment_token", "read_attachment_token"]
