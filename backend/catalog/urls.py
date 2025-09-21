"""URL patterns for catalog management views."""
from __future__ import annotations

from django.urls import path

from .views import (
    BuildingCreateView,
    BuildingListView,
    BuildingUpdateView,
    ElevatorCreateView,
    ElevatorListView,
    ElevatorUpdateView,
)

app_name = "catalog"

urlpatterns = [
    path("buildings/", BuildingListView.as_view(), name="building-list"),
    path("buildings/create/", BuildingCreateView.as_view(), name="building-create"),
    path("buildings/<int:pk>/edit/", BuildingUpdateView.as_view(), name="building-update"),
    path("elevators/", ElevatorListView.as_view(), name="elevator-list"),
    path("elevators/create/", ElevatorCreateView.as_view(), name="elevator-create"),
    path("elevators/<int:pk>/edit/", ElevatorUpdateView.as_view(), name="elevator-update"),
]
