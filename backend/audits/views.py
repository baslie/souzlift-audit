"""Views for secure delivery of audit attachments."""
from __future__ import annotations

import mimetypes
import os

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.signing import BadSignature, SignatureExpired
from django.http import FileResponse, Http404, HttpResponse
from django.views import View

from accounts.permissions import is_admin

from .models import AuditAttachment
from .tokens import read_attachment_token


class AttachmentDownloadView(LoginRequiredMixin, View):
    """Serve audit attachments through authenticated, signed URLs."""

    http_method_names = ["get"]

    def get(self, request, token: str, *args, **kwargs) -> HttpResponse:  # type: ignore[override]
        try:
            attachment_id = read_attachment_token(token)
        except SignatureExpired as exc:
            raise Http404("Ссылка для скачивания истекла.") from exc
        except BadSignature as exc:
            raise Http404("Недействительная ссылка для скачивания.") from exc

        attachment = (
            AuditAttachment.objects.select_related("response__audit__created_by")
            .filter(pk=attachment_id)
            .first()
        )
        if attachment is None or not attachment.file:
            raise Http404("Вложение не найдено.")

        audit = attachment.response.audit
        user = request.user
        if not self._user_can_access(user, audit.created_by_id):
            raise Http404("Вложение не найдено.")

        storage = attachment.file.storage
        if not storage.exists(attachment.file.name):
            raise Http404("Файл вложения отсутствует на сервере.")

        filename = os.path.basename(attachment.file.name)
        content_type, _ = mimetypes.guess_type(filename)
        file_handle = attachment.file.open("rb")

        response = FileResponse(file_handle, as_attachment=True, filename=filename)
        if content_type:
            response.headers["Content-Type"] = content_type
        return response

    @staticmethod
    def _user_can_access(user: object, author_id: int | None) -> bool:
        if not hasattr(user, "is_authenticated") or not user.is_authenticated:
            return False
        if is_admin(user):
            return True
        return getattr(user, "pk", None) == author_id


__all__ = ["AttachmentDownloadView"]
