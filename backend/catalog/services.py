"""Utility functions for catalog imports with preview and execution helpers."""
from __future__ import annotations

from dataclasses import dataclass
from math import isnan
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Building, Elevator, ReviewStatus


class CatalogImportError(Exception):
    """Raised when a file cannot be processed for preview or import."""


@dataclass(slots=True)
class CatalogImportErrorEntry:
    """Detailed description of a failed import row."""

    row_number: int
    message: str
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "message": self.message,
            "data": self.data,
        }


@dataclass(slots=True)
class CatalogImportRow:
    """Normalized representation of a row extracted from the import file."""

    row_number: int
    data: dict[str, Any]
    errors: list[str]

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(slots=True)
class CatalogImportPreview:
    """Container for preview results before confirming an import."""

    filename: str
    rows: list[CatalogImportRow]

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    @property
    def valid_rows(self) -> list[CatalogImportRow]:
        return [row for row in self.rows if row.is_valid]

    @property
    def error_rows(self) -> list[CatalogImportRow]:
        return [row for row in self.rows if not row.is_valid]

    @property
    def has_errors(self) -> bool:
        return any(not row.is_valid for row in self.rows)

    def build_payload(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for row in self.valid_rows:
            data = dict(row.data)
            data["row_number"] = row.row_number
            payload.append(data)
        return payload


@dataclass(slots=True)
class CatalogImportResult:
    """Summary of the import execution."""

    total_rows: int
    created_count: int
    updated_count: int
    errors: list[CatalogImportErrorEntry]

    @property
    def success_rows(self) -> int:
        return self.total_rows - len(self.errors)

    def error_payload(self) -> list[dict[str, Any]]:
        return [entry.as_dict() for entry in self.errors]


class CatalogImportExecutionError(Exception):
    """Raised when the import transaction detects validation errors."""

    def __init__(self, result: CatalogImportResult):
        super().__init__("Catalog import failed with validation errors.")
        self.result = result


_BUILDING_COLUMNS: dict[str, Sequence[str]] = {
    "address": ("address", "адрес"),
    "entrance": ("entrance", "подъезд"),
    "notes": ("notes", "примечания", "комментарии"),
}

_ELEVATOR_COLUMNS: dict[str, Sequence[str]] = {
    "building_address": ("building_address", "адрес здания", "building", "здание"),
    "building_entrance": ("building_entrance", "подъезд", "entrance"),
    "identifier": ("identifier", "идентификатор", "номер", "номер лифта"),
    "status": ("status", "статус"),
    "description": ("description", "описание", "примечания"),
}

_REQUIRED_BUILDING_FIELDS = frozenset({"address"})
_REQUIRED_ELEVATOR_FIELDS = frozenset({"building_address", "identifier"})


def _read_dataframe(uploaded_file) -> pd.DataFrame:
    try:
        uploaded_file.seek(0)
    except Exception:  # pragma: no cover - not all file-like objects support seek
        pass
    extension = Path(getattr(uploaded_file, "name", "")).suffix.lower()
    try:
        if extension in {".xlsx", ".xlsm", ".xls"}:
            frame = pd.read_excel(uploaded_file, dtype=str)
        else:
            uploaded_file.seek(0)
            frame = pd.read_csv(uploaded_file, dtype=str)
    except Exception as exc:  # pragma: no cover - pandas error text varies
        raise CatalogImportError(
            _("Не удалось прочитать файл импорта: %(error)s") % {"error": exc}
        ) from exc
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:  # pragma: no cover - in-memory files may not support seek
            pass

    if frame.empty:
        return frame

    frame = frame.fillna("")
    return frame


def _normalize_columns(
    frame: pd.DataFrame,
    column_map: dict[str, Sequence[str]],
    required_fields: Iterable[str],
) -> pd.DataFrame:
    normalized_lookup: dict[str, str] = {
        str(column).strip().lower(): column for column in frame.columns
    }
    rename_map: dict[str, str] = {}

    for field, aliases in column_map.items():
        matched_column: str | None = None
        for alias in aliases:
            key = alias.strip().lower()
            if key in normalized_lookup:
                matched_column = normalized_lookup[key]
                break
        if matched_column is not None:
            rename_map[matched_column] = field
        elif field in required_fields:
            sample_name = aliases[0]
            raise CatalogImportError(
                _("В файле отсутствует обязательный столбец «%(name)s».")
                % {"name": sample_name}
            )

    frame = frame.rename(columns=rename_map)
    for field in column_map:
        if field not in frame.columns:
            frame[field] = ""

    ordered_columns = [field for field in column_map]
    return frame[ordered_columns]


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and isnan(value):
        return ""
    return str(value).strip()


def _build_building_rows(frame: pd.DataFrame) -> list[CatalogImportRow]:
    rows: list[CatalogImportRow] = []
    for offset, record in enumerate(frame.to_dict(orient="records"), start=2):
        data = {
            "address": _clean_string(record.get("address", "")),
            "entrance": _clean_string(record.get("entrance", "")),
            "notes": _clean_string(record.get("notes", "")),
        }
        if not any(data.values()):
            continue
        errors: list[str] = []
        if not data["address"]:
            errors.append(_("Не указан адрес здания."))
        rows.append(CatalogImportRow(row_number=offset, data=data, errors=errors))
    return rows


def _build_elevator_rows(frame: pd.DataFrame) -> list[CatalogImportRow]:
    building_lookup: dict[tuple[str, str], Building] = {}
    for building in Building.objects.all():
        key = (
            _clean_string(building.address).lower(),
            _clean_string(building.entrance).lower(),
        )
        building_lookup[key] = building

    rows: list[CatalogImportRow] = []
    for offset, record in enumerate(frame.to_dict(orient="records"), start=2):
        address = _clean_string(record.get("building_address", ""))
        entrance = _clean_string(record.get("building_entrance", ""))
        identifier = _clean_string(record.get("identifier", ""))
        status_value = _clean_string(record.get("status", ""))
        description = _clean_string(record.get("description", ""))

        if not any([address, entrance, identifier, status_value, description]):
            continue

        errors: list[str] = []
        if not address:
            errors.append(_("Не указан адрес здания."))

        building_key = (address.lower(), entrance.lower())
        building = building_lookup.get(building_key)
        if building is None and address:
            errors.append(
                _("Здание «%(address)s» не найдено. Добавьте его перед импортом лифтов.")
                % {"address": address if not entrance else f"{address}, подъезд {entrance}"}
            )

        if not identifier:
            errors.append(_("Не указан идентификатор лифта."))

        status_code, status_error = _resolve_status(status_value)
        if status_error:
            errors.append(status_error)

        data = {
            "building_id": building.pk if building else None,
            "building_address": address,
            "building_entrance": entrance,
            "identifier": identifier,
            "status": status_code,
            "description": description,
        }
        rows.append(CatalogImportRow(row_number=offset, data=data, errors=errors))
    return rows


def _resolve_status(raw_value: str) -> tuple[str, str | None]:
    if not raw_value:
        return Elevator.Status.IN_SERVICE, None

    normalized = raw_value.strip().lower()
    for code, label in Elevator.Status.choices:
        if normalized == code:
            return code, None
        if normalized == str(label).strip().lower():
            return code, None

    return Elevator.Status.IN_SERVICE, _(
        "Неизвестный статус лифта: %(value)s. Допустимые значения: %(choices)s."
    ) % {
        "value": raw_value,
        "choices": ", ".join(str(label) for _, label in Elevator.Status.choices),
    }


def build_building_preview(uploaded_file) -> CatalogImportPreview:
    frame = _read_dataframe(uploaded_file)
    if frame.empty:
        rows: list[CatalogImportRow] = []
    else:
        normalized = _normalize_columns(frame, _BUILDING_COLUMNS, _REQUIRED_BUILDING_FIELDS)
        rows = _build_building_rows(normalized)
    filename = getattr(uploaded_file, "name", "")
    return CatalogImportPreview(filename=filename, rows=rows)


def build_elevator_preview(uploaded_file) -> CatalogImportPreview:
    frame = _read_dataframe(uploaded_file)
    if frame.empty:
        rows = []
    else:
        normalized = _normalize_columns(frame, _ELEVATOR_COLUMNS, _REQUIRED_ELEVATOR_FIELDS)
        rows = _build_elevator_rows(normalized)
    filename = getattr(uploaded_file, "name", "")
    return CatalogImportPreview(filename=filename, rows=rows)


def import_buildings(rows: Sequence[dict[str, Any]], user: Any) -> CatalogImportResult:
    errors: list[CatalogImportErrorEntry] = []
    created_count = 0
    updated_count = 0
    timestamp = timezone.now()

    with transaction.atomic():
        for raw in rows:
            address = _clean_string(raw.get("address"))
            entrance = _clean_string(raw.get("entrance"))
            notes = _clean_string(raw.get("notes"))
            row_number = int(raw.get("row_number", 0) or 0)

            if not address:
                errors.append(
                    CatalogImportErrorEntry(row_number=row_number, message=_("Не указан адрес здания."), data=raw)
                )
                continue

            try:
                building = (
                    Building.objects.select_for_update()
                    .filter(address=address, entrance=entrance)
                    .first()
                )
                is_new = building is None
                if building is None:
                    building = Building(address=address, entrance=entrance)
                    if getattr(user, "is_authenticated", False):
                        building.created_by = user

                building.notes = notes
                building.review_status = ReviewStatus.APPROVED
                if getattr(user, "is_authenticated", False):
                    building.verified_by = user
                building.verified_at = timestamp
                building.full_clean()
                building.save()
                if is_new:
                    created_count += 1
                else:
                    updated_count += 1
            except Exception as exc:
                errors.append(
                    CatalogImportErrorEntry(
                        row_number=row_number or 0,
                        message=str(exc),
                        data=raw,
                    )
                )

        if errors:
            raise CatalogImportExecutionError(
                CatalogImportResult(
                    total_rows=len(rows),
                    created_count=0,
                    updated_count=0,
                    errors=errors,
                )
            )

    return CatalogImportResult(
        total_rows=len(rows),
        created_count=created_count,
        updated_count=updated_count,
        errors=[],
    )


def import_elevators(rows: Sequence[dict[str, Any]], user: Any) -> CatalogImportResult:
    errors: list[CatalogImportErrorEntry] = []
    created_count = 0
    updated_count = 0
    timestamp = timezone.now()

    with transaction.atomic():
        for raw in rows:
            row_number = int(raw.get("row_number", 0) or 0)
            building_id = raw.get("building_id")
            identifier = _clean_string(raw.get("identifier"))
            status = raw.get("status") or Elevator.Status.IN_SERVICE
            description = _clean_string(raw.get("description"))

            if not building_id:
                errors.append(
                    CatalogImportErrorEntry(
                        row_number=row_number,
                        message=_("В справочнике отсутствует указанное здание."),
                        data=raw,
                    )
                )
                continue

            if not identifier:
                errors.append(
                    CatalogImportErrorEntry(
                        row_number=row_number,
                        message=_("Не указан идентификатор лифта."),
                        data=raw,
                    )
                )
                continue

            try:
                building = Building.objects.select_for_update().get(pk=building_id)
            except Building.DoesNotExist as exc:
                errors.append(
                    CatalogImportErrorEntry(
                        row_number=row_number,
                        message=str(exc),
                        data=raw,
                    )
                )
                continue

            try:
                elevator = (
                    Elevator.objects.select_for_update()
                    .filter(building=building, identifier=identifier)
                    .first()
                )
                is_new = elevator is None
                if elevator is None:
                    elevator = Elevator(building=building, identifier=identifier)
                    if getattr(user, "is_authenticated", False):
                        elevator.created_by = user

                elevator.status = status
                elevator.description = description
                elevator.review_status = ReviewStatus.APPROVED
                if getattr(user, "is_authenticated", False):
                    elevator.verified_by = user
                elevator.verified_at = timestamp
                elevator.full_clean()
                elevator.save()
                if is_new:
                    created_count += 1
                else:
                    updated_count += 1
            except Exception as exc:
                errors.append(
                    CatalogImportErrorEntry(
                        row_number=row_number,
                        message=str(exc),
                        data=raw,
                    )
                )

        if errors:
            raise CatalogImportExecutionError(
                CatalogImportResult(
                    total_rows=len(rows),
                    created_count=0,
                    updated_count=0,
                    errors=errors,
                )
            )

    return CatalogImportResult(
        total_rows=len(rows),
        created_count=created_count,
        updated_count=updated_count,
        errors=[],
    )


__all__ = [
    "CatalogImportError",
    "CatalogImportErrorEntry",
    "CatalogImportExecutionError",
    "CatalogImportPreview",
    "CatalogImportResult",
    "CatalogImportRow",
    "build_building_preview",
    "build_elevator_preview",
    "import_buildings",
    "import_elevators",
]
