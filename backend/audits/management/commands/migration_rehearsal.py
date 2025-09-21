"""Management command for the T5.2 migration rehearsal checks."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import BaseCommand, CommandParser, color_style
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models import Count, F
from django.utils import timezone

from audits.models import Audit, AuditAttachment, AuditResponse
from checklists.models import ChecklistItem, ChecklistTemplate


class Command(BaseCommand):
    """Run data quality checks for the migration rehearsal (task T5.2)."""

    help = (
        "Собрать отчёт о состоянии данных после миграций: чек-листы, статусы аудитов, "
        "вложения. Используется в рамках репетиции T5.2."
    )

    def add_arguments(self, parser: CommandParser) -> None:  # pragma: no cover - CLI glue
        parser.add_argument(
            "--database",
            dest="database",
            default=DEFAULT_DB_ALIAS,
            help="Алиас базы данных для проверки (по умолчанию: default).",
        )
        parser.add_argument(
            "--output",
            dest="output",
            help="Путь к JSON-файлу для сохранения детального отчёта.",
        )
        parser.add_argument(
            "--max-file-checks",
            dest="max_file_checks",
            type=int,
            default=20,
            help=(
                "Максимальное количество вложений для проверки наличия файлов."
                " Значение 0 отключает проверку файлов."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        database = options["database"]
        output_path = options.get("output")
        max_file_checks = max(0, int(options.get("max_file_checks", 20)))

        style = color_style()
        report: dict[str, Any] = {
            "generated_at": timezone.now().isoformat(timespec="seconds"),
            "database": database,
        }

        report["checklists"] = self.inspect_checklists(database)
        report["audits"] = self.inspect_audits(database)
        report["attachments"] = self.inspect_attachments(database, max_file_checks=max_file_checks)
        report["summary"] = self.build_summary(report)

        self.render_console(report, style)

        if output_path:
            output_file = Path(output_path)
            output_file.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            self.stdout.write(style.NOTICE(f"JSON-отчёт сохранён в {output_file.resolve()}"))

    # --- helpers -----------------------------------------------------------------

    def inspect_checklists(self, database: str) -> dict[str, Any]:
        templates_qs = ChecklistTemplate.objects.using(database).order_by("id")
        items_qs = ChecklistItem.objects.using(database)
        template_results: list[dict[str, Any]] = []
        warnings: list[str] = []
        errors: list[str] = []

        for template in templates_qs:
            items = list(
                ChecklistItem.objects.using(database)
                .filter(template_id=template.pk)
                .order_by("order", "id")
                .only(
                    "id",
                    "order",
                    "score_type",
                    "min_score",
                    "max_score",
                    "step",
                    "options",
                )
            )
            orders = [item.order for item in items]
            duplicates = self.find_duplicates(orders)
            numeric_issues = [
                item.id
                for item in items
                if item.score_type == ChecklistItem.ScoreType.NUMERIC
                and (item.min_score is None or item.max_score is None or (item.step or 0) <= 0)
            ]
            option_issues = [
                item.id
                for item in items
                if item.score_type == ChecklistItem.ScoreType.OPTION and not item.options
            ]

            if duplicates:
                warnings.append(
                    "Повторяющиеся значения order в шаблоне "
                    f"{template.pk}: {sorted(duplicates)}."
                )
            if numeric_issues:
                errors.append(
                    "Неверно сконфигурированы числовые вопросы в шаблоне "
                    f"{template.pk}: {numeric_issues}."
                )
            if option_issues:
                errors.append(
                    "Пункты с выбором вариантов без опций в шаблоне "
                    f"{template.pk}: {option_issues}."
                )

            template_results.append(
                {
                    "id": template.pk,
                    "name": template.name,
                    "items": len(items),
                    "min_order": orders[0] if orders else None,
                    "max_order": orders[-1] if orders else None,
                    "has_duplicates": bool(duplicates),
                    "numeric_issues": numeric_issues,
                    "option_issues": option_issues,
                }
            )

        legacy_info = self.fetch_legacy_checklist_counts(database)

        if legacy_info:
            legacy_questions = legacy_info.get("catalog_checklistquestion")
            if legacy_questions is not None and legacy_questions != items_qs.count():
                warnings.append(
                    "Количество пунктов чек-листа не совпадает с числом записей в "
                    "legacy-таблице catalog_checklistquestion."
                )

        return {
            "templates_total": templates_qs.count(),
            "items_total": items_qs.count(),
            "templates": template_results,
            "legacy_tables": legacy_info,
            "warnings": warnings,
            "errors": errors,
        }

    def inspect_audits(self, database: str) -> dict[str, Any]:
        audits_qs = Audit.objects.using(database)
        responses_qs = AuditResponse.objects.using(database)

        status_breakdown = {
            row["status"]: row["total"]
            for row in audits_qs.values("status").annotate(total=Count("id"))
        }

        legacy_statuses = {
            status: total
            for status, total in status_breakdown.items()
            if status not in Audit.Status.values
        }

        submitted_without_timestamp = audits_qs.filter(
            status=Audit.Status.SUBMITTED, submitted_at__isnull=True
        ).values_list("id", flat=True)
        draft_with_timestamp = audits_qs.filter(
            status=Audit.Status.DRAFT, submitted_at__isnull=False
        ).values_list("id", flat=True)

        score_mismatches: list[int] = []
        for audit in (
            audits_qs.select_related("template")
            .prefetch_related("responses__item")
            .iterator(chunk_size=200)
        ):
            expected_score = audit.calculate_score(commit=False)
            if audit.score != expected_score:
                score_mismatches.append(audit.pk)

        cross_template_responses = list(
            responses_qs.exclude(item__template=F("audit__template")).values_list("id", flat=True)
        )

        errors: list[str] = []
        warnings: list[str] = []

        if legacy_statuses:
            errors.append(
                "Обнаружены устаревшие статусы аудитов: "
                + ", ".join(f"{key}={value}" for key, value in sorted(legacy_statuses.items()))
            )
        if submitted_without_timestamp:
            warnings.append(
                "Аудиты без отметки submitted_at: "
                + ", ".join(map(str, submitted_without_timestamp[:20]))
            )
        if draft_with_timestamp:
            warnings.append(
                "Черновики с заполненным submitted_at: "
                + ", ".join(map(str, draft_with_timestamp[:20]))
            )
        if score_mismatches:
            errors.append(
                "Несовпадение расчёта итогового балла: audits="
                + ", ".join(map(str, score_mismatches[:20]))
            )
        if cross_template_responses:
            errors.append(
                "Ответы, не соответствующие шаблону аудита: responses="
                + ", ".join(map(str, cross_template_responses[:20]))
            )

        return {
            "total": audits_qs.count(),
            "status_breakdown": status_breakdown,
            "legacy_statuses": legacy_statuses,
            "responses_total": responses_qs.count(),
            "submitted_without_timestamp": list(submitted_without_timestamp),
            "draft_with_timestamp": list(draft_with_timestamp),
            "score_mismatches": score_mismatches,
            "cross_template_responses": cross_template_responses,
            "warnings": warnings,
            "errors": errors,
        }

    def inspect_attachments(self, database: str, *, max_file_checks: int) -> dict[str, Any]:
        attachments_qs = AuditAttachment.objects.using(database)

        mismatched_audits = list(
            attachments_qs.filter(response__isnull=False)
            .exclude(response__audit=F("audit"))
            .values_list("id", flat=True)
        )

        limits = getattr(settings, "AUDIT_ATTACHMENT_LIMITS", {})
        over_audit_limit = list(
            attachments_qs.values("audit_id")
            .annotate(total=Count("id"))
            .filter(total__gt=int(limits.get("max_per_audit", 0) or 0))
            .values_list("audit_id", flat=True)
        )
        over_response_limit = list(
            attachments_qs.filter(response_id__isnull=False)
            .values("response_id")
            .annotate(total=Count("id"))
            .filter(total__gt=int(limits.get("max_per_response", 0) or 0))
            .values_list("response_id", flat=True)
        )

        missing_files: list[int] = []
        if max_file_checks:
            checked = 0
            for attachment in attachments_qs.iterator():
                if checked >= max_file_checks:
                    break
                checked += 1
                file_field = attachment.file
                if not file_field:
                    missing_files.append(attachment.pk)
                    continue
                try:
                    if not file_field.storage.exists(file_field.name):
                        missing_files.append(attachment.pk)
                except Exception:  # pragma: no cover - defensive I/O guard
                    missing_files.append(attachment.pk)

        legacy_columns = self.fetch_attachment_legacy_columns(database)

        warnings: list[str] = []
        errors: list[str] = []

        if mismatched_audits:
            errors.append(
                "Вложения с несоответствующим ответом/аудитом: "
                + ", ".join(map(str, mismatched_audits[:20]))
            )
        if over_audit_limit:
            warnings.append(
                "Аудиты, превышающие лимит вложений: "
                + ", ".join(map(str, over_audit_limit[:20]))
            )
        if over_response_limit:
            warnings.append(
                "Ответы, превышающие лимит вложений: "
                + ", ".join(map(str, over_response_limit[:20]))
            )
        if missing_files:
            warnings.append(
                "Файлы вложений не найдены на диске: "
                + ", ".join(map(str, missing_files[:20]))
            )
        if legacy_columns:
            warnings.append(
                "В таблице вложений остались legacy-колонки: "
                + ", ".join(sorted(legacy_columns))
            )

        return {
            "total": attachments_qs.count(),
            "mismatched_audits": mismatched_audits,
            "over_audit_limit": over_audit_limit,
            "over_response_limit": over_response_limit,
            "missing_files": missing_files,
            "legacy_columns": sorted(legacy_columns),
            "warnings": warnings,
            "errors": errors,
        }

    # --- rendering ---------------------------------------------------------------

    def build_summary(self, report: dict[str, Any]) -> dict[str, Any]:
        sections = [report["checklists"], report["audits"], report["attachments"]]
        total_errors = sum(len(section.get("errors", [])) for section in sections)
        total_warnings = sum(len(section.get("warnings", [])) for section in sections)
        passed = total_errors == 0
        return {
            "passed": passed,
            "errors": total_errors,
            "warnings": total_warnings,
        }

    def render_console(self, report: dict[str, Any], style: Any) -> None:
        summary = report["summary"]
        header = (
            f"Отчёт репетиции миграции (T5.2) — база '{report['database']}', "
            f"сгенерирован {report['generated_at']}"
        )
        self.stdout.write(style.MIGRATE_LABEL(header))

        def render_section(title: str, data: dict[str, Any]) -> None:
            self.stdout.write(style.SUCCESS(f"\n{title}"))
            for key in ("templates_total", "items_total", "total", "responses_total"):
                if key in data:
                    self.stdout.write(f"  {key}: {data[key]}")
            if data.get("warnings"):
                self.stdout.write(style.WARNING("  Предупреждения:"))
                for warning in data["warnings"]:
                    self.stdout.write(style.WARNING(f"    - {warning}"))
            if data.get("errors"):
                self.stdout.write(style.ERROR("  Ошибки:"))
                for error in data["errors"]:
                    self.stdout.write(style.ERROR(f"    - {error}"))

        render_section("Чек-листы", report["checklists"])
        render_section("Аудиты", report["audits"])
        render_section("Вложения", report["attachments"])

        if summary["passed"]:
            self.stdout.write(style.SUCCESS("\nИтог: критичных ошибок не обнаружено."))
        else:
            self.stdout.write(style.ERROR("\nИтог: необходимо устранить найденные ошибки."))
        if summary["warnings"] and summary["errors"] == 0:
            self.stdout.write(style.WARNING("Есть предупреждения, требующие анализа."))

    # --- utilities --------------------------------------------------------------

    def fetch_legacy_checklist_counts(self, database: str) -> dict[str, int]:
        connection = connections[database]
        table_names = {
            table_info.name for table_info in connection.introspection.get_table_list(connection.cursor())
        }
        legacy_tables = {
            name
            for name in {
                "catalog_checklistcategory",
                "catalog_checklistsection",
                "catalog_checklistquestion",
                "catalog_scoreoption",
            }
            if name in table_names
        }
        result: dict[str, int] = {}
        if not legacy_tables:
            return result
        with connection.cursor() as cursor:
            for table_name in sorted(legacy_tables):
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()
                if count:
                    result[table_name] = int(count[0])
        return result

    def fetch_attachment_legacy_columns(self, database: str) -> set[str]:
        connection = connections[database]
        table_name = AuditAttachment._meta.db_table
        legacy_columns = {"offline_uuid", "checksum", "synced_at"}
        try:
            description = connection.introspection.get_table_description(connection.cursor(), table_name)
        except Exception:  # pragma: no cover - defensive
            return set()
        existing_columns = {column.name for column in description}
        return legacy_columns & existing_columns

    @staticmethod
    def find_duplicates(values: list[int]) -> set[int]:
        counter = Counter(values)
        return {value for value, total in counter.items() if total > 1}

