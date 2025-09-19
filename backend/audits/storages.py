"""Custom storage backends for the audits application."""
from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.functional import LazyObject, empty


class _ProtectedFileSystemStorage(FileSystemStorage):
    """Stores files under the project controlled directory without public URLs."""

    def __init__(self) -> None:
        root = Path(settings.PROTECTED_MEDIA_ROOT)
        os.makedirs(root, exist_ok=True)
        super().__init__(location=str(root), base_url=None)

    def url(self, name: str) -> str:  # pragma: no cover - defensive override
        raise NotImplementedError("Direct URLs are disabled for protected media files.")


class ProtectedMediaStorage(LazyObject):
    """Lazy wrapper allowing runtime reconfiguration of the storage location."""

    def _setup(self) -> None:
        self._wrapped = _ProtectedFileSystemStorage()

    def reset(self) -> None:
        """Force the next access to recreate the wrapped storage instance."""

        self._wrapped = empty


protected_media_storage = ProtectedMediaStorage()


def reset_protected_media_storage() -> None:
    """Helper used in tests to rebuild the storage with fresh settings."""

    protected_media_storage.reset()


__all__ = ["protected_media_storage", "reset_protected_media_storage"]
