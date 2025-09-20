"""Integration tests covering offline workflow and service worker delivery."""
from __future__ import annotations

import json
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from audits.models import Audit, AuditAttachment, AuditResponse, OfflineSyncBatch
from audits.storages import reset_protected_media_storage
from config.views import ServiceWorkerView

from .factories import ChecklistQuestionFactory

SMALL_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00"
    b"\x01\x00\x00\x02\x02D\x01\x00;"
)


@pytest.mark.django_db
def test_offline_sync_round_trip(client, settings, tmp_path):
    """Ensure auditor can sync catalog, audits and attachments sequentially."""

    storage_root = tmp_path / "protected"
    storage_root.mkdir(exist_ok=True)
    settings.PROTECTED_MEDIA_ROOT = str(storage_root)
    reset_protected_media_storage()

    try:
        UserModel = get_user_model()
        auditor = UserModel.objects.create_user(username='offline-auditor', password='Secret123!')
        from accounts.permissions import is_auditor as _is_auditor

        assert auditor.profile.role == auditor.profile.Roles.AUDITOR
        assert auditor.profile.is_auditor
        assert _is_auditor(auditor)
        auditor.profile.mark_password_changed()
        assert client.login(username=auditor.username, password='Secret123!')
        question = ChecklistQuestionFactory(default_score_options=[5, 3])

        url = reverse("offline-sync")
        data_payload = {
            "device_id": "device-42",
            "catalog": {
                "buildings": [
                    {
                        "client_id": "b-local",
                        "address": "Улица Примеров, 5",
                        "entrance": "2",
                        "notes": "Добавлено из офлайна",
                    }
                ],
                "elevators": [
                    {
                        "client_id": "e-local",
                        "identifier": "EL-999",
                        "description": "Лифт из офлайн-пакета",
                        "status": "in_service",
                        "building_client_id": "b-local",
                    }
                ],
            },
            "audits": [
                {
                    "client_id": "a-local",
                    "elevator_client_id": "e-local",
                    "status": Audit.Status.SUBMITTED,
                    "started_at": "2024-05-01T08:00:00+00:00",
                    "finished_at": "2024-05-01T09:15:00+00:00",
                    "object_info": {"manager": "Иван Иванов"},
                    "responses": [
                        {
                            "client_id": "r-local",
                            "question_id": question.pk,
                            "score": 5,
                            "comment": "Всё соответствует нормам",
                            "is_flagged": False,
                        }
                    ],
                }
            ],
        }

        response = client.post(
            url,
            data=json.dumps(data_payload),
            content_type="application/json",
        )
        if response.status_code != 200:
            try:
                details = response.json()
            except ValueError:
                details = response.content.decode("utf-8")
            pytest.fail(f"Unexpected response {response.status_code}: {details}")
        body = response.json()
        assert body["status"] == "ok"
        assert body["device_id"] == "device-42"
        assert body["catalog"]["buildings"][0]["client_id"] == "b-local"
        assert body["catalog"]["elevators"][0]["client_id"] == "e-local"

        snapshot = body.get("catalog_snapshot")
        assert snapshot is not None
        assert "checklist" in snapshot
        assert "audit_filters" in snapshot

        checklist_payload = body.get("checklist")
        assert checklist_payload is not None
        if checklist_payload["categories"]:
            first_category = checklist_payload["categories"][0]
            if first_category["sections"]:
                first_section = first_category["sections"][0]
                if first_section["questions"]:
                    question_meta = first_section["questions"][0]
                    assert "category_id" in question_meta
                    assert "section_id" in question_meta

        filters_payload = body.get("audit_filters")
        assert filters_payload is not None
        assert "status" in filters_payload
        assert "period" in filters_payload
        assert "review" not in filters_payload

        audit_mapping = body["audits"][0]
        audit_id = audit_mapping["id"]
        response_mapping = audit_mapping["responses"][0]
        response_id = response_mapping["id"]

        audit_obj = Audit.objects.get(pk=audit_id)
        assert audit_obj.created_by == auditor
        assert audit_obj.status == Audit.Status.SUBMITTED
        assert audit_obj.object_info == {"manager": "Иван Иванов"}
        assert audit_obj.total_score == 5

        response_obj = AuditResponse.objects.get(pk=response_id)
        assert response_obj.is_offline_cached
        assert response_obj.score == 5
        assert response_obj.comment == "Всё соответствует нормам"

        data_batches = OfflineSyncBatch.objects.filter(payload__kind="data", device_id="device-42")
        assert data_batches.count() == 1
        data_batch = data_batches.first()
        assert data_batch is not None
        assert data_batch.status == OfflineSyncBatch.Status.APPLIED
        assert data_batch.response_status == 200

        offline_uuid = uuid.uuid4()
        attachment_payload = {
            "device_id": "device-42",
            "attachment": {
                "response_id": response_id,
                "caption": "Фото витрины",
                "offline_uuid": str(offline_uuid),
            },
        }

        upload_response = client.post(
            url,
            data={
                "payload": json.dumps(attachment_payload),
                "file": SimpleUploadedFile("photo.gif", SMALL_GIF, content_type="image/gif"),
            },
        )
        assert upload_response.status_code == 201
        upload_body = upload_response.json()
        assert upload_body["status"] == "ok"
        attachment_data = upload_body["attachment"]
        attachment_id = attachment_data["id"]

        attachment = AuditAttachment.objects.get(pk=attachment_id)
        assert attachment.response_id == response_id
        assert attachment.caption == "Фото витрины"
        assert str(attachment.offline_uuid) == str(offline_uuid)
        assert attachment.stored_size > 0

        attachment_batches = OfflineSyncBatch.objects.filter(
            payload__kind="attachment", device_id="device-42"
        )
        assert attachment_batches.count() == 1
        attachment_batch = attachment_batches.first()
        assert attachment_batch is not None
        assert attachment_batch.status == OfflineSyncBatch.Status.APPLIED
        assert attachment_batch.response_status == 201
    finally:
        reset_protected_media_storage()


def test_service_worker_served(client):
    """Service worker endpoint should stream pre-built bundle with correct headers."""

    asset_path = finders.find(ServiceWorkerView.static_path)
    assert asset_path, "Service worker asset should exist in static directories."

    response = client.get(reverse("service-worker"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/javascript")
    assert response["Service-Worker-Allowed"] == "/"

    with open(asset_path, "rb") as file_handle:
        expected_content = file_handle.read()

    assert response.content == expected_content


def test_service_worker_missing_file_returns_404(client, monkeypatch):
    """The view should return 404 when the underlying static asset is absent."""

    monkeypatch.setattr("config.views.finders.find", lambda path: None)

    class MissingStaticStorage:
        def open(self, path: str):
            raise FileNotFoundError

    monkeypatch.setattr("config.views.staticfiles_storage", MissingStaticStorage())
    response = client.get(reverse("service-worker"))
    assert response.status_code == 404
