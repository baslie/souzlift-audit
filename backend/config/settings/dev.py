"""Development settings for the «Союзлифт Аудит» project."""
from __future__ import annotations

from .base import *  # noqa: F401,F403

DEBUG = env_bool("DJANGO_DEBUG", True)

# Ensure local hosts are always allowed during development and testing.
for host in ["localhost", "127.0.0.1", "testserver"]:
    if host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = "localhost"
EMAIL_PORT = 1025
EMAIL_USE_TLS = False
EMAIL_USE_SSL = False

LOGGING["handlers"]["console"]["formatter"] = "simple"
LOGGING["handlers"]["console"]["level"] = "DEBUG" if DEBUG else LOG_LEVEL
LOGGING["loggers"]["django"]["handlers"] = ["console"]
LOGGING["root"]["level"] = "DEBUG" if DEBUG else LOG_LEVEL

# В режиме разработки и тестирования используем обычное хранение статики,
# чтобы избежать ошибок manifest при отсутствии сборки Tailwind.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
