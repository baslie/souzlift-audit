from __future__ import annotations

import json
import uuid

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from audits.models import Audit, AuditAttachment, AuditResponse, OfflineSyncBatch
from catalog.models import (
    Building,
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    Elevator,
    ReviewStatus,
)

from .test_attachment_access import ProtectedMediaTestCase, SMALL_GIF


class OfflineSyncDataTests(TestCase):
    """Integration tests for processing offline sync JSON payloads."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.auditor = UserModel.objects.create_user(username="auditor", password="Secret123!")
        self.auditor.profile.mark_password_changed()

        category = ChecklistCategory.objects.create(code="safety", name="Безопасность", order=1)
        section = ChecklistSection.objects.create(category=category, title="Общие", order=1)
        self.question = ChecklistQuestion.objects.create(section=section, text="Исправность", order=1)

        self.client.force_login(self.auditor)

    def test_sync_creates_catalog_records_and_audit(self) -> None:
        url = reverse("offline-sync")
        payload = {
            "device_id": "device-1",
            "catalog": {
                "buildings": [
                    {
                        "client_id": "b-1",
                        "address": "Советская, 10",
                        "entrance": "1",
                        "notes": "Добавлено офлайн",
                    }
                ],
                "elevators": [
                    {
                        "client_id": "e-1",
                        "identifier": "EL-001",
                        "description": "Тестовый лифт",
                        "status": Elevator.Status.IN_SERVICE,
                        "building_client_id": "b-1",
                    }
                ],
            },
            "audits": [
                {
                    "client_id": "a-1",
                    "elevator_client_id": "e-1",
                    "planned_date": "2024-01-01",
                    "started_at": "2024-01-01T08:00:00+00:00",
                    "finished_at": "2024-01-01T08:30:00+00:00",
                    "status": Audit.Status.SUBMITTED,
                    "object_info": {"manager": "Иванов"},
                    "responses": [
                        {
                            "client_id": "r-1",
                            "question_id": self.question.pk,
                            "score": 5,
                            "comment": "Все отлично",
                            "is_flagged": False,
                        }
                    ],
                }
            ],
        }

        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body.get("status"), "ok")
        self.assertEqual(body.get("device_id"), "device-1")

        buildings = body.get("catalog", {}).get("buildings", [])
        self.assertEqual(len(buildings), 1)
        new_building_id = buildings[0]["id"]
        new_building = Building.objects.get(pk=new_building_id)
        self.assertEqual(new_building.address, "Советская, 10")
        self.assertEqual(new_building.created_by, self.auditor)
        self.assertEqual(new_building.review_status, ReviewStatus.PENDING)

        elevators = body.get("catalog", {}).get("elevators", [])
        self.assertEqual(len(elevators), 1)
        new_elevator_id = elevators[0]["id"]
        new_elevator = Elevator.objects.get(pk=new_elevator_id)
        self.assertEqual(new_elevator.identifier, "EL-001")
        self.assertEqual(new_elevator.created_by, self.auditor)
        self.assertEqual(new_elevator.building_id, new_building_id)

        audits = body.get("audits", [])
        self.assertEqual(len(audits), 1)
        audit_payload = audits[0]
        audit = Audit.objects.get(pk=audit_payload["id"])
        self.assertEqual(audit.created_by, self.auditor)
        self.assertEqual(audit.status, Audit.Status.SUBMITTED)
        self.assertEqual(audit.object_info, {"manager": "Иванов"})
        self.assertEqual(audit.total_score, 5)
        self.assertIsNotNone(audit.started_at)
        self.assertIsNotNone(audit.finished_at)

        responses = audit_payload.get("responses", [])
        self.assertEqual(len(responses), 1)
        response_obj = AuditResponse.objects.get(pk=responses[0]["id"])
        self.assertEqual(response_obj.score, 5)
        self.assertTrue(response_obj.is_offline_cached)

        batches = OfflineSyncBatch.objects.all()
        self.assertEqual(batches.count(), 1)
        batch = batches.first()
        assert batch is not None
        self.assertEqual(batch.status, OfflineSyncBatch.Status.APPLIED)
        self.assertEqual(batch.device_id, "device-1")
        self.assertEqual(batch.payload.get("kind"), "data")


class OfflineSyncAttachmentTests(ProtectedMediaTestCase):
    """Ensure attachments uploaded via offline sync are stored correctly."""

    def setUp(self) -> None:
        super().setUp()
        UserModel = get_user_model()
        self.auditor = UserModel.objects.create_user(username="auditor2", password="Secret123!")
        self.auditor.profile.mark_password_changed()

        category = ChecklistCategory.objects.create(code="tech", name="Техника", order=1)
        section = ChecklistSection.objects.create(category=category, title="Раздел", order=1)
        self.question = ChecklistQuestion.objects.create(section=section, text="Исправность", order=1)

        self.client.force_login(self.auditor)

        # Create initial audit via sync to reuse response IDs.
        url = reverse("offline-sync")
        initial_payload = {
            "device_id": "device-2",
            "catalog": {
                "buildings": [
                    {"client_id": "b-2", "address": "Ленина, 15"},
                ],
                "elevators": [
                    {
                        "client_id": "e-2",
                        "identifier": "EL-200",
                        "building_client_id": "b-2",
                    }
                ],
            },
            "audits": [
                {
                    "client_id": "a-2",
                    "elevator_client_id": "e-2",
                    "status": Audit.Status.SUBMITTED,
                    "responses": [
                        {
                            "client_id": "r-2",
                            "question_id": self.question.pk,
                            "score": 4,
                        }
                    ],
                }
            ],
        }
        response = self.client.post(url, data=json.dumps(initial_payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.response_id = data["audits"][0]["responses"][0]["id"]

    def test_upload_attachment(self) -> None:
        url = reverse("offline-sync")
        offline_uuid = uuid.uuid4()
        payload = {
            "device_id": "device-2",
            "attachment": {
                "response_id": self.response_id,
                "caption": "Фото",
                "offline_uuid": str(offline_uuid),
            },
        }

        file = SimpleUploadedFile("photo.gif", SMALL_GIF, content_type="image/gif")
        response = self.client.post(
            url,
            data={"payload": json.dumps(payload), "file": file},
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body.get("status"), "ok")
        attachment_id = body.get("attachment", {}).get("id")
        self.assertIsNotNone(attachment_id)

        attachment = AuditAttachment.objects.get(pk=attachment_id)
        self.assertEqual(attachment.response_id, self.response_id)
        self.assertEqual(attachment.offline_uuid, uuid.UUID(str(offline_uuid)))
        self.assertEqual(attachment.caption, "Фото")
        self.assertGreater(attachment.stored_size, 0)

        batches = OfflineSyncBatch.objects.filter(payload__kind="attachment")
        self.assertEqual(batches.count(), 1)
        batch = batches.first()
        assert batch is not None
        self.assertEqual(batch.status, OfflineSyncBatch.Status.APPLIED)
        self.assertEqual(batch.device_id, "device-2")

        # Duplicate upload with the same offline UUID returns existing attachment without new batch.
        duplicate_response = self.client.post(
            url,
            data={"payload": json.dumps(payload), "file": SimpleUploadedFile("photo.gif", SMALL_GIF)},
        )
        self.assertEqual(duplicate_response.status_code, 200)
        duplicate_body = duplicate_response.json()
        self.assertTrue(duplicate_body.get("duplicate"))
        self.assertEqual(
            OfflineSyncBatch.objects.filter(payload__kind="attachment").count(),
            1,
        )
