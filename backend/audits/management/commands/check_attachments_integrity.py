from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from audits.models import AuditAttachment
from audits.storages import protected_media_storage


class Command(BaseCommand):
    """Проверить целостность вложений аудитов."""

    help = (
        "Проверяет, что файлы вложений существуют, соответствуют сохранённому размеру "
        "и что в защищённом каталоге нет осиротевших файлов."
    )

    def add_arguments(self, parser: Any) -> None:  # type: ignore[override]
        parser.add_argument(
            "--fix-sizes",
            action="store_true",
            help="Автоматически синхронизировать поле stored_size с реальным размером файла.",
        )
        parser.add_argument(
            "--delete-orphans",
            action="store_true",
            help="Удалять файлы, которые присутствуют в каталоге, но не связаны с записями в базе данных.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Вывести результат в формате JSON для последующей обработки скриптами.",
        )

    def handle(self, *args: object, **options: Any) -> str | None:  # type: ignore[override]
        fix_sizes: bool = options.get("fix_sizes", False)
        delete_orphans: bool = options.get("delete_orphans", False)
        as_json: bool = options.get("as_json", False)

        protected_root = Path(settings.PROTECTED_MEDIA_ROOT)
        if not protected_root.exists():
            message = f"Каталог защищённых медиа {protected_root} отсутствует."
            if as_json:
                payload = {
                    "checked": 0,
                    "missing_files": [],
                    "size_mismatches": [],
                    "orphans": [],
                    "fixed_sizes": 0,
                    "deleted_orphans": 0,
                    "status": "warning",
                    "message": message,
                }
                return json.dumps(payload, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.WARNING(message))
            return None

        attachments = (
            AuditAttachment.objects.select_related("response", "response__audit")
            .order_by("pk")
            .iterator()
        )

        total_checked = 0
        referenced_files: set[str] = set()
        missing_files: list[dict[str, Any]] = []
        size_mismatches: list[dict[str, Any]] = []
        fixed_sizes: list[dict[str, Any]] = []

        for attachment in attachments:
            total_checked += 1
            relative_name = attachment.file.name if attachment.file else ""
            if not relative_name:
                missing_files.append(
                    {
                        "id": attachment.pk,
                        "reason": "empty-field",
                        "path": None,
                    }
                )
                continue

            referenced_files.add(relative_name)

            try:
                file_path = Path(protected_media_storage.path(relative_name))
            except (FileNotFoundError, NotImplementedError, ValueError) as exc:
                missing_files.append(
                    {
                        "id": attachment.pk,
                        "reason": "storage-error",
                        "path": relative_name,
                        "details": str(exc),
                    }
                )
                continue

            if not file_path.exists():
                missing_files.append(
                    {
                        "id": attachment.pk,
                        "reason": "missing-file",
                        "path": relative_name,
                    }
                )
                continue

            actual_size = file_path.stat().st_size
            if attachment.stored_size != actual_size:
                if fix_sizes:
                    AuditAttachment.objects.filter(pk=attachment.pk).update(
                        stored_size=actual_size
                    )
                    fixed_sizes.append(
                        {
                            "id": attachment.pk,
                            "path": relative_name,
                            "stored_size": attachment.stored_size,
                            "actual_size": actual_size,
                        }
                    )
                else:
                    size_mismatches.append(
                        {
                            "id": attachment.pk,
                            "path": relative_name,
                            "stored_size": attachment.stored_size,
                            "actual_size": actual_size,
                        }
                    )

        orphans: list[str] = []
        deleted_orphans: list[str] = []
        if protected_root.exists():
            for file_path in protected_root.rglob("*"):
                if not file_path.is_file():
                    continue
                relative = file_path.relative_to(protected_root).as_posix()
                if not relative.startswith("audits/"):
                    continue
                if relative in referenced_files:
                    continue
                orphans.append(relative)

        if delete_orphans and orphans:
            for relative in orphans:
                try:
                    file_path = protected_root / relative
                    file_path.unlink()
                except OSError as exc:
                    self.stderr.write(
                        self.style.ERROR(
                            f"Не удалось удалить осиротевший файл {relative}: {exc}"
                        )
                    )
                else:
                    deleted_orphans.append(relative)
            deleted_set = set(deleted_orphans)
            orphans = [item for item in orphans if item not in deleted_set]

        summary = {
            "checked": total_checked,
            "missing_files": missing_files,
            "size_mismatches": size_mismatches,
            "orphans": orphans,
            "fixed_sizes": fixed_sizes,
            "deleted_orphans": deleted_orphans,
        }

        if as_json:
            status = "ok"
            if missing_files or size_mismatches or orphans:
                status = "failed"
            elif fixed_sizes or deleted_orphans:
                status = "modified"
            summary["status"] = status
            return json.dumps(summary, ensure_ascii=False, indent=2)

        self.stdout.write(f"Проверено вложений: {summary['checked']}")
        if fixed_sizes:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Исправлено записей с некорректным размером: {len(fixed_sizes)}"
                )
            )
            for record in fixed_sizes:
                self.stdout.write(
                    f"  - Вложение #{record['id']} ({record['path']}): "
                    f"{record['stored_size']} → {record['actual_size']} байт"
                )
        if deleted_orphans:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Удалено осиротевших файлов: {len(deleted_orphans)}"
                )
            )
            for path in deleted_orphans:
                self.stdout.write(f"  - {path}")

        issues = 0
        if missing_files:
            issues += len(missing_files)
            self.stderr.write(
                self.style.ERROR(
                    f"Отсутствует {len(missing_files)} файлов вложений."
                )
            )
            for record in missing_files:
                description = record.get("path") or "<без пути>"
                self.stderr.write(
                    f"  - Вложение #{record['id']} ({description}), причина: {record['reason']}"
                )
        if size_mismatches:
            issues += len(size_mismatches)
            self.stderr.write(
                self.style.ERROR(
                    f"Выявлено {len(size_mismatches)} несоответствий размеров."
                )
            )
            for record in size_mismatches:
                self.stderr.write(
                    f"  - Вложение #{record['id']} ({record['path']}): "
                    f"в базе {record['stored_size']} байт, фактически {record['actual_size']} байт"
                )
        if orphans:
            issues += len(orphans)
            self.stderr.write(
                self.style.WARNING(
                    f"Найдено {len(orphans)} осиротевших файлов без записей в базе."
                )
            )
            for path in orphans:
                self.stderr.write(f"  - {path}")

        if issues:
            raise CommandError(
                "Проверка целостности вложений завершилась с ошибками, подробности выше."
            )

        self.stdout.write(self.style.SUCCESS("Все вложения соответствуют базе данных."))
        return None
