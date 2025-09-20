"""Integration-style tests covering primary business flows."""
from __future__ import annotations

from django.core.exceptions import ValidationError
import pytest

from audits.models import Audit
from catalog.models import Building, Elevator, ReviewStatus

from .factories import (
    AdminUserFactory,
    AuditFactory,
    AuditResponseFactory,
    AuditorUserFactory,
    ChecklistQuestionFactory,
    ElevatorFactory,
)


@pytest.mark.django_db
class TestAuditCreationFlow:
    """Validate creating a new audit with minimal input."""

    def test_auditor_can_create_audit_for_existing_elevator(self) -> None:
        auditor = AuditorUserFactory()
        elevator = ElevatorFactory()

        audit = Audit.objects.create(elevator=elevator, created_by=auditor)

        assert audit.status == Audit.Status.DRAFT
        assert audit.created_by == auditor
        assert audit.elevator == elevator
        assert audit.total_score == 0
        assert audit.started_at is None
        assert audit.finished_at is None
        assert audit.object_info == {}


@pytest.mark.django_db
class TestCatalogModerationFlow:
    """Ensure moderated catalog records follow visibility rules."""

    def test_building_and_elevator_moderation_updates_visibility(self) -> None:
        admin = AdminUserFactory()
        auditor = AuditorUserFactory()
        other_auditor = AuditorUserFactory()

        building = Building.objects.create(address="Ленина, 10", created_by=auditor)
        elevator = Elevator.objects.create(
            building=building,
            identifier="EL-42",
            created_by=auditor,
        )

        assert building.review_status == ReviewStatus.PENDING
        assert elevator.review_status == ReviewStatus.PENDING

        # Pending entries should only be visible to creators and administrators.
        assert building in Building.objects.visible_for_user(auditor)
        assert building not in Building.objects.visible_for_user(other_auditor)
        assert elevator in Elevator.objects.visible_for_user(auditor)
        assert elevator not in Elevator.objects.visible_for_user(other_auditor)
        assert building in Building.objects.visible_for_user(admin)
        assert elevator in Elevator.objects.visible_for_user(admin)

        # Approving records promotes them to the shared catalog and sets metadata.
        building.approve(admin)
        elevator.approve(admin)
        building.refresh_from_db()
        elevator.refresh_from_db()

        assert building.review_status == ReviewStatus.APPROVED
        assert building.verified_by == admin
        assert building.verified_at is not None
        assert elevator.review_status == ReviewStatus.APPROVED
        assert elevator.verified_by == admin
        assert elevator.verified_at is not None

        other_visibility = Elevator.objects.visible_for_user(other_auditor)
        assert elevator in other_visibility

        # Returning the elevator to moderation hides it again from other auditors.
        elevator.send_to_review()
        elevator.refresh_from_db()
        assert elevator.review_status == ReviewStatus.PENDING
        assert elevator.verified_by is None
        assert elevator.verified_at is None
        assert elevator not in Elevator.objects.visible_for_user(other_auditor)


@pytest.mark.django_db
class TestAuditStatusTransitions:
    """Cover status workflow and automatic timestamps for audits."""

    def test_status_progression_sets_timestamps_and_prevents_reverts(self) -> None:
        admin = AdminUserFactory()
        auditor = AuditorUserFactory()
        audit = AuditFactory(created_by=auditor)

        audit.start(actor=auditor)
        assert audit.status == Audit.Status.IN_PROGRESS
        assert audit.started_at is not None
        started_at = audit.started_at
        assert audit.finished_at is None

        audit.submit(actor=auditor)
        assert audit.status == Audit.Status.SUBMITTED
        assert audit.finished_at is not None
        finished_at = audit.finished_at

        audit.mark_reviewed(actor=admin)
        assert audit.status == Audit.Status.REVIEWED
        assert audit.started_at == started_at
        assert audit.finished_at == finished_at

        # Reverting to a previous status is not allowed and raises a validation error.
        audit.status = Audit.Status.IN_PROGRESS
        with pytest.raises(ValidationError):
            audit.save(update_fields=["status"])


@pytest.mark.django_db
class TestAuditScoreCalculations:
    """Ensure total score stays in sync with responses."""

    def test_total_score_updates_on_response_changes(self) -> None:
        audit = AuditFactory()
        question_high = ChecklistQuestionFactory(default_score_options=[5, 3], max_score=5)
        question_low = ChecklistQuestionFactory(default_score_options=[4, 2], max_score=4)

        response_one = AuditResponseFactory(audit=audit, question=question_high, score=3)
        response_two = AuditResponseFactory(audit=audit, question=question_low, score=2)

        audit.refresh_from_db()
        assert audit.total_score == 5

        response_one.score = 5
        response_one.save(update_fields=["score"])
        audit.refresh_from_db()
        assert audit.total_score == 7

        response_two.score = 4
        response_two.save(update_fields=["score"])
        audit.refresh_from_db()
        assert audit.total_score == 9

        # Manual recalculation should return the same aggregated value.
        recalculated = Audit.recalculate_total_score_for(audit.pk)
        assert recalculated == 9
        audit.refresh_from_db()
        assert audit.total_score == 9
