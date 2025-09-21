"""Production settings for the «Союзлифт Аудит» project."""
from __future__ import annotations

import os

from . import base as base_settings

globals().update({name: getattr(base_settings, name) for name in base_settings.__all__})

BASE_DIR = base_settings.BASE_DIR
ALLOWED_HOSTS = base_settings.ALLOWED_HOSTS
CSRF_TRUSTED_ORIGINS = base_settings.CSRF_TRUSTED_ORIGINS
env_bool = base_settings.env_bool
env_int = base_settings.env_int
LOGGING = base_settings.LOGGING
LOG_LEVEL = base_settings.LOG_LEVEL

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

# Logging configuration with rotating file handlers for production deployments.
LOGGING["loggers"]["django"]["handlers"] = ["console", "app_file"]
LOGGING["loggers"]["django.request"]["handlers"] = ["console", "app_file"]
LOGGING["root"]["handlers"] = ["console", "app_file"]
