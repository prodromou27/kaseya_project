"""Django settings for the Odyssey Kaseya Analytics & Reporting Portal.

One settings module, driven by environment variables. ``DJANGO_ENV`` selects
``development`` / ``test`` / ``production`` defaults; production refuses insecure values.
"""

from __future__ import annotations

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .env import env_bool, env_int, env_list, env_str

BASE_DIR = Path(__file__).resolve().parent.parent

DJANGO_ENV = env_str("DJANGO_ENV", "development")
if DJANGO_ENV not in {"development", "test", "production"}:
    raise ImproperlyConfigured("DJANGO_ENV must be development, test or production.")
IS_PRODUCTION = DJANGO_ENV == "production"

DEBUG = env_bool("DJANGO_DEBUG", default=DJANGO_ENV == "development")
if IS_PRODUCTION and DEBUG:
    raise ImproperlyConfigured("DJANGO_DEBUG must be false in production.")

SECRET_KEY = env_str(
    "DJANGO_SECRET_KEY",
    default="dev-only-insecure-secret-key-change-me" if not IS_PRODUCTION else None,
    required=IS_PRODUCTION,
)
if IS_PRODUCTION and (SECRET_KEY.startswith("dev-only") or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong, unique value in production.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])
# Extra names/IPs the portal is opened with (e.g. the server IP before DNS exists). HTTPS origins only.
PORTAL_EXTRA_HOSTS = env_list("PORTAL_EXTRA_HOSTS", [])
ALLOWED_HOSTS += [h for h in PORTAL_EXTRA_HOSTS if h not in ALLOWED_HOSTS]
CSRF_TRUSTED_ORIGINS += [f"https://{h}" for h in PORTAL_EXTRA_HOSTS if f"https://{h}" not in CSRF_TRUSTED_ORIGINS]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.core",
    "apps.accounts",
    "apps.customers",
    "apps.integrations",
    "apps.audit",
    "apps.reporting",
    "apps.inventory",
    "apps.software",
    "apps.patching",
    "apps.onboarding",
]

MIDDLEWARE = [
    "apps.core.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.SessionTimeoutMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

# --- Database: PostgreSQL only. SQLite is never used, including in tests. ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": env_str("POSTGRES_HOST", "localhost"),
        "PORT": env_int("POSTGRES_PORT", 5432),
        "NAME": env_str("POSTGRES_DB", "portal"),
        "USER": env_str("POSTGRES_USER", "portal"),
        "PASSWORD": env_str("POSTGRES_PASSWORD", "portal" if not IS_PRODUCTION else None, required=IS_PRODUCTION),
        "CONN_MAX_AGE": env_int("POSTGRES_CONN_MAX_AGE", 60),
        "OPTIONS": {"sslmode": env_str("POSTGRES_SSLMODE", "prefer")},
        "TEST": {"NAME": env_str("POSTGRES_TEST_DB", "test_portal")},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 14}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Sessions & cookies (server-side DB sessions; nothing sensitive in browser storage) ---
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "okp_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=IS_PRODUCTION)
SESSION_IDLE_TIMEOUT_SECONDS = env_int("SESSION_IDLE_TIMEOUT_SECONDS", 30 * 60)
SESSION_ABSOLUTE_TIMEOUT_SECONDS = env_int("SESSION_ABSOLUTE_TIMEOUT_SECONDS", 10 * 60 * 60)
SESSION_COOKIE_AGE = SESSION_IDLE_TIMEOUT_SECONDS
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_NAME = "okp_csrftoken"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # SPA reads it to send X-CSRFToken; protected by SameSite + same origin.

