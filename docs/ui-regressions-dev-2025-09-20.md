# DEV UI regressions — 2025-09-20

## UI-DEV-001 — Потеря центрирования `.container` в базовом шаблоне

- **Статус проверки:** не воспроизведено (2025-09-30)
- **Проверенные экраны:** личный кабинет (`accounts:dashboard`), списки справочников (`catalog:building-list`, `catalog:elevator-list`), список аудитов (`audits:audit-list`), офлайн-страницы (`audits:offline_checklist`, `audits:offline_object_info`). Все эти представления наследуют `backend/templates/base.html`.
- **Фактическое поведение:** элементы с классом `container` остаются центрированными. В собранном стиле `backend/static/css/tailwind.min.css` класс `.container` включает `margin-left: auto; margin-right: auto; padding-left/right: 1rem`, что обеспечивает выравнивание по центру.
- **Причина отклонения:** первичное сообщение о регрессии не подтверждено. Ветки разработки содержат корректную конфигурацию Tailwind и актуальный собранный CSS.
- **Рекомендации по ремедиации:** дополнительных действий не требуется. При последующих изменениях стилей запускать пересборку Tailwind и проверять, что `backend/static/css/tailwind.min.css` синхронизирован с `tailwind.config.js`.
- **Примечания:** для быстрой валидации можно выполнить `python backend/manage.py runserver` и проверить центрирование в браузере либо проинспектировать класс `.container` в собранном CSS.
