"""URL patterns for catalog management views."""
from __future__ import annotations

from django.urls import path

from .views import (
    BuildingCreateView,
    BuildingDeleteView,
    BuildingImportView,
    BuildingListView,
    BuildingUpdateView,
    ElevatorCreateView,
    ElevatorDeleteView,
    ElevatorImportView,
    ElevatorListView,
    ElevatorUpdateView,
)

app_name = "catalog"

urlpatterns = [
    path("buildings/", BuildingListView.as_view(), name="building-list"),
    path("buildings/create/", BuildingCreateView.as_view(), name="building-create"),
    path("buildings/import/", BuildingImportView.as_view(), name="building-import"),
    path("buildings/<int:pk>/edit/", BuildingUpdateView.as_view(), name="building-update"),
    path("buildings/<int:pk>/delete/", BuildingDeleteView.as_view(), name="building-delete"),
    path("elevators/", ElevatorListView.as_view(), name="elevator-list"),
    path("elevators/create/", ElevatorCreateView.as_view(), name="elevator-create"),
    path("elevators/import/", ElevatorImportView.as_view(), name="elevator-import"),
    path("elevators/<int:pk>/edit/", ElevatorUpdateView.as_view(), name="elevator-update"),
    path("elevators/<int:pk>/delete/", ElevatorDeleteView.as_view(), name="elevator-delete"),
]
