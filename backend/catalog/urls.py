"""URL patterns for catalog management views."""
from __future__ import annotations

from django.urls import path

from .views import (
    BuildingCreateView,
    BuildingListView,
    BuildingModerationView,
    BuildingUpdateView,
    ChecklistCategoryCreateView,
    ChecklistCategoryDeleteView,
    ChecklistCategoryReorderView,
    ChecklistCategoryUpdateView,
    ChecklistOverviewView,
    ChecklistQuestionCreateView,
    ChecklistQuestionDeleteView,
    ChecklistQuestionReorderView,
    ChecklistQuestionUpdateView,
    ChecklistSectionCreateView,
    ChecklistSectionDeleteView,
    ChecklistSectionReorderView,
    ChecklistSectionUpdateView,
    ElevatorCreateView,
    ElevatorListView,
    ElevatorModerationView,
    ElevatorUpdateView,
    ScoreOptionCreateView,
    ScoreOptionDeleteView,
    ScoreOptionReorderView,
    ScoreOptionUpdateView,
)

app_name = "catalog"

urlpatterns = [
    path("checklist/", ChecklistOverviewView.as_view(), name="checklist-overview"),
    path("checklist/categories/create/", ChecklistCategoryCreateView.as_view(), name="checklist-category-create"),
    path(
        "checklist/categories/<int:pk>/edit/",
        ChecklistCategoryUpdateView.as_view(),
        name="checklist-category-update",
    ),
    path(
        "checklist/categories/<int:pk>/delete/",
        ChecklistCategoryDeleteView.as_view(),
        name="checklist-category-delete",
    ),
    path(
        "checklist/categories/<int:pk>/move/",
        ChecklistCategoryReorderView.as_view(),
        name="checklist-category-move",
    ),
    path(
        "checklist/categories/<int:category_pk>/sections/create/",
        ChecklistSectionCreateView.as_view(),
        name="checklist-section-create",
    ),
    path(
        "checklist/sections/<int:pk>/edit/",
        ChecklistSectionUpdateView.as_view(),
        name="checklist-section-update",
    ),
    path(
        "checklist/sections/<int:pk>/delete/",
        ChecklistSectionDeleteView.as_view(),
        name="checklist-section-delete",
    ),
    path(
        "checklist/sections/<int:pk>/move/",
        ChecklistSectionReorderView.as_view(),
        name="checklist-section-move",
    ),
    path(
        "checklist/sections/<int:section_pk>/questions/create/",
        ChecklistQuestionCreateView.as_view(),
        name="checklist-question-create",
    ),
    path(
        "checklist/questions/<int:pk>/edit/",
        ChecklistQuestionUpdateView.as_view(),
        name="checklist-question-update",
    ),
    path(
        "checklist/questions/<int:pk>/delete/",
        ChecklistQuestionDeleteView.as_view(),
        name="checklist-question-delete",
    ),
    path(
        "checklist/questions/<int:pk>/move/",
        ChecklistQuestionReorderView.as_view(),
        name="checklist-question-move",
    ),
    path(
        "checklist/questions/<int:question_pk>/options/create/",
        ScoreOptionCreateView.as_view(),
        name="checklist-option-create",
    ),
    path(
        "checklist/options/<int:pk>/edit/",
        ScoreOptionUpdateView.as_view(),
        name="checklist-option-update",
    ),
    path(
        "checklist/options/<int:pk>/delete/",
        ScoreOptionDeleteView.as_view(),
        name="checklist-option-delete",
    ),
    path(
        "checklist/options/<int:pk>/move/",
        ScoreOptionReorderView.as_view(),
        name="checklist-option-move",
    ),
    path("buildings/", BuildingListView.as_view(), name="building-list"),
    path("buildings/create/", BuildingCreateView.as_view(), name="building-create"),
    path("buildings/<int:pk>/edit/", BuildingUpdateView.as_view(), name="building-update"),
    path("buildings/<int:pk>/moderate/", BuildingModerationView.as_view(), name="building-moderate"),
    path("elevators/", ElevatorListView.as_view(), name="elevator-list"),
    path("elevators/create/", ElevatorCreateView.as_view(), name="elevator-create"),
    path("elevators/<int:pk>/edit/", ElevatorUpdateView.as_view(), name="elevator-update"),
    path("elevators/<int:pk>/moderate/", ElevatorModerationView.as_view(), name="elevator-moderate"),
]

