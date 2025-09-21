"""Import/export services for checklist templates using pandas/openpyxl."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re
from typing import IO, Iterable, Sequence

import pandas as pd
from django.db import transaction

from .models import ChecklistItem, ChecklistOptionDefinition, ChecklistTemplate

# Column aliases are normalized using `_normalize_label`.
_COLUMN_ALIASES: dict[str, set[str]] = {
    "order": {"order", "порядок", "index", "номер", "no", "№"},
    "area": {"area", "зона", "a"},
    "category": {"category", "категория", "уровень"},
    "question": {"question", "вопрос", "параметры", "parameter", "text", "описание"},
    "help_text": {"help_text", "help", "подсказка", "инструкция", "критерии"},
    "score_type": {"score_type", "type", "тип", "result", "результат"},
    "min_score": {"min_score", "минимальныйбалл", "минимальный_балл", "min"},
    "max_score": {"max_score", "максимальныйбалл", "максимальный_балл", "max"},
    "step": {"step", "шаг"},
    "options": {"options", "опции", "варианты", "choices"},
    "requires_comment": {
        "requires_comment",
        "comment_required",
        "обязательныйкомментарий",
        "комментарийобязателен",
    },
    "weight": {"weight", "вес"},
}

_TRUE_VALUES = {"1", "true", "yes", "y", "да", "истина", "required", "обязательно"}
_FALSE_VALUES = {"0", "false", "no", "n", "нет", "ложь", "", "optional", "необязательно"}

_NUMERIC_ALIASES = {"numeric", "number", "score", "digit", "range", "числовой", "баллы"}
_OPTION_ALIASES = {"option", "choice", "variant", "вариант", "опция", "enum"}

_EXPORT_COLUMNS = [
    "order",
    "area",
    "category",
    "question",
    "help_text",
    "score_type",
    "min_score",
    "max_score",
    "step",
    "options",
    "requires_comment",
    "weight",
]


class ChecklistImportError(Exception):
    """Raised when a checklist import file contains invalid data."""

    def __init__(self, errors: Sequence[str]):
        self.errors = list(errors)
        message = "\n".join(self.errors)
        super().__init__(message)


@dataclass
class _ParsedRow:
    question: str
    order: int
    area: str
    category: str
    help_text: str
    score_type: str
    min_score: Decimal | None
    max_score: Decimal | None
    step: Decimal | None
    options: list[ChecklistOptionDefinition]
    requires_comment: bool
    weight: Decimal


def import_checklist_from_file(
    template: ChecklistTemplate,
    file_obj: IO[bytes | str],
    *,
    filename: str,
    clear_existing: bool = True,
) -> list[ChecklistItem]:
    """Load checklist data from CSV/XLSX file and create template items."""

    dataframe = _read_dataframe(file_obj, filename=filename)
    return import_checklist_from_dataframe(
        template,
        dataframe,
        clear_existing=clear_existing,
    )


def import_checklist_from_dataframe(
    template: ChecklistTemplate,
    dataframe: pd.DataFrame,
    *,
    clear_existing: bool = True,
) -> list[ChecklistItem]:
    """Create checklist items from a pandas dataframe."""

    prepared = _prepare_dataframe(dataframe)
    records = prepared.to_dict(orient="records")
    errors: list[str] = []
    parsed_rows: list[_ParsedRow] = []
    used_orders: set[int] = set()

    if not clear_existing:
        used_orders.update(
            template.items.values_list("order", flat=True)
        )

    next_order = (max(used_orders) + 1) if used_orders else 1

    for index, raw_row in enumerate(records, start=2):
        normalized = {
            key: _normalize_value(value)
            for key, value in raw_row.items()
        }
        if not normalized.get("question"):
            # Skip empty rows silently — they often appear in Excel exports.
            continue
        try:
            parsed = _parse_row(
                normalized,
                row_number=index,
                next_order=next_order,
                used_orders=used_orders,
            )
        except ChecklistImportRowError as exc:  # pragma: no cover - simple passthrough
            errors.append(str(exc))
            continue
        parsed_rows.append(parsed)
        used_orders.add(parsed.order)
        next_order = max(next_order, parsed.order + 1)

    if not parsed_rows and not errors:
        errors.append("Не найдено ни одной строки с вопросами чек-листа.")

    if errors:
        raise ChecklistImportError(errors)

    items: list[ChecklistItem] = []
    for parsed in parsed_rows:
        item = ChecklistItem(
            template=template,
            order=parsed.order,
            area=parsed.area,
            category=parsed.category,
            question=parsed.question,
            help_text=parsed.help_text,
            score_type=parsed.score_type,
            min_score=parsed.min_score,
            max_score=parsed.max_score,
            step=parsed.step,
            options=[definition.serialized() for definition in parsed.options],
            requires_comment=parsed.requires_comment,
            weight=parsed.weight,
        )
        # Avoid hitting the database for uniqueness checks by validating fields explicitly.
        item.clean_fields()
        item.clean()
        items.append(item)

    with transaction.atomic():
        if clear_existing:
            template.items.all().delete()
        ChecklistItem.objects.bulk_create(items)
    return items


def export_checklist_to_dataframe(template: ChecklistTemplate) -> pd.DataFrame:
    """Serialize checklist items to a pandas dataframe."""

    rows: list[dict[str, object]] = []
    for item in template.items.order_by("order", "id"):
        rows.append(
            {
                "order": item.order,
                "area": item.area,
                "category": item.category,
                "question": item.question,
                "help_text": item.help_text,
                "score_type": item.score_type,
                "min_score": _decimal_to_string(item.min_score),
                "max_score": _decimal_to_string(item.max_score),
                "step": _decimal_to_string(item.step),
                "options": _serialize_options(item),
                "requires_comment": item.requires_comment,
                "weight": _decimal_to_string(item.weight),
            }
        )
    return pd.DataFrame(rows, columns=_EXPORT_COLUMNS)


def export_checklist_to_csv(
    template: ChecklistTemplate,
    file_obj: IO[str],
    *,
    index: bool = False,
    encoding: str = "utf-8",
) -> None:
    """Write checklist items to a CSV file-like object."""

    dataframe = export_checklist_to_dataframe(template)
    dataframe.to_csv(file_obj, index=index, encoding=encoding)


def export_checklist_to_excel(
    template: ChecklistTemplate,
    file_obj: IO[bytes],
    *,
    index: bool = False,
) -> None:
    """Write checklist items to an XLSX file-like object using openpyxl."""

    dataframe = export_checklist_to_dataframe(template)
    dataframe.to_excel(file_obj, index=index, engine="openpyxl")


class ChecklistImportRowError(ValueError):
    """Detailed error for a particular row of the import file."""

    def __init__(self, row_number: int, message: str):
        super().__init__(f"Строка {row_number}: {message}")
        self.row_number = row_number
        self.message = message


def _read_dataframe(file_obj: IO[bytes | str], *, filename: str) -> pd.DataFrame:
    suffix = filename.split(".")[-1].lower() if "." in filename else ""
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    if suffix in {"csv", "txt"}:
        return pd.read_csv(file_obj, dtype=str, keep_default_na=False)
    if suffix in {"xlsx", "xlsm", "xls"}:
        return pd.read_excel(file_obj, dtype=str, engine="openpyxl")
    raise ChecklistImportError(
        [
            "Неподдерживаемый формат файла: ожидались CSV или XLSX.",
        ]
    )


def _prepare_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe

    df = dataframe.copy()
    rename_map: dict[str, str] = {}
    for column in df.columns:
        canonical = _canonical_column(column)
        if canonical:
            rename_map[column] = canonical
    df = df.rename(columns=rename_map)

    required_columns = {"question"}
    missing = sorted(column for column in required_columns if column not in df.columns)
    if missing:
        raise ChecklistImportError(
            [
                "Отсутствуют обязательные столбцы: "
                + ", ".join(missing),
            ]
        )

    if "requires_comment" not in df.columns:
        df["requires_comment"] = False

    # Treat empty strings as missing values to allow forward fill.
    df = df.replace(r"^\s*$", pd.NA, regex=True)

    for column in ("area", "category"):
        if column in df.columns:
            df[column] = df[column].ffill().fillna("")

    return df


def _canonical_column(column: object) -> str | None:
    normalized = _normalize_label(column)
    for canonical, aliases in _COLUMN_ALIASES.items():
        if normalized in aliases:
            return canonical
    return None


def _normalize_label(label: object) -> str:
    text = str(label).strip().lower()
    text = text.replace("ё", "е")
    text = re.sub(r"[^a-z0-9а-я]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _normalize_value(value: object) -> object | None:
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    if value is None:
        return None
    if not isinstance(value, str) and pd.isna(value):  # type: ignore[arg-type]
        return None
    if isinstance(value, str) and value.lower() in {"nan", "none"}:
        return None
    return value


def _parse_row(
    row: dict[str, object],
    *,
    row_number: int,
    next_order: int,
    used_orders: set[int],
) -> _ParsedRow:
    question = str(row.get("question", "")).strip()
    if not question:
        raise ChecklistImportRowError(row_number, "Отсутствует формулировка вопроса.")

    area = str(row.get("area", "") or "")
    category = str(row.get("category", "") or "")
    raw_help_text = row.get("help_text", "")
    help_text = str(raw_help_text or "")

    options = _parse_option_definitions(
        row.get("options"),
        help_text=help_text,
    )
    score_type = _parse_score_type(
        row.get("score_type"),
        options,
        row_number=row_number,
    )

    min_score: Decimal | None = None
    max_score: Decimal | None = None
    step: Decimal | None = None
    if score_type == ChecklistItem.ScoreType.NUMERIC:
        min_score = _parse_decimal(
            row.get("min_score"),
            "min_score",
            row_number=row_number,
            required=True,
        )
        max_score = _parse_decimal(
            row.get("max_score"),
            "max_score",
            row_number=row_number,
            required=True,
        )
        step = _parse_decimal(
            row.get("step"),
            "step",
            row_number=row_number,
            required=True,
        )
        if options:
            raise ChecklistImportRowError(
                row_number,
                "Для числового вопроса не требуется список вариантов.",
            )
    else:
        if not options:
            raise ChecklistImportRowError(
                row_number,
                "Для вопросов с вариантами необходимо указать хотя бы один вариант.",
            )

    requires_comment = _parse_bool(
        row.get("requires_comment"),
        row_number=row_number,
    )
    weight = _parse_decimal(
        row.get("weight"),
        "weight",
        row_number=row_number,
        required=False,
        default=Decimal("1"),
    )

    order = _parse_order(
        row.get("order"),
        row_number=row_number,
    )
    if order is None:
        order = next_order
    if order <= 0:
        raise ChecklistImportRowError(
            row_number,
            "Порядковый номер должен быть положительным числом.",
        )
    if order in used_orders:
        raise ChecklistImportRowError(
            row_number,
            f"Порядковый номер {order} уже используется.",
        )

    return _ParsedRow(
        question=question,
        order=order,
        area=area,
        category=category,
        help_text=help_text,
        score_type=score_type,
        min_score=min_score,
        max_score=max_score,
        step=step,
        options=options,
        requires_comment=requires_comment,
        weight=weight,
    )


def _parse_score_type(
    raw_value: object,
    options: Iterable[ChecklistOptionDefinition],
    *,
    row_number: int,
) -> str:
    option_list = list(options)
    if raw_value is None:
        return (
            ChecklistItem.ScoreType.OPTION
            if option_list
            else ChecklistItem.ScoreType.NUMERIC
        )
    text = _normalize_label(raw_value)
    if text in _NUMERIC_ALIASES:
        return ChecklistItem.ScoreType.NUMERIC
    if text in _OPTION_ALIASES:
        return ChecklistItem.ScoreType.OPTION
    if option_list:
        return ChecklistItem.ScoreType.OPTION
    raw_text = str(raw_value).strip()
    if re.match(r"^-?\d+(?:[.,]\d+)?\s*[-–—]\s*-?\d+(?:[.,]\d+)?$", raw_text):
        return ChecklistItem.ScoreType.NUMERIC
    raise ChecklistImportRowError(
        row_number,
        "Не удалось определить тип оценки: ожидается 'numeric' или 'option'.",
    )


def _parse_option_definitions(
    value: object | None,
    *,
    help_text: str,
) -> list[ChecklistOptionDefinition]:
    candidates = list(_iterate_option_candidates(value))
    options: list[ChecklistOptionDefinition] = []

    for candidate in candidates:
        option = _build_option_definition(candidate)
        if option is not None:
            options.append(option)

    if not options and help_text:
        options.extend(_extract_options_from_help_text(help_text))

    normalized: list[ChecklistOptionDefinition] = []
    seen_labels: set[str] = set()
    for option in options:
        label_key = option.label.strip().lower()
        if not label_key:
            continue
        if label_key in seen_labels:
            continue
        seen_labels.add(label_key)
        normalized.append(option)
    return normalized


def _iterate_option_candidates(value: object | None) -> Iterable[object]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    text = str(value).strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        parts = [part for part in re.split(r"[\n;|]+", text) if part.strip()]
        return parts
    if isinstance(loaded, list):
        return loaded
    return [loaded]


def _build_option_definition(candidate: object) -> ChecklistOptionDefinition | None:
    if isinstance(candidate, ChecklistOptionDefinition):
        return candidate
    if isinstance(candidate, dict):
        label = str(
            candidate.get("label")
            or candidate.get("text")
            or candidate.get("name")
            or "",
        ).strip()
        if not label:
            return None
        raw_value = (
            candidate.get("value")
            if "value" in candidate
            else candidate.get("score")
        )
        value = _coerce_decimal(raw_value)
        return ChecklistOptionDefinition(value=value, label=label)
    text = str(candidate or "").strip()
    if not text:
        return None
    match = re.match(r"^(?P<value>-?\d+(?:[.,]\d+)?)\s*[-–—:]+\s*(?P<label>.+)$", text)
    if match:
        value = _coerce_decimal(match.group("value"))
        label = match.group("label").strip()
        if label:
            return ChecklistOptionDefinition(value=value, label=label)
    return ChecklistOptionDefinition(value=None, label=text)


def _extract_options_from_help_text(text: str) -> list[ChecklistOptionDefinition]:
    pattern = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*[-–—:]")
    matches = list(pattern.finditer(text))
    options: list[ChecklistOptionDefinition] = []
    if not matches:
        return options
    for index, match in enumerate(matches):
        value = _coerce_decimal(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        label = text[start:end].strip(" \t\n\r;,.•-·")
        if label:
            options.append(ChecklistOptionDefinition(value=value, label=label))
    return options


def _coerce_decimal(value: object | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _parse_bool(value: object | None, *, row_number: int) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ChecklistImportRowError(
        row_number,
        f"Не удалось интерпретировать значение '{value}' как булево.",
    )


def _parse_decimal(
    value: object | None,
    field: str,
    *,
    row_number: int,
    required: bool,
    default: Decimal | None = None,
) -> Decimal | None:
    if value is None:
        if required:
            raise ChecklistImportRowError(
                row_number,
                f"Для поля {field} необходимо указать значение.",
            )
        return default
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(" ", "")
    if not text:
        if required:
            raise ChecklistImportRowError(
                row_number,
                f"Для поля {field} необходимо указать значение.",
            )
        return default
    text = text.replace(",", ".")
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - defensive branch
        raise ChecklistImportRowError(
            row_number,
            f"Поле {field} должно быть числом.",
        ) from exc
    return parsed


def _parse_order(value: object | None, *, row_number: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ChecklistImportRowError(
            row_number,
            "Порядковый номер должен быть целым числом.",
        ) from exc
    if number != number.to_integral_value():
        raise ChecklistImportRowError(
            row_number,
            "Порядковый номер должен быть целым числом.",
        )
    return int(number)


def _decimal_to_string(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")


def _serialize_options(item: ChecklistItem) -> str:
    if item.score_type != ChecklistItem.ScoreType.OPTION:
        return ""
    return json.dumps(
        [definition.serialized() for definition in item.option_definitions()],
        ensure_ascii=False,
    )


__all__ = [
    "ChecklistImportError",
    "import_checklist_from_dataframe",
    "import_checklist_from_file",
    "export_checklist_to_dataframe",
    "export_checklist_to_csv",
    "export_checklist_to_excel",
]

