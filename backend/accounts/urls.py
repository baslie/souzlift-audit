"""URL patterns for the accounts app."""
from __future__ import annotations

from django.urls import path

from .views import (
    AccountDashboardView,
    AccountLoginView,
    AccountLogoutView,
    AccountPasswordChangeDoneView,
    AccountPasswordChangeView,
    ForcePasswordChangeView,
)

app_name = "accounts"

urlpatterns = [
    path("login/", AccountLoginView.as_view(), name="login"),
    path("logout/", AccountLogoutView.as_view(), name="logout"),
    path("dashboard/", AccountDashboardView.as_view(), name="dashboard"),
    path("password/change/", AccountPasswordChangeView.as_view(), name="password-change"),
    path(
        "password/change/done/",
        AccountPasswordChangeDoneView.as_view(),
        name="password-change-done",
    ),
    path("password/force/", ForcePasswordChangeView.as_view(), name="force-password-change"),
]
