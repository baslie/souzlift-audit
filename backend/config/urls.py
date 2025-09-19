"""Root URL configuration for the Союзлифт Аудит project."""
from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from audits.api import CatalogSnapshotView, OfflineSyncView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("catalog/", include("catalog.urls")),
    path("audits/", include("audits.urls")),
    path("api/offline-sync/", OfflineSyncView.as_view(), name="offline-sync"),
    path(
        "api/catalog/snapshot/",
        CatalogSnapshotView.as_view(),
        name="catalog-snapshot",
    ),
    path("", RedirectView.as_view(pattern_name="accounts:dashboard", permanent=False), name="home"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
