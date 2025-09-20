"""Custom views for project-wide endpoints."""
from __future__ import annotations

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import Http404, HttpRequest, HttpResponse
from django.views import View


class ServiceWorkerView(View):
    """Serve the precompiled service worker script from the static directory."""

    static_path = "js/service-worker.js"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:  # noqa: D401
        try:
            asset_path = finders.find(self.static_path)
            if asset_path:
                with open(asset_path, "rb") as file_handle:
                    content = file_handle.read()
            else:
                with staticfiles_storage.open(self.static_path) as file_handle:
                    content = file_handle.read()
        except FileNotFoundError as exc:
            raise Http404("Service worker not found.") from exc

        response = HttpResponse(content, content_type="application/javascript")
        response["Service-Worker-Allowed"] = "/"
        return response


__all__ = ["ServiceWorkerView"]
