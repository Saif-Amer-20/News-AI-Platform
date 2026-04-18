from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: str = "") -> list[str]:
    value = os.getenv(key, default)
    return [item.strip() for item in value.split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django_prometheus",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "core",
    "accounts",
    "topics",
    "sources",
    "alerts",
    "cases",
    "ops",
    "validation",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

POSTGRES_DB = env("POSTGRES_DB", "newsintel")
POSTGRES_USER = env("POSTGRES_USER", "newsintel")
POSTGRES_PASSWORD = env("POSTGRES_PASSWORD", "")
POSTGRES_HOST = env("POSTGRES_HOST", "postgres")
POSTGRES_PORT = env("POSTGRES_PORT", "5432")

DATABASES = {
    "default": {
        "ENGINE": "django_prometheus.db.backends.postgresql",
        "NAME": POSTGRES_DB,
        "USER": POSTGRES_USER,
        "PASSWORD": POSTGRES_PASSWORD,
        "HOST": POSTGRES_HOST,
        "PORT": POSTGRES_PORT,
        "CONN_MAX_AGE": 60,
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Baghdad"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/backend-static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
}

from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "SAMEORIGIN"

REDIS_HOST = env("REDIS_HOST", "redis")
REDIS_PORT = int(env("REDIS_PORT", "6379"))
CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://redis:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# ── Worker performance limits ─────────────────────────────────────────
CELERY_WORKER_CONCURRENCY = 2           # max 2 concurrent tasks (was unlimited/CPU count)
CELERY_WORKER_PREFETCH_MULTIPLIER = 1   # don't prefetch — prevents task pile-up
CELERY_TASK_SOFT_TIME_LIMIT = 1800      # soft limit: 30 minutes
CELERY_TASK_TIME_LIMIT = 3600           # hard limit: 1 hour (kill runaway tasks)
CELERY_WORKER_MAX_TASKS_PER_CHILD = 50  # recycle worker processes to free memory

CELERY_BEAT_SCHEDULE = {
    "dispatch-active-source-fetches": {
        "task": "sources.tasks.dispatch_active_source_fetches",
        "schedule": 600.0,  # every 10 minutes (was 5)
    },
    "update-source-reliability": {
        "task": "sources.tasks.update_source_reliability_task",
        "schedule": 7200.0,  # every 2 hours (was 1h)
    },
    "resolve-orphan-events": {
        "task": "sources.tasks.resolve_orphan_events_task",
        "schedule": 1800.0,  # every 30 minutes (was 10)
    },
    "merge-duplicate-entities": {
        "task": "sources.tasks.merge_duplicate_entities_task",
        "schedule": 7200.0,  # every 2 hours (was 30m)
    },
    "refresh-event-intelligence": {
        "task": "sources.tasks.refresh_event_intelligence_task",
        "schedule": 3600.0,  # every 1 hour (was 20m)
    },
    "bootstrap-search-indices": {
        "task": "sources.tasks.bootstrap_search_indices_task",
        "schedule": 86400.0,  # daily — idempotent
    },
    "bootstrap-graph-schema": {
        "task": "sources.tasks.bootstrap_graph_schema_task",
        "schedule": 86400.0,  # daily — idempotent
    },
    "generate-intel-assessments": {
        "task": "sources.tasks.generate_intel_assessments_task",
        "schedule": 7200.0,  # every 2 hours (was 45m)
    },
    "run-anomaly-detection": {
        "task": "sources.tasks.run_anomaly_detection_task",
        "schedule": 1800.0,  # every 30 minutes (was 10)
    },
    "run-signal-correlation": {
        "task": "sources.tasks.run_signal_correlation_task",
        "schedule": 3600.0,  # every 1 hour (was 15m)
    },
    "run-predictive-scoring": {
        "task": "sources.tasks.run_predictive_scoring_task",
        "schedule": 3600.0,  # every 1 hour (was 20m)
    },
    "run-historical-pattern-matching": {
        "task": "sources.tasks.run_historical_pattern_matching_task",
        "schedule": 7200.0,  # every 2 hours (was 1h)
    },
    "run-geo-radar": {
        "task": "sources.tasks.run_geo_radar_task",
        "schedule": 3600.0,  # every 1 hour (was 15m)
    },

    # ── Self-Learning Intelligence Layer ──────────────────────
    "auto-evaluate-predictions": {
        "task": "sources.tasks.auto_evaluate_predictions_task",
        "schedule": 7200.0,  # every 2 hours (was 1h)
    },
    "update-source-reputations": {
        "task": "sources.tasks.update_source_reputations_task",
        "schedule": 14400.0,  # every 4 hours (was 2h)
    },
    "run-adaptive-learning-cycle": {
        "task": "sources.tasks.run_adaptive_learning_cycle_task",
        "schedule": 28800.0,  # every 8 hours (was 4h)
    },
    "capture-learning-records": {
        "task": "sources.tasks.capture_learning_records_task",
        "schedule": 7200.0,  # every 2 hours (was 1h)
    },
    "bootstrap-adaptive-thresholds": {
        "task": "sources.tasks.bootstrap_adaptive_thresholds_task",
        "schedule": 86400.0,  # daily — idempotent
    },

    # ── AI-Driven Entity Consolidation ─────────────────────────
    "background-entity-consolidation": {
        "task": "sources.tasks.background_entity_consolidation_task",
        "schedule": 7200.0,  # every 2 hours (was 20m!)
    },

    # ── Entity Intelligence Layer ───────────────────────────────
    "rebuild-entity-relationships": {
        "task": "sources.tasks.rebuild_entity_relationships_task",
        "schedule": 7200.0,  # every 2 hours (was 30m!)
    },
    "score-entity-intelligence": {
        "task": "sources.tasks.score_entity_intelligence_task",
        "schedule": 3600.0,  # every 1 hour (was 15m!)
    },
}

OPENSEARCH_URL = env("OPENSEARCH_URL", "http://opensearch:9200")
NEO4J_URI = env("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = env("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = env("NEO4J_PASSWORD", "")
MINIO_ENDPOINT = env("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = env("MINIO_ACCESS_KEY", env("MINIO_ROOT_USER", ""))
MINIO_SECRET_KEY = env("MINIO_SECRET_KEY", env("MINIO_ROOT_PASSWORD", ""))
MINIO_RAW_BUCKET = env("MINIO_RAW_BUCKET", "newsintel-raw")
NEWSAPI_KEY = env("NEWSAPI_KEY", "")
GNEWS_KEY = env("GNEWS_KEY", "")
GROQ_API_KEY = env("GROQ_API_KEY", "")
HTTP_USER_AGENT = env(
    "HTTP_USER_AGENT",
    "NewsIntelBot/1.0 (+https://localhost/internal-ingestion)",
)

PLATFORM_NAME = env("PLATFORM_NAME", "News Intelligence Platform")
PLATFORM_ENV = env("PLATFORM_ENV", "production")

LOG_LEVEL = env("DJANGO_LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "gunicorn": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