if IS_PRODUCTION and not (SESSION_COOKIE_SECURE and CSRF_COOKIE_SECURE):
    raise ImproperlyConfigured("Secure cookies are mandatory in production.")

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if env_bool("TRUST_PROXY_TLS_HEADER") else None
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=False)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000 if IS_PRODUCTION else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = IS_PRODUCTION
# HSTS preload is for public domains; the portal is an internal host. Opt in explicitly if policy requires it.
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=False)
SILENCED_SYSTEM_CHECKS = [] if SECURE_HSTS_PRELOAD else ["security.W021"]
DATA_UPLOAD_MAX_MEMORY_SIZE = 1 * 1024 * 1024
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)

# --- Authentication ---
LOCAL_LOGIN_ENABLED = env_bool("LOCAL_LOGIN_ENABLED", default=not IS_PRODUCTION)
OIDC = {
    "ENABLED": env_bool("OIDC_ENABLED", default=False),
    "ISSUER": env_str("OIDC_ISSUER", ""),
    "CLIENT_ID": env_str("OIDC_CLIENT_ID", ""),
    "CLIENT_SECRET": env_str("OIDC_CLIENT_SECRET", ""),
    "REDIRECT_URI": env_str("OIDC_REDIRECT_URI", ""),
    "SCOPES": env_str("OIDC_SCOPES", "openid email profile"),
    "AUTO_PROVISION": env_bool("OIDC_AUTO_PROVISION", default=False),
    # Optional `amr` values that must be present in the ID token (e.g. "mfa"). MFA is primarily enforced
    # by IdP Conditional Access; this is a defence-in-depth check that must be validated in UAT (P5-01).
    "REQUIRED_AMR": env_list("OIDC_REQUIRED_AMR", []),
    "POST_LOGIN_REDIRECT": env_str("OIDC_POST_LOGIN_REDIRECT", "/"),
}
if OIDC["ENABLED"] and not all(OIDC[k] for k in ("ISSUER", "CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI")):
    raise ImproperlyConfigured(
        "OIDC_ENABLED requires OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET and OIDC_REDIRECT_URI."
    )
if OIDC["ENABLED"] and not OIDC["ISSUER"].startswith("https://"):
    raise ImproperlyConfigured("OIDC_ISSUER must use https.")

