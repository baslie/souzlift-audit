"""REST endpoints for the audits application."""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views import View

from accounts.permissions import is_admin, is_auditor
from audits.models import Audit, AuditAttachment, AuditResponse, OfflineSyncBatch
from catalog.models import Building, Elevator, ReviewStatus, ChecklistQuestion

logger = logging.getLogger(__name__)


class OfflineSyncView(LoginRequiredMixin, View):
    """Handle offline synchronisation payloads from auditor devices."""

    http_method_names = ["post"]

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:  # type: ignore[override]
        user = request.user
        if not (is_auditor(user) or is_admin(user)):
            return self._json_error("forbidden", "Недостаточно прав для синхронизации.", status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> JsonResponse:
        content_type = (request.content_type or "").split(";")[0].strip().lower()
        if content_type == "application/json":
            try:
                payload = json.loads(request.body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                return self._json_error("invalid_json", "Не удалось прочитать данные синхронизации.", errors={"detail": str(exc)})
            return self._handle_data_payload(request, payload)

        if content_type == "multipart/form-data":
            payload_raw = request.POST.get("payload")
            if not payload_raw:
                return self._json_error("invalid_payload", "Отсутствует описание вложения в поле payload.")
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError as exc:
                return self._json_error("invalid_json", "Некорректный формат JSON для вложения.", errors={"detail": str(exc)})
            return self._handle_attachment_payload(request, payload)

        return self._json_error(
            "unsupported_media_type",
            "Поддерживаются только application/json и multipart/form-data.",
            status=415,
        )

    # --- payload handlers -------------------------------------------------

    def _handle_data_payload(self, request: HttpRequest, payload: Any) -> JsonResponse:
        if not isinstance(payload, Mapping):
            return self._json_error("invalid_payload", "Ожидался объект JSON с данными синхронизации.")

        device_id = self._clean_string(payload.get("device_id"))
        if not device_id:
            return self._json_error("invalid_payload", "Не указан идентификатор устройства (device_id).")

        batch = OfflineSyncBatch.objects.create(
            user=request.user,
            device_id=device_id,
            payload=self._compact_batch_payload(payload, kind="data"),
        )

        try:
            with transaction.atomic():
                mapping = self._apply_data_payload(request, payload)
        except ValidationError as exc:
            batch.mark_error(self._serialize_validation_error(exc))
            return self._json_error("validation_error", "Не удалось применить данные синхронизации.", errors=batch.error_details, status=400)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Offline sync failed")
            batch.mark_error({"type": exc.__class__.__name__, "message": str(exc)})
            return self._json_error("processing_error", "Во время синхронизации произошла непредвиденная ошибка.", status=500)

        batch.mark_applied()
        response_payload = {
            "status": "ok",
            "device_id": device_id,
            "catalog": mapping["catalog"],
            "audits": mapping["audits"],
        }
        return JsonResponse(response_payload, status=200)

    def _handle_attachment_payload(self, request: HttpRequest, payload: Any) -> JsonResponse:
        if not isinstance(payload, Mapping):
            return self._json_error("invalid_payload", "Ожидался объект JSON с метаданными вложения.")

        device_id = self._clean_string(payload.get("device_id"))
        if not device_id:
            return self._json_error("invalid_payload", "Не указан идентификатор устройства (device_id).")

        metadata = payload.get("attachment")
        if not isinstance(metadata, Mapping):
            return self._json_error("invalid_payload", "Ожидался объект attachment с описанием файла.")

        file_obj = request.FILES.get("file")
        if file_obj is None:
            return self._json_error("invalid_payload", "Файл вложения не передан.")

        response_id = metadata.get("response_id")
        if not response_id:
            return self._json_error("invalid_payload", "Не указан идентификатор ответа (response_id).")

        try:
            response_pk = int(response_id)
        except (TypeError, ValueError):
            return self._json_error("invalid_payload", "Идентификатор ответа должен быть целым числом.")

        response = (
            AuditResponse.objects.select_related("audit", "audit__created_by")
            .filter(pk=response_pk)
            .first()
        )
        if response is None or response.audit.created_by_id != request.user.id:
            return self._json_error("not_found", "Ответ не найден или недоступен.", status=404)

        caption = self._clean_string(metadata.get("caption"))
        offline_uuid_raw = metadata.get("offline_uuid")
        offline_uuid = None
        if offline_uuid_raw:
            try:
                offline_uuid = str(uuid.UUID(str(offline_uuid_raw)))
            except (TypeError, ValueError):
                return self._json_error("invalid_payload", "Поле offline_uuid имеет некорректный формат UUID.")

        existing_attachment = None
        if offline_uuid:
            existing_attachment = (
                AuditAttachment.objects.filter(offline_uuid=offline_uuid, response=response).first()
            )
            if existing_attachment is not None:
                return JsonResponse(
                    {
                        "status": "ok",
                        "device_id": device_id,
                        "attachment": {
                            "id": existing_attachment.pk,
                            "response_id": response_pk,
                            "offline_uuid": existing_attachment.offline_uuid,
                        },
                        "duplicate": True,
                    },
                    status=200,
                )

        batch = OfflineSyncBatch.objects.create(
            user=request.user,
            device_id=device_id,
            payload={
                "kind": "attachment",
                "response_id": response_pk,
                "offline_uuid": offline_uuid,
            },
        )

        try:
            with transaction.atomic():
                attachment = AuditAttachment(
                    response=response,
                    file=file_obj,
                    caption=caption or "",
                    offline_uuid=offline_uuid,
                )
                attachment._log_actor = request.user
                attachment.save()
        except ValidationError as exc:
            batch.mark_error(self._serialize_validation_error(exc))
            return self._json_error("validation_error", "Не удалось сохранить вложение.", errors=batch.error_details, status=400)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Attachment sync failed")
            batch.mark_error({"type": exc.__class__.__name__, "message": str(exc)})
            return self._json_error("processing_error", "Во время загрузки вложения произошла ошибка.", status=500)

        batch.mark_applied()
        return JsonResponse(
            {
                "status": "ok",
                "device_id": device_id,
                "attachment": {
                    "id": attachment.pk,
                    "response_id": response_pk,
                    "offline_uuid": attachment.offline_uuid,
                },
            },
            status=201,
        )

    # --- data processing helpers -----------------------------------------

    def _apply_data_payload(self, request: HttpRequest, payload: Mapping[str, Any]) -> dict[str, Any]:
        user = request.user
        catalog_payload = payload.get("catalog")
        if catalog_payload and not isinstance(catalog_payload, Mapping):
            raise ValidationError({"catalog": "Ожидался объект каталога."})

        building_map: dict[str, Building] = {}
        catalog_result = {"buildings": [], "elevators": []}

        buildings_data = []
        if isinstance(catalog_payload, Mapping):
            buildings_data = catalog_payload.get("buildings") or []
        if buildings_data and not isinstance(buildings_data, Iterable):
            raise ValidationError({"catalog": "Поле buildings должно быть списком."})

        for entry in buildings_data or []:
            if not isinstance(entry, Mapping):
                raise ValidationError({"catalog": "Каждый элемент buildings должен быть объектом."})
            client_id = self._require_client_id(entry, "building")
            address = self._clean_string(entry.get("address"))
            if not address:
                raise ValidationError({"catalog": "Для здания необходимо указать address."})

            building = Building.objects.create(
                address=address,
                entrance=self._clean_string(entry.get("entrance")) or "",
                notes=self._clean_string(entry.get("notes")) or "",
                created_by=user,
                review_status=ReviewStatus.PENDING,
            )
            building_map[client_id] = building
            catalog_result["buildings"].append({"client_id": client_id, "id": building.pk})

        elevator_map: dict[str, Elevator] = {}
        elevators_data = []
        if isinstance(catalog_payload, Mapping):
            elevators_data = catalog_payload.get("elevators") or []
        if elevators_data and not isinstance(elevators_data, Iterable):
            raise ValidationError({"catalog": "Поле elevators должно быть списком."})

        for entry in elevators_data or []:
            if not isinstance(entry, Mapping):
                raise ValidationError({"catalog": "Каждый элемент elevators должен быть объектом."})
            client_id = self._require_client_id(entry, "elevator")
            identifier = self._clean_string(entry.get("identifier"))
            if not identifier:
                raise ValidationError({"catalog": "Для лифта необходимо указать identifier."})

            building = self._resolve_building(entry, building_map)

            status_value = entry.get("status") or Elevator.Status.IN_SERVICE
            if status_value not in Elevator.Status.values:
                raise ValidationError({"catalog": "Недопустимый статус лифта."})

            elevator = Elevator.objects.create(
                building=building,
                identifier=identifier,
                description=self._clean_string(entry.get("description")) or "",
                status=status_value,
                created_by=user,
                review_status=ReviewStatus.PENDING,
            )
            elevator_map[client_id] = elevator
            catalog_result["elevators"].append({"client_id": client_id, "id": elevator.pk})

        audits_data = payload.get("audits") or []
        if audits_data and not isinstance(audits_data, Iterable):
            raise ValidationError({"audits": "Поле audits должно быть списком."})

        audits_result: list[dict[str, Any]] = []

        for entry in audits_data or []:
            if not isinstance(entry, Mapping):
                raise ValidationError({"audits": "Каждый элемент списка audits должен быть объектом."})

            client_id = self._require_client_id(entry, "audit")
            audit = self._resolve_audit(entry, user, elevator_map)
            audit._log_actor = user

            if "object_info" in entry:
                object_info = entry.get("object_info")
                if object_info is None:
                    audit.object_info = {}
                elif isinstance(object_info, Mapping):
                    audit.object_info = dict(object_info)
                else:
                    raise ValidationError({"audits": "object_info должен быть объектом."})

            if "planned_date" in entry:
                planned_date_raw = entry.get("planned_date")
                audit.planned_date = self._parse_date(planned_date_raw, field="planned_date")

            if "started_at" in entry:
                started_raw = entry.get("started_at")
                audit.started_at = self._parse_datetime(started_raw, field="started_at")

            if "finished_at" in entry:
                finished_raw = entry.get("finished_at")
                audit.finished_at = self._parse_datetime(finished_raw, field="finished_at")

            if "status" in entry:
                status_value = entry.get("status")
                if status_value not in Audit.Status.values:
                    raise ValidationError({"audits": "Недопустимый статус аудита."})
                audit.status = status_value  # type: ignore[assignment]

            audit.save()

            responses_result: list[dict[str, Any]] = []
            responses_payload = entry.get("responses") or []
            if responses_payload and not isinstance(responses_payload, Iterable):
                raise ValidationError({"audits": "Поле responses должно быть списком."})

            for response_entry in responses_payload or []:
                if not isinstance(response_entry, Mapping):
                    raise ValidationError({"audits": "Каждый ответ должен быть объектом."})

                response_client_id = self._require_client_id(response_entry, "response")
                question_id = response_entry.get("question_id")
                if not question_id:
                    raise ValidationError({"audits": "Для ответа необходимо указать question_id."})
                try:
                    question_pk = int(question_id)
                except (TypeError, ValueError):
                    raise ValidationError({"audits": "question_id должен быть целым числом."})

                question = ChecklistQuestion.objects.filter(pk=question_pk).first()
                if question is None:
                    raise ValidationError({"audits": f"Вопрос {question_pk} не существует."})

                response_obj = self._resolve_response(response_entry, audit, question)

                score_raw = response_entry.get("score")
                if score_raw is None:
                    raise ValidationError({"audits": "Поле score обязательно для ответа."})
                try:
                    response_obj.score = int(score_raw)
                except (TypeError, ValueError):
                    raise ValidationError({"audits": "Значение score должно быть числом."})

                response_obj.comment = self._clean_string(response_entry.get("comment")) or ""
                response_obj.is_flagged = bool(response_entry.get("is_flagged", False))
                response_obj.is_offline_cached = True
                response_obj._log_actor = user
                response_obj.save()

                responses_result.append({"client_id": response_client_id, "id": response_obj.pk})

            audits_result.append({"client_id": client_id, "id": audit.pk, "responses": responses_result})

        return {"catalog": catalog_result, "audits": audits_result}

    # --- object resolution helpers ---------------------------------------

    def _resolve_building(self, entry: Mapping[str, Any], building_map: Mapping[str, Building]) -> Building:
        building_id = entry.get("building_id")
        if building_id:
            try:
                building_pk = int(building_id)
            except (TypeError, ValueError):
                raise ValidationError({"catalog": "building_id должен быть числом."})
            building = Building.objects.filter(pk=building_pk).first()
            if building is None:
                raise ValidationError({"catalog": f"Здание {building_pk} не найдено."})
            return building

        building_client_id = entry.get("building_client_id")
        if building_client_id:
            building = building_map.get(str(building_client_id))
            if building is None:
                raise ValidationError({"catalog": "Неизвестный building_client_id."})
            return building

        raise ValidationError({"catalog": "Для лифта необходимо указать building_id или building_client_id."})

    def _resolve_audit(
        self,
        entry: Mapping[str, Any],
        user: Any,
        elevator_map: Mapping[str, Elevator],
    ) -> Audit:
        audit_id = entry.get("id")
        if audit_id:
            try:
                audit_pk = int(audit_id)
            except (TypeError, ValueError):
                raise ValidationError({"audits": "Идентификатор аудита должен быть числом."})
            audit = Audit.objects.select_for_update().filter(pk=audit_pk, created_by=user).first()
            if audit is None:
                raise ValidationError({"audits": f"Аудит {audit_pk} не найден или недоступен."})
            return audit

        elevator = self._resolve_elevator(entry, elevator_map)
        return Audit(elevator=elevator, created_by=user)

    def _resolve_elevator(
        self,
        entry: Mapping[str, Any],
        elevator_map: Mapping[str, Elevator],
    ) -> Elevator:
        elevator_id = entry.get("elevator_id")
        if elevator_id:
            try:
                elevator_pk = int(elevator_id)
            except (TypeError, ValueError):
                raise ValidationError({"audits": "Идентификатор лифта должен быть числом."})
            elevator = Elevator.objects.filter(pk=elevator_pk).first()
            if elevator is None:
                raise ValidationError({"audits": f"Лифт {elevator_pk} не найден."})
            return elevator

        elevator_client_id = entry.get("elevator_client_id")
        if elevator_client_id:
            elevator = elevator_map.get(str(elevator_client_id))
            if elevator is None:
                raise ValidationError({"audits": "Неизвестный elevator_client_id."})
            return elevator

        raise ValidationError({"audits": "Для аудита необходимо указать elevator_id или elevator_client_id."})

    def _resolve_response(
        self,
        entry: Mapping[str, Any],
        audit: Audit,
        question: ChecklistQuestion,
    ) -> AuditResponse:
        response_id = entry.get("id")
        if response_id:
            try:
                response_pk = int(response_id)
            except (TypeError, ValueError):
                raise ValidationError({"audits": "Идентификатор ответа должен быть числом."})
            response_obj = (
                AuditResponse.objects.select_for_update().filter(pk=response_pk, audit=audit).first()
            )
            if response_obj is None:
                raise ValidationError({"audits": f"Ответ {response_pk} не найден."})
            return response_obj

        existing = AuditResponse.objects.filter(audit=audit, question=question).first()
        if existing is not None:
            return existing
        return AuditResponse(audit=audit, question=question)

    # --- utility helpers --------------------------------------------------

    @staticmethod
    def _clean_string(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _require_client_id(entry: Mapping[str, Any], entity: str) -> str:
        client_id = entry.get("client_id")
        if client_id is None:
            raise ValidationError({entity: "client_id обязателен."})
        value = str(client_id).strip()
        if not value:
            raise ValidationError({entity: "client_id не может быть пустым."})
        return value

    @staticmethod
    def _parse_date(value: Any, *, field: str) -> Any:
        if value in (None, ""):
            return None
        parsed = parse_date(str(value))
        if parsed is None:
            raise ValidationError({field: "Некорректный формат даты."})
        return parsed

    @staticmethod
    def _parse_datetime(value: Any, *, field: str) -> Any:
        if value in (None, ""):
            return None
        parsed = parse_datetime(str(value))
        if parsed is None:
            raise ValidationError({field: "Некорректный формат даты и времени."})
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    @staticmethod
    def _serialize_validation_error(exc: ValidationError) -> dict[str, Any]:
        if isinstance(exc.message_dict, dict):
            return {key: [str(message) for message in value] for key, value in exc.message_dict.items()}
        if isinstance(exc.message, str):
            return {"detail": [exc.message]}
        return {"detail": [str(exc)]}

    @staticmethod
    def _compact_batch_payload(payload: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
        result = {"kind": kind}
        audits = payload.get("audits")
        if isinstance(audits, Iterable):
            result["audits"] = [
                {"client_id": str(entry.get("client_id")), "id": entry.get("id")}
                for entry in audits
                if isinstance(entry, Mapping)
            ]
        catalog = payload.get("catalog")
        if isinstance(catalog, Mapping):
            result["catalog"] = {}
            buildings = catalog.get("buildings")
            if isinstance(buildings, Iterable):
                result["catalog"]["buildings"] = [
                    {"client_id": str(entry.get("client_id"))}
                    for entry in buildings
                    if isinstance(entry, Mapping)
                ]
            elevators = catalog.get("elevators")
            if isinstance(elevators, Iterable):
                result["catalog"]["elevators"] = [
                    {"client_id": str(entry.get("client_id"))}
                    for entry in elevators
                    if isinstance(entry, Mapping)
                ]
        return result

    @staticmethod
    def _json_error(
        code: str,
        message: str,
        *,
        status: int = 400,
        errors: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        payload: dict[str, Any] = {"status": "error", "code": code, "message": message}
        if errors:
            payload["errors"] = errors
        return JsonResponse(payload, status=status)


__all__ = ["OfflineSyncView"]
