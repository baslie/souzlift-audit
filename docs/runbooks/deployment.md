# Продакшен-развёртывание

Документ описывает типовой сценарий вывода «Союзлифт Аудит» в продакшен согласно [архитектуре 3.0](../architecture/v3.md#8-%D1%82%D0%B5%D1%85%D0%BD%D0%B8%D1%87%D0%B5%D1%81%D0%BA%D0%B0%D1%8F-%D1%80%D0%B5%D0%B0%D0%BB%D0%B8%D0%B7%D0%B0%D1%86%D0%B8%D1%8F) и плану задач [T11.1](../../AGENTS.md). Рекомендации рассчитаны на виртуальный сервер под Linux (Ubuntu 22.04 LTS или совместимую систему) с обратным прокси Nginx и приложением, работающим под `gunicorn`. При необходимости их можно адаптировать под `uWSGI` (см. раздел 6).

> **Важно.** Перед внедрением на боевом окружении скорректируйте параметры домена, путей и прав пользователя в соответствии с инфраструктурой заказчика.

## 1. Подготовка сервера

1. Создайте системного пользователя без прав входа по паролю (пример: `appuser`) и каталог проекта:
   ```bash
   sudo adduser --system --group --home /opt/souzlift appuser
   sudo mkdir -p /opt/souzlift
   sudo chown appuser:appuser /opt/souzlift
   ```
2. Установите системные зависимости:
   ```bash
   sudo apt update
   sudo apt install -y python3.11 python3.11-venv python3-pip nginx git sqlite3
   ```
3. По согласованию с безопасностью откройте входящие соединения только по портам 22 (SSH) и 443/80 (HTTPS/HTTP) либо используйте встроенный firewall (`ufw allow 'Nginx Full'`).

## 2. Развёртывание приложения

1. Склонируйте репозиторий и переключитесь на последнюю стабильную ветку:
   ```bash
   sudo -u appuser git clone https://git.example.com/souzlift.git /opt/souzlift
   cd /opt/souzlift
   sudo -u appuser git checkout main
   ```
2. Создайте и активируйте виртуальное окружение:
   ```bash
   sudo -u appuser python3.11 -m venv /opt/souzlift/.venv
   sudo -u appuser /opt/souzlift/.venv/bin/pip install --upgrade pip
   sudo -u appuser /opt/souzlift/.venv/bin/pip install -r requirements.txt
   ```
3. Скопируйте файл окружения и заполните значения (см. раздел 3):
   ```bash
   sudo cp deploy/souzlift.env.example /etc/souzlift.env
   sudo chown root:appuser /etc/souzlift.env
   sudo chmod 640 /etc/souzlift.env
   sudo -u appuser nano /etc/souzlift.env
   ```
4. Выполните миграции и сборку статики:
   ```bash
   sudo -u appuser DJANGO_ENV=prod /opt/souzlift/.venv/bin/python manage.py migrate
   sudo -u appuser DJANGO_ENV=prod /opt/souzlift/.venv/bin/python manage.py collectstatic --noinput
   ```
5. Создайте суперпользователя (при первом запуске):
   ```bash
   sudo -u appuser DJANGO_ENV=prod /opt/souzlift/.venv/bin/python manage.py createsuperuser
   ```
   Профиль создаваемого пользователя получает роль «Аудитор». Сразу после
   создания назначьте ему роль администратора, иначе в основном интерфейсе будут
   доступны только функции аудитора. Сделать это можно через панель
   администратора (`/admin/accounts/userprofile/`) либо командой:

   ```bash
   sudo -u appuser DJANGO_ENV=prod /opt/souzlift/.venv/bin/python manage.py shell <<'PY'
from django.contrib.auth import get_user_model

User = get_user_model()
user = User.objects.get(username="<ваш_логин>")
profile = user.profile
profile.role = profile.Roles.ADMIN
profile.save(update_fields=["role"])
print(f"Пользователь {user.username} переведён в роль администратора")
PY
   ```
   Замените `<ваш_логин>` на имя созданного пользователя. После выполнения в
   консоли появится подтверждение о смене роли.

## 3. Переменные окружения

Шаблон `/etc/souzlift.env` содержит минимальный набор переменных. Обязательно задайте уникальные значения секретов и доменных имён.

| Переменная | Назначение |
|------------|------------|
| `DJANGO_ENV` | Профиль конфигурации (`prod` для боевого стенда). |
| `DJANGO_SECRET_KEY` | Секретный ключ Django. Сгенерируйте через `python -c "import secrets; print(secrets.token_urlsafe(50))"`. |
| `DJANGO_ALLOWED_HOSTS` | Список доменов и IP-адресов, с которых принимаются запросы (через запятую). |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Полные URL с префиксом `https://` для защиты CSRF. |
| `DJANGO_DB_PATH` | Путь к SQLite-файлу (например, `/opt/souzlift/backend/db/db.sqlite3`). |
| `DJANGO_STATIC_ROOT` | Путь к каталогу статики (`/opt/souzlift/backend/staticfiles`). |
| `DJANGO_MEDIA_ROOT` | Путь к каталогу медиа (`/opt/souzlift/backend/media`). |
| `DJANGO_LOG_DIR` | Каталог логов (`/var/log/souzlift`). |
| `DJANGO_EMAIL_*` | Почтовые настройки согласно [docs/runbooks/operations.md](operations.md). |
| `DJANGO_EMAIL_NOTIFICATIONS_ENABLED` | Включение почтовых уведомлений (по умолчанию `false`, включайте только при настроенном SMTP). |
| `DJANGO_SECURE_*` | HTTPS-настройки (HSTS, редиректы) в соответствии с политикой безопасности. |

При необходимости добавьте переменные SMTP, OAuth и другие настройки, описанные в [docs/runbooks/operations.md](operations.md).

## 4. Служба systemd для gunicorn

В каталоге `deploy/` подготовлен шаблон `gunicorn.service`. Скопируйте его в `/etc/systemd/system/` и перезапустите конфигурацию systemd:

```bash
sudo cp /opt/souzlift/deploy/gunicorn.service /etc/systemd/system/gunicorn.service
sudo systemctl daemon-reload
sudo systemctl enable gunicorn
sudo systemctl start gunicorn
sudo systemctl status gunicorn
```

Шаблон использует `EnvironmentFile=/etc/souzlift.env` и запускает приложение от пользователя `appuser`. При изменении путей или имён пользователя обновите юнит-файл. Для управления процессом доступны стандартные команды:

- `sudo systemctl restart gunicorn`
- `sudo systemctl stop gunicorn`
- `journalctl -u gunicorn -f` — просмотр логов.

Файл `deploy/gunicorn.conf.py` задаёт подключение к сокету `/run/gunicorn/gunicorn.sock`, параметры журналирования и количество воркеров (по умолчанию — половина доступных ядер, но не менее двух). При изменении конфигурации сервера скорректируйте значения `workers`, `threads`, `timeout` и пути к логам.

## 5. Конфигурация Nginx

Шаблон `deploy/nginx.conf` предполагает, что gunicorn слушает сокет `/run/gunicorn/gunicorn.sock`. Основные шаги установки:

```bash
sudo cp /opt/souzlift/deploy/nginx.conf /etc/nginx/sites-available/souzlift.conf
sudo ln -s /etc/nginx/sites-available/souzlift.conf /etc/nginx/sites-enabled/souzlift.conf
sudo nginx -t
sudo systemctl reload nginx
```

Убедитесь, что каталоги статики и медиа соответствуют настройкам Django (`DJANGO_STATIC_ROOT`, `DJANGO_MEDIA_ROOT`). Для включения HTTPS используйте `certbot` или корпоративный PKI и обновите блок `server` сертификатами `ssl_certificate`/`ssl_certificate_key`.
Если требуется принудительный редирект с HTTP на HTTPS, добавьте в HTTP-блок строку `return 301 https://$host$request_uri;`.

### 5.1. SELinux и AppArmor

Если сервер работает с включённым SELinux/AppArmor, выдайте разрешения на доступ Nginx к сокету и медиа-каталогам:

```bash
sudo setsebool -P httpd_can_network_connect 1
sudo chcon -Rt httpd_sys_content_t /opt/souzlift/backend/staticfiles
sudo chcon -Rt httpd_sys_rw_content_t /opt/souzlift/backend/media
```

Команды могут отличаться в зависимости от политики безопасности заказчика.

## 6. Альтернативный вариант на uWSGI

При необходимости заменить gunicorn на `uWSGI`:

1. Установите пакет `uwsgi` и Python-плагин: `sudo apt install -y uwsgi uwsgi-plugin-python3`.
2. Создайте юнит `deploy/uwsgi.service` по аналогии с `gunicorn.service` и укажите запуск `uwsgi --ini /opt/souzlift/deploy/uwsgi.ini`.
3. Настройте `deploy/uwsgi.ini` с параметрами `chdir`, `module=backend.config.wsgi:application`, `home=/opt/souzlift/.venv`, `socket=/run/uwsgi.sock`, `vacuum=true`.
4. Обновите конфигурацию Nginx, заменив `proxy_pass http://unix:/run/gunicorn/gunicorn.sock` на `uwsgi_pass unix:/run/uwsgi.sock;` и добавив `include uwsgi_params;`.

Шаблоны для `uWSGI` можно добавить позднее при переходе на этот серверный стек.

## 7. Проверка после запуска

1. Убедитесь, что служба активна: `sudo systemctl status gunicorn`.
2. Проверьте логи приложения: `journalctl -u gunicorn --since "5 minutes ago"` и `/var/log/souzlift/*.log`.
3. Выполните HTTP-запрос к `/healthz/` (будет доступен после реализации T5.x) или зайдите в административную панель.
4. Прогоните smoke-проверки:
   ```bash
   sudo -u appuser DJANGO_ENV=prod /opt/souzlift/.venv/bin/python manage.py check
   sudo -u appuser DJANGO_ENV=prod /opt/souzlift/.venv/bin/pytest --maxfail=1 --disable-warnings
   ```
5. Контролируйте использование диска и резервные копии согласно [docs/runbooks/operations.md](operations.md).

## 8. Обновление приложения

Для выпуска новой версии выполните шаги из [docs/runbooks/operations.md](operations.md#13-%D1%80%D0%B0%D0%B7%D0%B2%D1%91%D1%80%D1%82%D1%8B%D0%B2%D0%B0%D0%BD%D0%B8%D0%B5-%D0%BD%D0%B0-%D0%BF%D1%80%D0%BE%D0%B4%D0%B0%D0%BA%D1%88%D0%B5%D0%BD%D0%B5) и перезапустите службы. Перед обновлением обязательно создайте резервную копию (раздел 2 в `operations.md`).

## 9. Чек-лист готовности

- [ ] Права на каталоги `/opt/souzlift`, `/var/log/souzlift`, `/run/gunicorn/gunicorn.sock` принадлежат пользователю `appuser` и группе `appuser`.
- [ ] Файл `/etc/souzlift.env` заполнен и защищён (`640`).
- [ ] `systemctl status gunicorn` и `systemctl status nginx` показывают состояние `active (running)`.
- [ ] HTTPS-сертификаты установлены и проверены на истечение срока действия.
- [ ] Настроены cron-задачи резервного копирования и обслуживания (см. `scripts/`).
- [ ] Выполнены smoke-проверки и тестовый вход в систему под администратором.

Документ актуализируется при изменении архитектуры или политик эксплуатации.
