# Союзлифт Аудит

Веб-приложение для проведения аудитов лифтовой инфраструктуры компании «Союзлифт». Репозиторий содержит серверную часть на Django, шаблоны пользовательского интерфейса и эксплуатационные материалы.

## Основные возможности

- личные кабинеты аудитора и администратора с разграничением прав;
- справочники зданий и лифтов с модерацией записей, созданных аудиторами;
- конструктор чек-листа с гибкими настройками обязательных полей и шкал оценок;
- проведение аудита с фотофиксацией, расчётом баллов и историей статусов;
- офлайн-режим с кэшированием справочников, локальным сохранением черновиков и последующей синхронизацией;
- экспорт результатов для печати и в табличные форматы.

Подробная архитектура описана в [docs/architecture/v1.md](docs/architecture/v1.md) (базовая версия) и дополнена моделью ролей в [docs/architecture/v2.md](docs/architecture/v2.md); план реализации фиксируется в [AGENTS.md](AGENTS.md).

## Стек и зависимости

| Компонент | Используемые технологии |
|-----------|-------------------------|
| Backend   | Python 3.11, Django 5.x |
| База данных | SQLite (файл `backend/db/db.sqlite3`) |
| UI        | Django Templates, Bootstrap 5 (предсобранные CSS/JS) |
| Тесты     | `pytest`, `pytest-django`, `factory-boy`, `ruff` |

Зависимости Python перечислены в [requirements.txt](requirements.txt). Стили Bootstrap подключаются локально из каталога `backend/static/`.

## Структура репозитория

- `backend/` — Django-проект (`config`) и приложения `accounts`, `catalog`, `audits`, тесты и статика.
- `docs/` — дополнительная документация для разработчиков, эксплуатации и пользователей:
  - `architecture/` — системные описания (версии 1.0 и 2.0);
  - `guides/` — руководства для разработчиков и пользователей;
  - `runbooks/` — эксплуатационные регламенты и инструкции по развёртыванию;
  - `checklists/` — контрольные листы регрессионных проверок;
  - `reports/` — зафиксированные результаты UI-проверок.
- `scripts/` — утилиты для резервного копирования, обслуживания и развёртывания.
- `deploy/` — конфигурации и шаблоны для серверной инфраструктуры.
- `data.csv` — демонстрационный набор исходных данных.

## Быстрый старт (разработка)

1. Установите Python 3.11 и необходимые системные пакеты (см. [docs/guides/development.md](docs/guides/development.md)).
2. Создайте виртуальное окружение и активируйте его:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
3. Установите зависимости: `pip install -r requirements.txt`.
4. Выполните миграции: `python manage.py migrate`.
5. Создайте суперпользователя: `python manage.py createsuperuser`.
6. Запустите сервер разработки: `python manage.py runserver`.

Переменные окружения по умолчанию настроены для профиля `dev`. Для переключения используйте `DJANGO_ENV` (`dev`, `test`, `prod`) и задайте секретный ключ в `DJANGO_SECRET_KEY` перед развёртыванием.

## Проверки качества

Перед коммитом или Pull Request выполните автоматические проверки:

```bash
python manage.py check
pytest
ruff check backend/
```

Дополнительные указания приведены в [docs/guides/development.md](docs/guides/development.md) и [docs/runbooks/operations.md](docs/runbooks/operations.md).

## Документация

- [docs/architecture/v1.md](docs/architecture/v1.md) — базовая архитектура.
- [docs/architecture/v2.md](docs/architecture/v2.md) — целевая архитектура 2.0.
- [docs/guides/development.md](docs/guides/development.md) — руководство разработчика.
- [docs/guides/windows-dev.md](docs/guides/windows-dev.md) — настройка окружения Windows.
- [docs/guides/user-guide.md](docs/guides/user-guide.md) — инструкция для аудиторов и администраторов.
- [docs/runbooks/deployment.md](docs/runbooks/deployment.md) — чек-листы развёртывания и настройки инфраструктуры.
- [docs/runbooks/operations.md](docs/runbooks/operations.md) — регламенты сопровождения и резервного копирования.
- [docs/checklists/ui-regression-checklist.md](docs/checklists/ui-regression-checklist.md) — контрольный список регрессионного тестирования интерфейса.
- [docs/reports/ui-regressions-dev-2025-09-20.md](docs/reports/ui-regressions-dev-2025-09-20.md) — отчёт по регрессиям DEV от 20.09.2025.
- [docs/reports/ui-regressions-dev-2025-10-01.md](docs/reports/ui-regressions-dev-2025-10-01.md) — отчёт по регрессиям DEV от 01.10.2025.

## Лицензия

Тип лицензии уточняется с заказчиком. До утверждения распространяется внутреннее соглашение компании «Союзлифт».