# --- DRF ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.SessionAuthentication401"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "apps.core.errors.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {"login": env_str("LOGIN_THROTTLE_RATE", "10/min")},
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Odyssey Kaseya Analytics & Reporting Portal API",
    "VERSION": "0.3.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
    "ENUM_NAME_OVERRIDES": {
        "UpdateStatusEnum": "apps.patching.models.UpdateStatus",
        "ReconciliationClassificationEnum": "apps.onboarding.models.Classification",
        "ReconciliationRunStateEnum": "apps.onboarding.models.ReconciliationRun.State",
        "ReviewedExpectationStateEnum": "apps.inventory.models.ExpectedSubnet.State",
        "HealthThresholdsStateEnum": "apps.inventory.models.HealthThresholds.State",
    },
}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
_redis_cache = env_str("REDIS_CACHE_URL", "")
if _redis_cache:
    CACHES["default"] = {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": _redis_cache}

# --- Celery ---
CELERY_BROKER_URL = env_str("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", default=DJANGO_ENV == "test")
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_DEFAULT_QUEUE = "maintenance"
CELERY_TASK_ROUTES = {
    "apps.reporting.tasks.*": {"queue": "reports"},
    "apps.integrations.tasks.run_sync": {"queue": "sync_vsa"},
}
CELERY_BEAT_SCHEDULE = {
    "dispatch-schedules": {"task": "apps.reporting.tasks.dispatch_schedules", "schedule": 60.0},
    "purge-expired-artifacts": {"task": "apps.reporting.tasks.purge_expired_artifacts", "schedule": 3600.0},
}
CELERY_TASK_ROUTES["apps.reporting.tasks.purge_expired_artifacts"] = {"queue": "maintenance"}
CELERY_TASK_ROUTES["apps.reporting.tasks.dispatch_schedules"] = {"queue": "maintenance"}
SYNC_MAX_DROP_RATIO = float(env_str("SYNC_MAX_DROP_RATIO", "0.5"))
DATA_STALE_AFTER_HOURS = env_int("DATA_STALE_AFTER_HOURS", 26)
CATALOG_REQUIRE_SEPARATE_REVIEWER = env_bool("CATALOG_REQUIRE_SEPARATE_REVIEWER", default=True)

# --- Report artifacts: private filesystem storage, never served directly by the proxy ---
REPORT_STORAGE_DIR = Path(env_str("REPORT_STORAGE_DIR", str(BASE_DIR / "var" / "reports")))
REPORT_ARTIFACT_TTL_HOURS = env_int("REPORT_ARTIFACT_TTL_HOURS", 24)
REPORT_MAX_ROWS = env_int("REPORT_MAX_ROWS", 100_000)

# --- VSA2 onboarding reconciliation: expected-inventory uploads (private storage, TTL, hard limits) ---
ONBOARDING_STORAGE_DIR = Path(env_str("ONBOARDING_STORAGE_DIR", str(BASE_DIR / "var" / "onboarding")))
ONBOARDING_UPLOAD_TTL_HOURS = env_int("ONBOARDING_UPLOAD_TTL_HOURS", 72)
ONBOARDING_MAX_UPLOAD_BYTES = env_int("ONBOARDING_MAX_UPLOAD_BYTES", 5 * 1024 * 1024)
ONBOARDING_MAX_ROWS = env_int("ONBOARDING_MAX_ROWS", 20_000)
# VSA4-03 device notifications: keep only this window, at most N most recent per device per sync.
NOTIFICATION_WINDOW_DAYS = env_int("NOTIFICATION_WINDOW_DAYS", 14)
NOTIFICATIONS_PER_DEVICE = env_int("NOTIFICATIONS_PER_DEVICE", 50)
CELERY_BEAT_SCHEDULE["purge-expired-onboarding-uploads"] = {
    "task": "apps.onboarding.tasks.purge_expired_uploads",
    "schedule": 3600.0,
}
CELERY_TASK_ROUTES["apps.onboarding.tasks.purge_expired_uploads"] = {"queue": "maintenance"}
CELERY_TASK_ROUTES["apps.onboarding.tasks.run_reconciliation"] = {"queue": "reports"}

# --- Connector egress policy (validated on every IntegrationInstance save; see apps.integrations.urlpolicy) ---
CONNECTOR_ALLOWED_HOSTS = {
    # VSA X server names are tenant-specific; administrators must list them explicitly.
    "vsa_x": env_list("CONNECTOR_ALLOWED_HOSTS_VSA_X", []),
    # Regional IT Glue API hosts as documented at https://api.itglue.com/developer (re-verify before P3).
    "itglue": env_list("CONNECTOR_ALLOWED_HOSTS_ITGLUE", ["api.itglue.com", "api.eu.itglue.com", "api.au.itglue.com"]),
    # Autotask zone hosts must be verified via zoneInformation in P4; no default is assumed here.
    "autotask": env_list("CONNECTOR_ALLOWED_HOSTS_AUTOTASK", []),
}
CONNECTOR_APPROVED_PRIVATE_CIDRS = env_list("CONNECTOR_APPROVED_PRIVATE_CIDRS", [])
# Fernet key(s) for API credentials entered in the portal. Comma-separated: the first encrypts, all decrypt (rotation).
# Lives in a Docker secret file on the host, never in the database. Empty = entering credentials in the portal is off.
CONNECTOR_ENCRYPTION_KEY = env_str("CONNECTOR_ENCRYPTION_KEY", "")

# --- Logging: structured JSON, redacted ---
LOG_LEVEL = env_str("LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "apps.core.logging.RequestIdFilter"},
        "redact": {"()": "apps.core.logging.RedactingFilter"},
    },
    "formatters": {"json": {"()": "apps.core.logging.JsonFormatter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id", "redact"],
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "django.request": {"level": "WARNING"},
    },
}
