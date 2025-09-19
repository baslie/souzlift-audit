"""Production settings for the «Союзлифт Аудит» project."""
from __future__ import annotations

import os
from pathlib import Path

from .base import *  # noqa: F401,F403

DEBUG = False

if not ALLOWED_HOSTS:
    raise RuntimeError(
        "DJANGO_ALLOWED_HOSTS must be configured for the production environment."
    )

if not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = [
        f"https://{host}"
        for host in ALLOWED_HOSTS
        if host not in {"localhost", "127.0.0.1"}
    ]

SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", True
)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", True)
SECURE_REFERRER_POLICY = os.environ.get("DJANGO_SECURE_REFERRER_POLICY", "same-origin")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"

# Logging configuration with rotating file handler for production deployments.
log_file = Path(os.environ.get("DJANGO_LOG_FILE", str(BASE_DIR / "logs" / "app.log")))
log_file.parent.mkdir(parents=True, exist_ok=True)
LOGGING["handlers"]["file"] = {
    "class": "logging.handlers.RotatingFileHandler",
    "formatter": "verbose",
    "filename": str(log_file),
    "maxBytes": env_int("DJANGO_LOG_MAX_BYTES", 5 * 1024 * 1024),
    "backupCount": env_int("DJANGO_LOG_BACKUP_COUNT", 10),
    "encoding": "utf-8",
    "level": LOG_LEVEL,
}
LOGGING["loggers"]["django"]["handlers"] = ["console", "file"]
LOGGING["loggers"]["django.request"]["handlers"] = ["console", "file"]
LOGGING["root"]["handlers"] = ["console", "file"]
