"""Base settings for the «Союзлифт Аудит» Django project."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List

from django.urls import reverse_lazy

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean flag from the environment."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: Iterable[str] | None = None) -> List[str]:
    """Read a comma-separated list from the environment."""
    raw_value = os.environ.get(name)
    if not raw_value:
        if default is None:
            return []
        return [item for item in default]
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    """Read an integer value from the environment."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


ENVIRONMENT = os.environ.get("DJANGO_ENV", "dev").strip().lower()
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])  # type: ignore[assignment]
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "catalog",
    "audits",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.primary_navigation",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db" / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Tomsk"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
PROTECTED_MEDIA_ROOT = BASE_DIR / "protected_media"
AUDIT_ATTACHMENT_URL_MAX_AGE = env_int("DJANGO_AUDIT_ATTACHMENT_URL_MAX_AGE", 300)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("DJANGO_EMAIL_PORT", 587)
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("DJANGO_EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("DJANGO_EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = env_int("DJANGO_EMAIL_TIMEOUT", 10)
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "noreply@souzlift.local")
SERVER_EMAIL = os.environ.get("DJANGO_SERVER_EMAIL", DEFAULT_FROM_EMAIL)

LOGIN_URL = reverse_lazy("accounts:login")
LOGIN_REDIRECT_URL = reverse_lazy("accounts:dashboard")
LOGOUT_REDIRECT_URL = reverse_lazy("accounts:login")

LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO")


def _resolve_log_path(env_var: str, default: Path) -> Path:
    """Resolve a log file path and ensure that its directory exists."""

    candidate = os.environ.get(env_var)
    path = Path(candidate) if candidate else default
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # In restricted environments (e.g. read-only directories) we silently
        # ignore the error. Logging will still work if the path is writable.
        pass
    return path


LOG_DIR = Path(os.environ.get("DJANGO_LOG_DIR", BASE_DIR / "logs"))
MAIN_LOG_FILE = _resolve_log_path("DJANGO_LOG_FILE", LOG_DIR / "app.log")
OFFLINE_SYNC_LOG_FILE = _resolve_log_path(
    "DJANGO_SYNC_LOG_FILE", LOG_DIR / "offline-sync-errors.log"
)
LOG_ROTATION_MAX_BYTES = env_int("DJANGO_LOG_MAX_BYTES", 5 * 1024 * 1024)
LOG_ROTATION_BACKUP_COUNT = env_int("DJANGO_LOG_BACKUP_COUNT", 10)
OFFLINE_SYNC_LOG_MAX_BYTES = env_int(
    "DJANGO_SYNC_LOG_MAX_BYTES", LOG_ROTATION_MAX_BYTES
)
OFFLINE_SYNC_LOG_BACKUP_COUNT = env_int(
    "DJANGO_SYNC_LOG_BACKUP_COUNT", LOG_ROTATION_BACKUP_COUNT
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
        "simple": {
            "format": "%(levelname)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "level": LOG_LEVEL,
        },
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "verbose",
            "filename": str(MAIN_LOG_FILE),
            "maxBytes": LOG_ROTATION_MAX_BYTES,
            "backupCount": LOG_ROTATION_BACKUP_COUNT,
            "encoding": "utf-8",
            "level": LOG_LEVEL,
            "delay": True,
        },
        "offline_sync_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "verbose",
            "filename": str(OFFLINE_SYNC_LOG_FILE),
            "maxBytes": OFFLINE_SYNC_LOG_MAX_BYTES,
            "backupCount": OFFLINE_SYNC_LOG_BACKUP_COUNT,
            "encoding": "utf-8",
            "level": "INFO",
            "delay": True,
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "audits.offline_sync": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
}

__all__ = [
    "BASE_DIR",
    "ENVIRONMENT",
    "SECRET_KEY",
    "DEBUG",
    "ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS",
    "INSTALLED_APPS",
    "MIDDLEWARE",
    "ROOT_URLCONF",
    "TEMPLATES",
    "WSGI_APPLICATION",
    "DATABASES",
    "AUTH_PASSWORD_VALIDATORS",
    "LANGUAGE_CODE",
    "TIME_ZONE",
    "USE_I18N",
    "USE_TZ",
    "STATIC_URL",
    "STATICFILES_DIRS",
    "STATIC_ROOT",
    "STATICFILES_STORAGE",
    "MEDIA_URL",
    "MEDIA_ROOT",
    "PROTECTED_MEDIA_ROOT",
    "AUDIT_ATTACHMENT_URL_MAX_AGE",
    "DEFAULT_AUTO_FIELD",
    "EMAIL_BACKEND",
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS",
    "EMAIL_USE_SSL",
    "EMAIL_TIMEOUT",
    "DEFAULT_FROM_EMAIL",
    "SERVER_EMAIL",
    "LOGIN_URL",
    "LOGIN_REDIRECT_URL",
    "LOGOUT_REDIRECT_URL",
    "LOG_DIR",
    "MAIN_LOG_FILE",
    "OFFLINE_SYNC_LOG_FILE",
    "LOG_LEVEL",
    "LOG_ROTATION_MAX_BYTES",
    "LOG_ROTATION_BACKUP_COUNT",
    "OFFLINE_SYNC_LOG_MAX_BYTES",
    "OFFLINE_SYNC_LOG_BACKUP_COUNT",
    "LOGGING",
    "env_bool",
    "env_int",
    "env_list",
]
