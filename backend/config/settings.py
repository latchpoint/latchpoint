from __future__ import annotations

import os
import sys
import json
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
IS_TESTING = "test" in sys.argv

env_file = env.str("ENV_FILE", default=None)
for candidate in [env_file, BASE_DIR / ".env", BASE_DIR.parent / ".env"]:
    if not candidate:
        continue
    candidate_path = Path(candidate)
    if candidate_path.exists():
        env.read_env(candidate_path)
        break

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-secret-key")
DEBUG = env.bool("DEBUG", default=False)
NOTIFICATIONS_DELIVERY_LOCK_TIMEOUT_SECONDS = env.int(
    "NOTIFICATIONS_DELIVERY_LOCK_TIMEOUT_SECONDS",
    default=60,
)
# Keep a copy of the explicit list even if we later expand to "*"
# so we can use it for dev-only conveniences like CSRF trusted origins.
RAW_ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
ALLOWED_HOSTS = RAW_ALLOWED_HOSTS
if env.bool("ALLOW_ALL_HOSTS", default=False):
    ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if DEBUG and not CSRF_TRUSTED_ORIGINS:
    # In dev the frontend often runs on a different port (or is reverse-proxied),
    # causing Django's origin check to reject POSTs unless explicitly trusted.
    dev_ports = (5427, 5428, 5173, 3000)
    dev_hosts = {"localhost", "127.0.0.1", *RAW_ALLOWED_HOSTS}
    dev_hosts.discard("*")
    CSRF_TRUSTED_ORIGINS = [
        f"http://{host}:{port}" for host in sorted(dev_hosts) for port in dev_ports
    ]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "channels",
    "scheduler.apps.SchedulerConfig",
    "accounts",
    "alarm",
    "control_panels.apps.ControlPanelsConfig",
    "transports_mqtt.apps.TransportsMqttConfig",
    "integrations_home_assistant.apps.IntegrationsHomeAssistantConfig",
    "integrations_zwavejs.apps.IntegrationsZwavejsConfig",
    "integrations_zigbee2mqtt.apps.IntegrationsZigbee2mqttConfig",
    "integrations_frigate.apps.IntegrationsFrigateConfig",
    "notifications.apps.NotificationsConfig",
    "locks",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env.str("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

API_RESPONSE_ENVELOPE_ENABLED = env.bool("API_RESPONSE_ENVELOPE_ENABLED", default=True)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.BearerTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        *(
            ["config.renderers.EnvelopeJSONRenderer"]
            if API_RESPONSE_ENVELOPE_ENABLED
            else ["rest_framework.renderers.JSONRenderer"]
        ),
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "EXCEPTION_HANDLER": "config.exception_handler.custom_exception_handler",
}

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)
CORS_ALLOW_CREDENTIALS = True

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

ALLOW_HOME_ASSISTANT_IN_TESTS = env.bool("ALLOW_HOME_ASSISTANT_IN_TESTS", default=False)

# Z-Wave JS integration (configured via alarm-profile settings; connectivity should be test-gated)
ALLOW_ZWAVEJS_IN_TESTS = env.bool("ALLOW_ZWAVEJS_IN_TESTS", default=False)

# Scheduler
SCHEDULER_ENABLED = env.bool("SCHEDULER_ENABLED", default=True)
SCHEDULER_LEADER_LOCK_ENABLED = env.bool("SCHEDULER_LEADER_LOCK_ENABLED", default=False)
SCHEDULER_LEADER_LOCK_ID = env.int("SCHEDULER_LEADER_LOCK_ID", default=4242001)
SCHEDULER_INSTANCE_ID = env.str("SCHEDULER_INSTANCE_ID", default="").strip() or None
SCHEDULER_FAILURE_EVENT_THRESHOLD = env.int("SCHEDULER_FAILURE_EVENT_THRESHOLD", default=3)
SCHEDULER_SLOW_RUN_THRESHOLD_SECONDS = env.float("SCHEDULER_SLOW_RUN_THRESHOLD_SECONDS", default=2.0)
SCHEDULER_RUN_HISTORY_RETENTION_DAYS = env.int("SCHEDULER_RUN_HISTORY_RETENTION_DAYS", default=30)
SCHEDULER_RUN_HISTORY_MAX_PER_TASK = env.int("SCHEDULER_RUN_HISTORY_MAX_PER_TASK", default=500)
_SCHEDULER_TASK_OVERRIDES_RAW = env.str("SCHEDULER_TASK_OVERRIDES", default="{}").strip()
try:
    SCHEDULER_TASK_OVERRIDES = (
        json.loads(_SCHEDULER_TASK_OVERRIDES_RAW) if _SCHEDULER_TASK_OVERRIDES_RAW else {}
    )
except Exception:
    SCHEDULER_TASK_OVERRIDES = {}

HA_LOG_LEVEL = env.str("HA_LOG_LEVEL", default=env.str("LOG_LEVEL", default="INFO")).upper()
if IS_TESTING and not ALLOW_HOME_ASSISTANT_IN_TESTS:
    HA_LOG_LEVEL = "WARNING"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO").upper()},
    "loggers": {
        "integrations_zwavejs": {
            "handlers": ["console"],
            "level": env.str("ZWAVEJS_LOG_LEVEL", default=env.str("LOG_LEVEL", default="INFO")).upper(),
            "propagate": False,
        },
        "control_panels": {
            "handlers": ["console"],
            "level": env.str("CONTROL_PANELS_LOG_LEVEL", default=env.str("LOG_LEVEL", default="INFO")).upper(),
            "propagate": False,
        },
        "integrations_home_assistant": {
            "handlers": ["console"],
            "level": HA_LOG_LEVEL,
            "propagate": False,
        },
        "alarm.middleware": {
            "handlers": ["console"],
            "level": env.str("WS_LOG_LEVEL", default=env.str("LOG_LEVEL", default="INFO")).upper(),
            "propagate": False,
        },
        "alarm.consumers": {
            "handlers": ["console"],
            "level": env.str("WS_LOG_LEVEL", default=env.str("LOG_LEVEL", default="INFO")).upper(),
            "propagate": False,
        },
    },
}
